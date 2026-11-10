import argparse
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


# Installed at ROOT/profiles/PROFILE/scripts/travel-scout.py.
HERMES_ROOT = Path(__file__).resolve().parents[3]
SCAN_AGE = timedelta(hours=12)
PREF_KEYS = (
    "departAfter", "departBefore", "checkedBag", "bagFeeEstimate", "minStars",
    "minRating", "maxPerPerson", "oneTicketPremium", "nonSmoking", "hotelCheckIn",
    "hotelCheckOut",
)


def read_object(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def scanner_settings(data_dir):
    saved = read_object(data_dir / "settings.json")
    settings = {}
    travelers = saved.get("travelers")
    if type(travelers) is int and travelers > 0:
        settings["travelers"] = travelers
    prefs = saved.get("prefs")
    if isinstance(prefs, dict):
        settings["prefs"] = {
            key: prefs[key] for key in PREF_KEYS
            if key in prefs and type(prefs[key]) in (str, int, float, bool, type(None))
            and (type(prefs[key]) is not float or math.isfinite(prefs[key]))
        }
        if "maxPerPerson" in settings["prefs"]:
            settings["maxPerPerson_scope"] = "flight_and_stay_per_person"
    return settings


def missing_prerequisites(root):
    prefs = read_object(root / "shared/travel-workflow/preferences.json")
    calendar = read_object(root / "shared/annual-schedule/calendar.json")
    budget = prefs.get("budget")
    amount = budget.get("amount") if isinstance(budget, dict) else None
    missing = []
    if (type(amount) not in (int, float) or amount <= 0
            or (type(amount) is float and not math.isfinite(amount))
            or budget.get("scope") != "entire_trip"
            or not isinstance(budget.get("currency"), str)
            or not re.fullmatch(r"[A-Z]{3}", budget["currency"])):
        missing.append("budget")
    coverage = calendar.get("coverage")
    status = coverage.get("status") if isinstance(coverage, dict) else None
    try:
        start = date.fromisoformat(coverage["start"])
        end = date.fromisoformat(coverage["end"])
        checked = datetime.fromisoformat(coverage["checked_at"])
        today = datetime.now(timezone(timedelta(hours=8))).date()
        covered = (status == "verified" and start <= end and end >= today
                   and start.isoformat() == coverage["start"]
                   and end.isoformat() == coverage["end"]
                   and checked.tzinfo is not None)
    except (KeyError, TypeError, ValueError):
        covered = False
    if not covered:
        missing.append("calendar_coverage")
    return missing


def utc_millis(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def snapshot(db, cutoff, current, today, data_dir):
    watches = [dict(row) for row in db.execute("""
        SELECT id, origin, originLabel, regionLabel, tripLength, currency, lastScanAt
        FROM watches WHERE active = 1 ORDER BY id LIMIT 25
    """)]
    for watch in watches[:24]:
        scan = watch["lastScanAt"]
        watch["observations"] = []
        if scan and cutoff <= scan <= current:
            watch["observations"] = [dict(row) for row in db.execute("""
                SELECT city, outboundDate, returnDate, stops, duration, price, currency, scannedAt
                FROM observations WHERE watchId = ? AND scannedAt = ? AND outboundDate > ?
                ORDER BY price, id LIMIT 3
            """, (watch["id"], scan, today))]
    return {
        "status": "ok" if watches else "empty",
        "source": "trip_agent_flight_observations",
        "scanner_settings": scanner_settings(data_dir),
        "active_watches": watches[:24],
        "active_watches_truncated": len(watches) > 24,
    }


def monitor(db, cutoff, current):
    alerts = [dict(row) for row in db.execute("""
        SELECT a.eventKey, a.watchId, a.kind, a.city, a.price, a.createdAt,
               w.origin, w.regionLabel, w.tripLength, w.currency
        FROM alerts a JOIN watches w ON w.id = a.watchId
        WHERE w.active = 1 AND a.kind = 'deal' AND a.createdAt BETWEEN ? AND ?
        ORDER BY a.createdAt DESC, a.id DESC LIMIT 12
    """, (cutoff, current))]
    return {"status": "signals" if alerts else "empty", "source": "trip_agent_deal_alerts", "alerts": alerts}


def main():
    parser = argparse.ArgumentParser(description="Read saved Trip Agent flight observations or deal signals.")
    parser.add_argument("--snapshot", action="store_true", help="Show active watches and fresh saved observations.")
    parser.add_argument("--root", type=Path, default=HERMES_ROOT, help="Hermes root directory.")
    args = parser.parse_args()

    if not args.snapshot:
        missing = missing_prerequisites(args.root)
        if missing:
            print(json.dumps({"status": "waiting", "missing": missing}))
            return

    runtime = read_object(args.root / "shared/travel-workflow/runtime.json")
    scanner = runtime.get("scanner_dir")
    if not isinstance(scanner, str) or not Path(scanner).is_absolute():
        print(json.dumps({"status": "no_source", "source": "trip_agent_scanner"}))
        return
    data_dir = Path(scanner) / "data"
    owner = read_object(data_dir / "workflow-owner.json").get("hermes_root")
    if not isinstance(owner, str) or not Path(owner).is_absolute() or Path(owner).resolve() != args.root.resolve():
        print(json.dumps({"status": "no_source", "source": "trip_agent_scanner"}))
        return
    database = data_dir / "trip-bot.db"
    now = datetime.now(timezone.utc)
    cutoff, current = utc_millis(now - SCAN_AGE), utc_millis(now)
    today = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)) as db:
            db.row_factory = sqlite3.Row
            deadline = time.monotonic() + 1.0
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.execute("BEGIN")
            result = snapshot(db, cutoff, current, today, data_dir) if args.snapshot else monitor(db, cutoff, current)
    except (OSError, sqlite3.Error):
        result = {"status": "no_source", "source": "trip_agent_scanner"}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
