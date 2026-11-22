#!/usr/bin/env python3
"""Erzeugt die erfundenen Beispielnachrichten fuer Vorschau und Test.

Alle Zeiten haengen an NOW (Dienstag, 24.11.2026, 09:41 MEZ). Aufruf:
python3 make_samples.py  ->  samples/*.json
"""
import json
import os
import random

NOW = 1795509660                 # Di 24.11.2026 09:41 MEZ
MIDNIGHT = 1795474800            # Di 24.11.2026 00:00 MEZ
H = 3600
DAY = 86400

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(out, exist_ok=True)


def write(name, obj):
    with open(os.path.join(out, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def at(day, hour, minute=0):
    return MIDNIGHT + day * DAY + hour * H + minute * 60


write("hello", {"type": "hello", "token": "beispiel-token"})
write("layout", {"type": "layout",
                 "pages": ["home", "claude", "calendar", "weather", "timer", "github", "homelab", "net"]})
write("time", {"type": "time", "unix": NOW + 0.25})

write("events", {"type": "events", "days": 7, "events": [
    {"start": at(0, 0), "end": at(1, 0), "all_day": True, "title": "Müllabfuhr", "loc": "", "cal": "Haus", "color": "#b49cff"},
    {"start": at(0, 10, 30), "end": at(0, 11, 15), "all_day": False, "title": "Teambesprechung", "loc": "Raum 2", "cal": "Arbeit", "color": "#6cb4ff"},
    {"start": at(0, 13, 0), "end": at(0, 16, 30), "all_day": False, "title": "Lernzeit Netzwerktechnik", "loc": "Bibliothek", "cal": "Schule", "color": "#3dd68c"},
    {"start": at(1, 8, 0), "end": at(1, 9, 0), "all_day": False, "title": "Zahnarzt, Kontrolle", "loc": "Praxis Süd", "cal": "Privat", "color": "#ffb224"},
    {"start": at(1, 17, 30), "end": at(1, 19, 0), "all_day": False, "title": "Sport", "loc": "Halle Süd", "cal": "Privat", "color": "#ffb224"},
    {"start": at(2, 12, 0), "end": at(2, 13, 0), "all_day": False, "title": "Mittagessen", "loc": "Kantine", "cal": "Arbeit", "color": "#6cb4ff"},
    {"start": at(3, 0), "end": at(4, 0), "all_day": True, "title": "Brückentag", "loc": "", "cal": "Haus", "color": "#b49cff"},
    {"start": at(4, 15, 0), "end": at(4, 16, 0), "all_day": False,
     "title": "Ein sehr langer Termintitel, der ganz sicher nicht in eine Zeile passt", "loc": "Überall und nirgends, Raum 404", "cal": "Arbeit", "color": "#ff6b6b"},
]})

random.seed(7)
hist = []
pct = 4.0
for i in range(48):
    t = NOW - (47 - i) * 3 * H - 30 * 60
    pct += random.uniform(0.0, 2.4)
    hist.append([t, round(min(pct, 100), 1)])
hist[-1][1] = 61.0
write("ai", {"type": "ai", "provider": "claude",
             "limits": {"updated": NOW - 120,
                        "five_hour": {"pct": 42.4, "reset": NOW + 2 * H + 14 * 60},
                        "seven_day": {"pct": 61.0, "reset": at(2, 14, 0)}},
             "history": hist})

# GitHub: 371 Tage bis heute (Dienstag), erster Tag also ein Mittwoch.
days = 371
levels = "".join(random.choice("0000111223344") for _ in range(days - 1)) + "3"
start_wday = (2 - (days - 1)) % 7
months = []
import datetime as dt
first = dt.date(2026, 11, 24) - dt.timedelta(days=days - 1)
names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
for i in range(days):
    d = first + dt.timedelta(days=i)
    if d.day == 1:
        months.append([(start_wday + i) // 7, names[d.month - 1]])
write("github", {"type": "github", "login": "beispiel", "levels": levels, "start_wday": start_wday,
                 "months": months, "total": 1019, "today": 3, "week": 10, "last_week": 17,
                 "streak": 12, "best": 19, "longest": 41, "best_date": "Mar 14",
                 "week_days": [2, 5, 3], "last_week_days": [0, 4, 2, 3, 1, 5, 2],
                 "kinds": {"commits": 812, "prs": 64, "reviews": 31, "issues": 22, "private": 90},
                 "repos": [{"name": "deskhub", "count": 210}, {"name": "dotfiles", "count": 95}]})

lat = [round(random.uniform(11, 19), 1) for _ in range(60)]
lat[17] = None
lat[18] = None
lat[44] = 142
write("net", {"type": "net", "online": True, "latency_ms": 14.2, "jitter_ms": 2.1, "loss_pct": 0,
              "hist": lat, "up_since": NOW - 3 * H - 20 * 60,
              "last_drop": {"at": at(-1, 22, 14), "dur_s": 184},
              "today_bytes": 1.2e9, "month_bytes": 4.1e10, "ip": "192.0.2.1"})

write("weather", {"type": "weather", "place": "Hamburg", "updated": NOW - 600,
                  "now": {"temp": 7.2, "feels": 4.1, "code": 3, "is_day": True, "humidity": 81, "wind": 18},
                  "hours": [{"t": at(0, 10 + i), "temp": round(7.0 + i * 0.3 - (i > 6) * (i - 6) * 0.6, 1),
                             "code": [3, 3, 61, 61, 63, 3, 2, 2, 1, 0, 0, 0][i],
                             "precip": [10, 20, 60, 70, 80, 40, 20, 10, 0, 0, 0, 0][i]} for i in range(12)],
                  "days": [{"t": at(i, 0), "min": [3.0, 2.0, -1.0, -3.0, 0.0, 4.0][i],
                            "max": [8.0, 7.0, 4.0, 2.0, 6.0, 10.0][i],
                            "code": [61, 3, 71, 0, 2, 80][i], "precip": [70, 20, 50, 0, 10, 60][i]} for i in range(6)]})

write("homelab", {"type": "homelab", "ok": True, "updated": NOW - 30, "up": 51, "total": 54, "down": [
    {"name": "Nextcloud", "since": NOW - 2 * H - 5 * 60},
    {"name": "Gäste-WLAN Portal", "since": at(-1, 21, 40)},
    {"name": "Paperless-ngx Dokumentenarchiv mit langem Namen", "since": at(-5, 8, 0)},
]})
# Quelle nicht erreichbar: letzter Stand von vor 40 Minuten.
write("homelab_alt", {"type": "homelab", "ok": False, "updated": NOW - 40 * 60, "up": 53, "total": 54,
                      "down": [{"name": "Nextcloud", "since": NOW - 2 * H - 5 * 60}]})
