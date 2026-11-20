"""Bambu Lab cloud API: sign in, find the account's printers.

Reverse-engineered by the community (see the ha-bambulab project); Bambu can change it
without notice, so every response is checked and failures raise BambuError with a short
message that is safe to show or log.
"""
import httpx

SERVICE = "deskhub-bambu"
HEADERS = {
    "User-Agent": "bambu_network_agent/01.09.05.01",
    "X-BBL-Client-Type": "slicer",
    "X-BBL-Client-Version": "01.09.05.51",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class BambuError(Exception):
    pass


class AuthError(BambuError):
    """Token or password rejected."""


def api_base(region: str) -> str:
    return "https://api.bambulab.cn" if region == "cn" else "https://api.bambulab.com"


def mqtt_host(region: str) -> str:
    return "cn.mqtt.bambulab.com" if region == "cn" else "us.mqtt.bambulab.com"


def make_client(**kw) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=20, **kw)


def _json(r: httpx.Response) -> dict:
    if r.status_code in (401, 403) and "json" not in r.headers.get("content-type", ""):
        raise BambuError(f"Bambu refused the request (HTTP {r.status_code}); "
                         "it may be blocking automated sign-ins right now")
    try:
        data = r.json()
    except ValueError:
        # Some sign-ins answer 200 with an empty body and the token in a cookie.
        if r.status_code == 200 and r.cookies.get("token"):
            return {"accessToken": r.cookies.get("token")}
        if r.status_code == 200 and not r.content.strip():
            return {}
        kind = r.headers.get("content-type", "").split(";")[0] or "no content type"
        raise BambuError(f"unexpected reply from Bambu (HTTP {r.status_code}, {kind}, "
                         f"{len(r.content)} bytes, not JSON)") from None
    if not isinstance(data, dict):
        raise BambuError("unexpected reply from Bambu")
    return data


def _post(client, region, path, body) -> dict:
    try:
        r = client.post(api_base(region) + path, json=body)
    except httpx.HTTPError as e:
        raise BambuError(f"could not reach Bambu ({type(e).__name__})") from None
    return _json(r)


def _result(data: dict) -> dict:
    """Login replies: {'accessToken': ...} on success, otherwise a message or a code request."""
    token = data.get("accessToken")
    if token:
        return {"status": "ok", "token": token}
    if data.get("loginType") == "verifyCode" or data.get("tfaKey"):
        return {"status": "code"}
    raise AuthError(str(data.get("message") or data.get("error") or "sign-in refused")[:120])


def login(client, region: str, account: str, password: str) -> dict:
    """-> {'status': 'ok', 'token': ...} or {'status': 'code'} (an emailed code is needed)."""
    data = _post(client, region, "/v1/user-service/user/login",
                 {"account": account, "password": password})
    # An empty 200 means the password passed but Bambu wants more; an emailed code
    # signs in without it.
    return {"status": "code"} if data == {} else _result(data)


def send_code(client, region: str, email: str):
    data = _post(client, region, "/v1/user-service/user/sendemail/code",
                 {"email": email, "type": "codeLogin"})
    if data.get("code") not in (None, 0, "0") or data.get("error"):
        raise BambuError(str(data.get("message") or data.get("error") or "could not send the code")[:120])


def login_with_code(client, region: str, account: str, code: str) -> str:
    data = _post(client, region, "/v1/user-service/user/login", {"account": account, "code": code})
    if data == {}:
        raise BambuError("Bambu sent an empty reply to the code sign-in")
    res = _result(data)
    if res["status"] != "ok":
        raise AuthError("that code was not accepted")
    return res["token"]


def _get(client, region, path, token) -> dict:
    try:
        r = client.get(api_base(region) + path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        raise BambuError(f"could not reach Bambu ({type(e).__name__})") from None
    if r.status_code in (401, 403) and "json" in r.headers.get("content-type", ""):
        raise AuthError("token rejected")
    return _json(r)


def get_uid(client, region: str, token: str) -> str:
    uid = _get(client, region, "/v1/design-user-service/my/preference", token).get("uid")
    if not uid:
        raise AuthError("token rejected (no user id in the reply)")
    return str(uid)


def list_printers(client, region: str, token: str) -> list[dict]:
    devices = _get(client, region, "/v1/iot-service/api/user/bind", token).get("devices")
    if not isinstance(devices, list):
        raise AuthError("token rejected (no device list in the reply)")
    return [{"serial": str(d.get("dev_id", "")), "name": str(d.get("name") or d.get("dev_id", "")),
             "model": str(d.get("dev_product_name") or ""), "online": bool(d.get("online"))}
            for d in devices if isinstance(d, dict) and d.get("dev_id")]
