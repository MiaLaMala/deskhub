"""GitHub contribution chart: the green squares from your profile, for the Home widget.

Opt-in: it needs a fine-grained personal access token (no extra permissions) from
https://github.com/settings/personal-access-tokens, kept in the Windows credential
store (service "deskhub-github"), never in config.toml. Queried as yourself, so
private work counts too when "Private contributions" is on in your profile.
Requests go only to api.github.com.
"""
import datetime as dt
import logging
import time

from .text import ascii_fold

log = logging.getLogger(__name__)

API = "https://api.github.com/graphql"
KEYRING_SERVICE = "deskhub-github"
KEYRING_USER = "token"
POLL_S = 15 * 60
BACKOFF_S = 10 * 60
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
QUERY = """query { viewer { id login contributionsCollection {
  totalCommitContributions totalPullRequestContributions totalPullRequestReviewContributions
  totalIssueContributions restrictedContributionsCount
  commitContributionsByRepository(maxRepositories: 5) { repository { name } contributions { totalCount } }
  contributionCalendar {
  totalContributions weeks { contributionDays { date weekday contributionCount contributionLevel } } } } } }"""
MAX_REPOS = 4
# GitHub leaves private repositories out of commitContributionsByRepository for a
# fine-grained token (it only gives restrictedContributionsCount), even when the token
# can read them. So count your commits on each private repository's default branch.
PRIVATE_QUERY = """query($id: ID!, $since: GitTimestamp!) { viewer { repositories(first: 50, privacy: PRIVATE,
  ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], orderBy: {field: PUSHED_AT, direction: DESC}) {
  nodes { name pushedAt defaultBranchRef { target { ... on Commit {
    history(since: $since, author: {id: $id}) { totalCount } } } } } } } }"""
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def get_token() -> str:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception as e:  # no keyring backend
        log.debug("github token: %s", e)
        return ""


def set_token(token: str | None):
    import keyring

    if token:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except keyring.errors.PasswordDeleteError:
            pass


def _http_post(token: str, query: str, variables: dict | None = None) -> dict:
    import httpx

    r = httpx.post(API, json={"query": query, "variables": variables or {}}, timeout=30,
                   headers={"Authorization": f"Bearer {token}", "User-Agent": "deskhub"})
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message", "GraphQL error"))
    return data["data"]


def fetch(token: str, post=_http_post) -> dict:
    """The viewer's login and contribution calendar, straight from GitHub."""
    v = post(token, QUERY)["viewer"]
    cc = v["contributionsCollection"]
    cal = cc["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    kinds = {"commits": cc.get("totalCommitContributions", 0), "prs": cc.get("totalPullRequestContributions", 0),
             "reviews": cc.get("totalPullRequestReviewContributions", 0),
             "issues": cc.get("totalIssueContributions", 0), "private": cc.get("restrictedContributionsCount", 0)}
    repos = [{"name": ascii_fold(r["repository"]["name"], 32), "count": int(r["contributions"]["totalCount"])}
             for r in cc.get("commitContributionsByRepository") or []]
    if kinds["private"]:
        try:
            repos += private_repos(token, v["id"], post)
        except Exception as e:  # the token can't read them: the public ones still show
            log.debug("github private repos: %s", e)
    repos.sort(key=lambda r: -r["count"])
    return {"login": v["login"], "total": int(cal["totalContributions"]), "days": days,
            "kinds": {k: int(n or 0) for k, n in kinds.items()}, "repos": repos[:MAX_REPOS]}


def private_repos(token: str, viewer_id: str, post=_http_post) -> list[dict]:
    """Your commits in the last year on each private repository the token can read."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    nodes = post(token, PRIVATE_QUERY, {"id": viewer_id, "since": since})["viewer"]["repositories"]["nodes"]
    out = []
    for n in nodes or []:
        history = ((n.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}
        count = int(history.get("totalCount") or 0)
        if count:
            out.append({"name": ascii_fold(n["name"], 32), "count": count})
    return out


def streak(counts: list[int]) -> int:
    """Days in a row with contributions, up to today, or up to yesterday while today is empty."""
    n = len(counts)
    end = n - 1 if counts and counts[-1] else n - 2
    run = 0
    while end - run >= 0 and counts[end - run] > 0:
        run += 1
    return run


def longest_streak(counts: list[int]) -> int:
    best = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        best = max(best, run)
    return best


def message(cal: dict, accent: bool = False) -> dict:
    """The board message: one digit per day for the level (oldest first, today last),
    the weekday of the first day (0 = Sunday), month labels by week column, and totals."""
    days = cal["days"]
    counts = [int(d["contributionCount"]) for d in days]
    levels = "".join(str(LEVELS.get(d["contributionLevel"], 0)) for d in days)
    start_wday = int(days[0]["weekday"]) if days else 0
    months = []
    for i, d in enumerate(days):
        date = dt.date.fromisoformat(d["date"])
        col = (i + start_wday) // 7
        # A label goes on the first full week of each month, like GitHub's chart.
        if date.day <= 7 and (i + start_wday) % 7 == 0:
            months.append([col, MONTHS[date.month - 1]])
    today_wday = (len(days) - 1 + start_wday) % 7
    week = sum(counts[len(counts) - 1 - today_wday:]) if counts else 0
    last_week = sum(counts[max(0, len(counts) - 8 - today_wday):len(counts) - 1 - today_wday])
    best = max(range(len(days)), key=lambda i: counts[i]) if days else -1
    best_date = ""
    if best >= 0 and counts[best] > 0:
        b = dt.date.fromisoformat(days[best]["date"])
        best_date = f"{MONTHS[b.month - 1]} {b.day}"
    # This week Sunday to today, and all of last week, a count per day.
    week_days = counts[len(counts) - 1 - today_wday:] if counts else []
    last_week_days = counts[max(0, len(counts) - 8 - today_wday):len(counts) - 1 - today_wday]
    return {"type": "github", "login": cal["login"], "total": cal["total"], "levels": levels,
            "start_wday": start_wday, "months": months, "today": counts[-1] if counts else 0,
            "week": week, "last_week": last_week, "streak": streak(counts),
            "longest": longest_streak(counts), "best": counts[best] if best >= 0 else 0,
            "best_date": best_date, "week_days": week_days, "last_week_days": last_week_days,
            "kinds": cal.get("kinds", {}), "repos": cal.get("repos", []), "accent": accent}


class GitHub:
    def __init__(self, token: str, accent: bool = False, post=_http_post, clock=time.time):
        self.token = token
        self.accent = accent
        self._post = post
        self._clock = clock
        self._next = 0.0
        self.msg: dict | None = None

    def poll(self) -> dict | None:
        """A new message when it's time to ask GitHub again and something changed, else None."""
        now = self._clock()
        if now < self._next:
            return None
        try:
            msg = message(fetch(self.token, self._post), self.accent)
        except Exception as e:  # bad token (401), network, rate limit
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("GitHub contributions failed: %s; trying again in 10 minutes", status or e)
            self._next = now + BACKOFF_S
            return None
        self._next = now + POLL_S
        if msg == self.msg:
            return None
        self.msg = msg
        log.info("GitHub: %d contributions in the last year, %d today", msg["total"], msg["today"])
        return msg
