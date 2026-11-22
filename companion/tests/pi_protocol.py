"""Field-by-field check of companion messages against cyd/PROTOKOLL.md (and the original
Desk Hub fields for events, github and net). Used by test_pi_app.py and fake_cyd_hub.py.

validate(msg) -> list of problems, empty when the message is fine.
"""
import numbers

PAGES = {"home", "claude", "calendar", "weather", "timer", "github", "homelab", "net"}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def exact(msg, required, optional=()):
    got, allowed = set(msg), set(required) | set(optional) | {"type"}
    return ([f"missing {sorted(set(required) - got)}"] if set(required) - got else []) + \
           ([f"unknown {sorted(got - allowed)}"] if got - allowed else [])


def v_hello(m):
    return exact(m, ["token"]) + ([] if isinstance(m.get("token"), str) else ["token not a string"])


def v_time(m):
    return exact(m, ["unix"]) + ([] if is_num(m.get("unix")) and m["unix"] > 1e9 else ["unix not unix seconds"])


def v_layout(m):
    p = m.get("pages")
    out = exact(m, ["pages"])
    if not isinstance(p, list) or not all(isinstance(x, str) for x in p):
        return out + ["pages not a list of strings"]
    return out + ([] if "home" in p else ["home missing"]) + \
        ([f"unknown pages {sorted(set(p) - PAGES)}"] if set(p) - PAGES else []) + \
        (["duplicate pages"] if len(set(p)) != len(p) else [])


def v_events(m):
    out = exact(m, ["events", "days"])
    if not is_int(m.get("days")):
        out.append("days not int")
    ev = m.get("events")
    if not isinstance(ev, list) or len(ev) > 16:
        return out + ["events not a list of at most 16"]
    for i, e in enumerate(ev):
        o = exact(e, ["start", "end", "all_day", "title", "loc", "cal", "color"])
        o += [f"{k} not int" for k in ("start", "end") if not is_int(e.get(k))]
        o += [f"{k} not str" for k in ("title", "loc", "cal", "color") if not isinstance(e.get(k), str)]
        if not isinstance(e.get("all_day"), bool):
            o.append("all_day not bool")
        if isinstance(e.get("title"), str) and (len(e["title"].encode()) > 79 or not e["title"].isascii()):
            o.append("title too long or not ASCII")
        if isinstance(e.get("loc"), str) and (len(e["loc"].encode()) > 63 or not e["loc"].isascii()):
            o.append("loc too long or not ASCII")
        if is_int(e.get("start")) and is_int(e.get("end")) and e["end"] <= e["start"]:
            o.append("end <= start")
        out += [f"event {i}: {x}" for x in o]
    return out


def _window(w, name):
    if not isinstance(w, dict):
        return [f"{name} not an object"]
    o = exact(w, ["pct", "reset"])
    if not is_num(w.get("pct")) or not 0 <= w["pct"] <= 100:
        o.append(f"{name}.pct not 0..100")
    if not is_int(w.get("reset")) or w["reset"] < 1e9:
        o.append(f"{name}.reset not unix seconds")
    return o


def v_ai(m):
    out = exact(m, ["provider", "limits"], ["history"])
    if m.get("provider") != "claude":
        out.append("provider not claude")
    lim = m.get("limits")
    if not isinstance(lim, dict):
        return out + ["limits not an object"]
    out += exact(lim, ["updated"], ["five_hour", "seven_day"])
    if not is_int(lim.get("updated")):
        out.append("limits.updated not int")
    if not ({"five_hour", "seven_day"} & set(lim)):
        out.append("limits without any window")
    for k in ("five_hour", "seven_day"):
        if k in lim:
            out += _window(lim[k], k)
    h = m.get("history")
    if h is not None:
        if not isinstance(h, list) or len(h) > 48:
            out.append("history not a list of at most 48")
        elif not all(isinstance(p, list) and len(p) == 2 and is_int(p[0]) and is_num(p[1]) for p in h):
            out.append("history entries not [unix, pct]")
    return out


def v_github(m):
    req = ["login", "total", "levels", "start_wday", "months", "today", "week", "last_week", "streak", "longest",
           "best", "best_date", "week_days", "last_week_days", "kinds", "repos", "accent"]
    out = exact(m, req)
    if not isinstance(m.get("login"), str):
        out.append("login not str")
    out += [f"{k} not int" for k in ("total", "start_wday", "today", "week", "last_week", "streak", "longest", "best")
            if not is_int(m.get(k))]
    lv = m.get("levels")
    if not isinstance(lv, str) or not lv or set(lv) - set("01234"):
        out.append("levels not a digit string 0-4")
    if is_int(m.get("start_wday")) and not 0 <= m["start_wday"] <= 6:
        out.append("start_wday not 0..6")
    for k in ("months", "week_days", "last_week_days", "repos"):
        if not isinstance(m.get(k), list):
            out.append(f"{k} not list")
    if not all(isinstance(x, list) and len(x) == 2 for x in m.get("months", [])):
        out.append("months entries not [col, name]")
    if not isinstance(m.get("kinds"), dict):
        out.append("kinds not object")
    if not isinstance(m.get("accent"), bool):
        out.append("accent not bool")
    if isinstance(lv, str) and is_int(m.get("start_wday")) and isinstance(m.get("week_days"), list):
        if len(m["week_days"]) > 7 or len(m["week_days"]) < 1:
            out.append("week_days length")
    return out


def v_net(m):
    req = ["online", "latency_ms", "jitter_ms", "loss_pct", "hist", "up_since", "last_drop", "today_bytes",
           "month_bytes", "speed", "testing", "ip"]
    out = exact(m, req)
    if not isinstance(m.get("online"), bool):
        out.append("online not bool")
    for k in ("latency_ms", "jitter_ms"):
        if m.get(k) is not None and not is_num(m[k]):
            out.append(f"{k} not number or null")
    if not is_int(m.get("loss_pct")) or not 0 <= m["loss_pct"] <= 100:
        out.append("loss_pct not 0..100")
    if not isinstance(m.get("hist"), list) or not all(is_int(x) for x in m["hist"]) or len(m["hist"]) > 60:
        out.append("hist not a list of at most 60 ints")
    if not is_int(m.get("today_bytes")) or not is_int(m.get("month_bytes")):
        out.append("bytes not int")
    if m.get("speed") is not None:
        out.append("speed must be null on the Pi")
    if m.get("testing") is not False:
        out.append("testing must be false on the Pi")
    return out


def v_weather(m):
    out = exact(m, ["place", "updated", "now", "hours", "days"])
    if not isinstance(m.get("place"), str):
        out.append("place not str")
    if not is_int(m.get("updated")):
        out.append("updated not int")
    n = m.get("now")
    if not isinstance(n, dict):
        return out + ["now not object"]
    out += [f"now: {x}" for x in exact(n, ["temp", "feels", "code", "is_day", "humidity", "wind"])]
    out += [f"now.{k} not number" for k in ("temp", "feels", "humidity", "wind") if not is_num(n.get(k))]
    if not is_int(n.get("code")):
        out.append("now.code not int")
    if not isinstance(n.get("is_day"), bool):
        out.append("now.is_day not bool")
    for key, limit, req in (("hours", 12, ["t", "temp", "code", "precip"]),
                            ("days", 6, ["t", "min", "max", "code", "precip"])):
        lst = m.get(key)
        if not isinstance(lst, list) or not lst or len(lst) > limit:
            out.append(f"{key} not a list of 1..{limit}")
            continue
        for i, e in enumerate(lst):
            out += [f"{key}[{i}]: {x}" for x in exact(e, req)]
            out += [f"{key}[{i}].{k} not number" for k in req if k != "code" and not is_num(e.get(k))]
            if not is_int(e.get("code")) or not is_int(e.get("t")):
                out.append(f"{key}[{i}] code/t not int")
            if is_num(e.get("precip")) and not 0 <= e["precip"] <= 100:
                out.append(f"{key}[{i}].precip not 0..100")
    return out


def v_homelab(m):
    out = exact(m, ["ok", "updated", "up", "total", "down"])
    if not isinstance(m.get("ok"), bool):
        out.append("ok not bool")
    out += [f"{k} not int" for k in ("updated", "up", "total") if not is_int(m.get(k))]
    d = m.get("down")
    if not isinstance(d, list) or len(d) > 8:
        return out + ["down not a list of at most 8"]
    for e in d:
        out += exact(e, ["name", "since"])
        if not isinstance(e.get("name"), str) or not is_int(e.get("since")):
            out.append("down entry types")
    return out


VALIDATORS = {"hello": v_hello, "time": v_time, "layout": v_layout, "events": v_events, "ai": v_ai,
              "github": v_github, "net": v_net, "weather": v_weather, "homelab": v_homelab}


def validate(msg) -> list[str]:
    if not isinstance(msg, dict) or "type" not in msg:
        return ["not an object with type"]
    v = VALIDATORS.get(msg["type"])
    return [f"{msg['type']}: {p}" for p in v(msg)] if v else [f"unknown message type {msg['type']!r}"]
