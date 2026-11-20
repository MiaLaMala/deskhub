"""GitHub contribution chart with a fake API: the board message (levels, month labels,
week sums, streak), polling and back-off, the Home widget sizes, and the setup step
(fake credential store). Never contacts GitHub.

    uv run python tests/test_github.py
"""
import builtins
import datetime as dt
import getpass
import pathlib
import sys
import tempfile

from deskhub import github as gh, setup_cli
from deskhub.pages import home_grid, widget_sizes

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


# A year of days from Sunday 2025-11-16 to Thursday 2026-11-19 (GitHub's weeks start on Sunday).
start = dt.date(2025, 11, 16)
end = dt.date(2026, 11, 19)
names = list(gh.LEVELS)
days = []
d = start
while d <= end:
    i = (d - start).days
    count = 0 if i % 5 == 0 else i % 4
    days.append({"date": d.isoformat(), "weekday": (d.weekday() + 1) % 7, "contributionCount": count,
                 "contributionLevel": names[min(count, 4)]})
    d += dt.timedelta(days=1)
# The last days: 0 yesterday... no, a run of 3 ending today.
for k, c in ((-4, 0), (-3, 2), (-2, 1), (-1, 5)):
    days[k]["contributionCount"] = c
    days[k]["contributionLevel"] = names[min(c, 4)]
weeks = [{"contributionDays": days[i:i + 7]} for i in range(0, len(days), 7)]
total = sum(x["contributionCount"] for x in days)
posts = []


def fake_post(token, query, variables=None):
    posts.append(token)
    if token == "bad":
        raise RuntimeError("Bad credentials")
    if query == gh.PRIVATE_QUERY:
        assert variables["id"] == "U_1" and variables["since"].endswith("Z"), variables
        return {"viewer": {"repositories": {"nodes": [
            {"name": "secret-game", "defaultBranchRef": {"target": {"history": {"totalCount": 120}}}},
            {"name": "empty", "defaultBranchRef": None},
            {"name": "quiet", "defaultBranchRef": {"target": {"history": {"totalCount": 0}}}}]}}}
    return {"viewer": {"id": "U_1", "login": "octo", "contributionsCollection": {
        "totalCommitContributions": 300, "totalPullRequestContributions": 40,
        "totalPullRequestReviewContributions": 12, "totalIssueContributions": None,
        "restrictedContributionsCount": 7,
        "commitContributionsByRepository": [
            {"repository": {"name": n}, "contributions": {"totalCount": c}}
            for n, c in (("small", 3), ("deskhub", 200), ("Café", 50), ("dots", 20), ("old", 10))],
        "contributionCalendar": {"totalContributions": total, "weeks": weeks}}}}


cal = gh.fetch("t", fake_post)
check(cal["login"] == "octo" and len(cal["days"]) == len(days), "fetch flattens the weeks")
m = gh.message(cal)
check(m["type"] == "github" and m["total"] == total, "type and total")
check(len(m["levels"]) == len(days) and set(m["levels"]) <= set("01234"), "one level digit per day")
check(m["levels"][-1] == "4" and m["today"] == 5, f"today last: {m['levels'][-1]} {m['today']}")
check(m["start_wday"] == 0, "starts on a Sunday")
check(m["streak"] == 3, f"streak of 3 ending today: {m['streak']}")
# Thursday: this week is Sun..Thu, the last 5 days.
check(m["week"] == sum(x["contributionCount"] for x in days[-5:]), f"this week: {m['week']}")
check(m["last_week"] == sum(x["contributionCount"] for x in days[-12:-5]), f"last week: {m['last_week']}")
check(m["best"] == max(x["contributionCount"] for x in days), "best day")
labels = [name for _, name in m["months"]]
check(labels[0] == "Dec" and labels[-1] == "Nov" and len(labels) == 12, f"month labels: {labels}")
check(all(days[c * 7]["date"][8:] <= "07" for c, _ in m["months"]), "labels on each month's first full week")
check(gh.message(cal, accent=True)["accent"] is True, "accent colours option")

# For the GitHub page.
check(m["kinds"] == {"commits": 300, "prs": 40, "reviews": 12, "issues": 0, "private": 7}, f"kinds: {m['kinds']}")
check(m["repos"] == [{"name": "deskhub", "count": 200}, {"name": "secret-game", "count": 120},
                     {"name": "Cafe", "count": 50}, {"name": "dots", "count": 20}],
      f"top 4 repos, private ones counted from their history: {m['repos']}")
check(m["week_days"] == [x["contributionCount"] for x in days[-5:]], f"this week by day: {m['week_days']}")
check(len(m["last_week_days"]) == 7 and sum(m["last_week_days"]) == m["last_week"], "last week by day")
best_i = max(range(len(days)), key=lambda i: days[i]["contributionCount"])
b = dt.date.fromisoformat(days[best_i]["date"])
check(m["best_date"] == f"{gh.MONTHS[b.month - 1]} {b.day}", f"best day date: {m['best_date']}")
check(gh.longest_streak([1, 1, 0, 1, 1, 1, 0]) == 3 and gh.longest_streak([]) == 0, "longest streak")
check(m["longest"] >= m["streak"], "longest streak is at least the current one")

check(gh.streak([1, 1, 0]) == 2, "empty today keeps yesterday's streak")
check(gh.streak([1, 0, 0]) == 0, "two empty days end it")
check(gh.streak([]) == 0, "no days")

now = [0.0]
g = gh.GitHub("t", post=fake_post, clock=lambda: now[0])
check(g.poll() is not None, "first poll sends")
posts.clear()
check(g.poll() is None and posts == [], "no request before 15 minutes")
now[0] += gh.POLL_S
check(g.poll() is None and posts == ["t", "t"], "asks again (calendar, then private repos); unchanged, so nothing to send")
bad = gh.GitHub("bad", post=fake_post, clock=lambda: now[0])
check(bad.poll() is None, "a failure sends nothing")
posts.clear()
now[0] += 60
bad.poll()
check(posts == [], "backs off after a failure")

check(widget_sizes("github") == ["2x1", "3x1", "4x1", "5x1", "2x2", "3x2", "4x2", "5x2"], "widget sizes")
check(home_grid({"home": {"grid": [{"widget": "github", "x": 0, "y": 2, "w": 5, "h": 1}]}})
      == [{"widget": "github", "x": 0, "y": 2, "w": 5, "h": 1}], "a 5x1 chart fits the bottom row")

# Setup: token checked with GitHub, saved, and the widget placed on Home.
store = {}
gh.get_token = lambda: store.get("t", "")
gh.set_token = lambda t: store.update(t=t) if t else store.pop("t", None)
real_fetch = gh.fetch
gh.fetch = lambda token, post=None: real_fetch(token, fake_post)


def run(answers, secret=""):
    it = iter(answers)
    builtins.input = lambda prompt="": next(it)
    getpass.getpass = lambda prompt="": secret
    setup_cli.step_github(cfg)


with tempfile.TemporaryDirectory() as tmp:
    cfg = pathlib.Path(tmp) / "config.toml"
    cfg.write_text('[home]\ngrid = [{ widget = "weather", x = 0, y = 0, w = 2, h = 1 }]\n', encoding="utf-8")
    run(["y"], "bad")
    check(store == {}, "token GitHub refuses isn't saved")
    run(["y", "y"], "ghp_good")
    check(store == {"t": "ghp_good"}, "token saved")
    placed = [x for x in home_grid(__import__("tomllib").loads(cfg.read_text(encoding="utf-8")))
              if x["widget"] == "github"]
    check(placed == [{"widget": "github", "x": 0, "y": 1, "w": 5, "h": 1}], f"placed 5x1 on the first free row: {placed}")
    run([""])
    check(store == {"t": "ghp_good"}, "Enter keeps the saved token")
    run(["n"])
    check(store == {}, "token can be removed")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
