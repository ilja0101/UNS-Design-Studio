"""Shift-hours scheduling for the simulated plants.

Pure, dependency-light logic (only stdlib + optional ``tzdata`` for named zones)
so it stays unit-testable without a running app. ``app.py`` owns persistence and
the background loop that actually clocks the plants in and out; everything here
is side-effect free and works on plain dicts and datetimes.

A shift config is::

    {"enabled": bool, "start": "HH:MM", "end": "HH:MM",
     "days": "Mon-Fri", "tz": "Europe/Amsterdam"}

``start > end`` means an overnight shift (e.g. 22:00->06:00). ``days`` accepts
ranges and lists ("Mon-Fri", "Mon-Fri,Sat") or "daily".
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

DAYNAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULTS = {
    "enabled": False,
    "start": "06:00",
    "end": "22:00",
    "days": "Mon-Fri",
    "tz": "Europe/Amsterdam",
}


# ─────────────────────────── parsing / validation ───────────────────────────
def parse_hhmm(s: str, default: str = "06:00") -> int:
    """"HH:MM" -> minutes since midnight; falls back to *default* on garbage."""
    try:
        h, m = str(s).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except Exception:
        pass
    dh, dm = default.split(":")
    return int(dh) * 60 + int(dm)


def clean_hhmm(s: str, default: str = "06:00") -> str:
    m = parse_hhmm(s, default)
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_days(spec: str) -> list[int]:
    """"Mon-Fri" / "Sat,Sun" / "Mon-Fri,Sat" / "daily" -> sorted [0..6] (Mon=0)."""
    spec = (spec or "Mon-Fri").strip().lower()
    if spec in ("daily", "all", "everyday", "7", "*"):
        return list(range(7))
    days: set[int] = set()
    for tok in spec.replace(" ", "").split(","):
        if not tok:
            continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            try:
                ia, ib = DAYNAMES.index(a[:3]), DAYNAMES.index(b[:3])
            except ValueError:
                continue
            i = ia
            while True:                      # inclusive, wrapping (e.g. Sat-Mon)
                days.add(i)
                if i == ib:
                    break
                i = (i + 1) % 7
        elif tok[:3] in DAYNAMES:
            days.add(DAYNAMES.index(tok[:3]))
    return sorted(days) or list(range(5))


def days_label(days: list[int]) -> str:
    return ",".join(DAYNAMES[d][:3].title() for d in sorted(days))


def resolve_tz(name: str) -> tuple[tzinfo, str]:
    """(tzinfo, resolved_name). Falls back to UTC if the named zone / tzdata is
    unavailable — never raises, so a missing tz database can't break the app."""
    if ZoneInfo is not None and name:
        try:
            tz = ZoneInfo(name)
            datetime.now(tz)                 # force a load so we fail here
            return tz, name
        except Exception:
            pass
    if ZoneInfo is not None:
        try:
            return ZoneInfo("UTC"), "UTC"
        except Exception:
            pass
    return timezone.utc, "UTC"


def normalize(raw: dict | None) -> dict:
    """Coerce an arbitrary dict into a valid, complete shift config."""
    raw = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULTS)
    cfg["enabled"] = bool(raw.get("enabled", DEFAULTS["enabled"]))
    cfg["start"] = clean_hhmm(raw.get("start", DEFAULTS["start"]), DEFAULTS["start"])
    cfg["end"] = clean_hhmm(raw.get("end", DEFAULTS["end"]), DEFAULTS["end"])
    cfg["days"] = days_label(parse_days(raw.get("days", DEFAULTS["days"])))
    # Store the requested tz name as-is; the loop resolves it to a real tzinfo
    # (with a UTC fallback) at read time, so an unavailable zone never blocks a save.
    cfg["tz"] = str(raw.get("tz", DEFAULTS["tz"]) or DEFAULTS["tz"]).strip()
    return cfg


def seed_from_env(env=os.environ) -> dict:
    """Initial config from UDS_SHIFT_* env, used on first boot only."""
    enabled = str(env.get("UDS_SHIFT_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")
    return normalize({
        "enabled": enabled,
        "start": env.get("UDS_SHIFT_START", DEFAULTS["start"]),
        "end": env.get("UDS_SHIFT_END", DEFAULTS["end"]),
        "days": env.get("UDS_SHIFT_DAYS", DEFAULTS["days"]),
        "tz": env.get("UDS_SHIFT_TZ", DEFAULTS["tz"]),
    })


# ─────────────────────────── the decision ───────────────────────────
def shift_open(now: datetime, start_min: int, end_min: int, days: list[int]) -> bool:
    """Are the plants supposed to be running at *now*?"""
    days = set(days)
    tod = now.hour * 60 + now.minute
    today = now.weekday()
    if start_min == end_min:
        return today in days                         # 24h on working days
    if start_min < end_min:
        return today in days and start_min <= tod < end_min
    # overnight (e.g. 22:00->06:00): after start on a work day, or before end the
    # morning after a work day.
    yesterday = (today - 1) % 7
    return (today in days and tod >= start_min) or (yesterday in days and tod < end_min)


def next_transition(now: datetime, start_min: int, end_min: int, days: list[int]) -> str | None:
    """ISO time of the next open/closed flip, or None if it never changes."""
    days = list(days)
    if not days or (len(set(days)) == 7 and start_min == end_min):
        return None
    here = shift_open(now, start_min, end_min, days)
    probe = now
    step = timedelta(minutes=5)
    for _ in range(8 * 24 * 12):                     # up to 8 days ahead
        probe = probe + step
        if shift_open(probe, start_min, end_min, days) != here:
            return probe.replace(second=0, microsecond=0).isoformat()
    return None


def compute_status(cfg: dict, now: datetime, running: int, total: int) -> dict:
    """Assemble the /api/shift status payload the UI badge renders."""
    cfg = normalize(cfg)
    start_min = parse_hhmm(cfg["start"])
    end_min = parse_hhmm(cfg["end"])
    days = parse_days(cfg["days"])
    if not cfg["enabled"]:
        state = "off"
    elif shift_open(now, start_min, end_min, days):
        state = "open"
    elif now.weekday() not in days:
        state = "dayoff"
    else:
        state = "closed"
    return {
        "enabled": cfg["enabled"],
        "state": state,                              # off | open | closed | dayoff
        "schedule": f'{cfg["start"]}–{cfg["end"]}',
        "start": cfg["start"],
        "end": cfg["end"],
        "days": cfg["days"],
        "tz": cfg["tz"],
        "running": running,
        "total": total,
        "next_change": next_transition(now, start_min, end_min, days) if cfg["enabled"] else None,
        "updated": now.isoformat(),
    }
