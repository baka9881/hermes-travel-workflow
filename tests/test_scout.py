import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class ScoutTests(unittest.TestCase):
    def setUp(self):
        # Retain fixtures: the user's policy forbids recursive cleanup.
        self.root = Path(tempfile.mkdtemp(prefix="hermes-scout-test-"))
        self.scanner = self.root / "scanner"
        self.data = self.scanner / "data"
        self.data.mkdir(parents=True)
        (self.data / "workflow-owner.json").write_text(json.dumps({"hermes_root": str(self.root)}), encoding="utf-8")
        self.put("shared/travel-workflow/runtime.json", {"scanner_dir": str(self.scanner), "timezone": "Asia/Taipei"})

    def put(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), encoding="utf-8")

    def run_scout(self, *args):
        result = subprocess.run([sys.executable, str(REPO / "scripts/travel-scout.py"), "--root", str(self.root), *args], text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def ready(self):
        self.put("shared/travel-workflow/preferences.json", {"budget": {"amount": 50000, "currency": "TWD", "scope": "entire_trip"}})
        self.put("shared/annual-schedule/calendar.json", {"coverage": {"status": "verified", "start": "2026-01-01", "end": "2030-12-31", "checked_at": "2026-01-01T00:00:00Z"}})

    def test_unscoped_budget_and_partial_calendar_remain_waiting(self):
        self.put("shared/travel-workflow/preferences.json", {"budget": 50000})
        self.put("shared/annual-schedule/calendar.json", {"coverage": {"status": "partial", "start": "2026-01-01", "end": "2030-12-31"}})
        self.assertEqual(self.run_scout(), {"status": "waiting", "missing": ["budget", "calendar_coverage"]})

    def database(self):
        source = (REPO / "scanner/src/store.ts").read_text(encoding="utf-8")
        schema = re.search(r"const SCHEMA = `([\s\S]*?)`;", source).group(1)
        database = self.data / "trip-bot.db"
        now = datetime.now(timezone.utc)
        self.now = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        stale = (now - timedelta(hours=13)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        future = (now + timedelta(days=10)).date().isoformat()
        with sqlite3.connect(database) as db:
            db.executescript(schema)
            db.execute("INSERT INTO watches (id, origin, originLabel, region, regionLabel, tripLength, nextScanAt, lastScanAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("sample", "TPE", "Taipei", "Japan", "Japan", "7", self.now, self.now))
            for price, at in [(9000, self.now), (1000, stale)]:
                db.execute("INSERT INTO observations (watchId, city, outboundDate, returnDate, stops, price, currency, scannedAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("sample", "Tokyo", future, future, 0, price, "TWD", at))
            for key, kind, at in [("fresh", "deal", self.now), ("old", "deal", stale), ("digest", "digest", self.now)]:
                db.execute("INSERT INTO alerts (watchId, kind, city, price, eventKey, message, createdAt, nextAttemptAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("sample", kind, "Tokyo", 9000, key, "{}", at, at))
        return database

    def test_fresh_snapshot_and_signals_are_read_only(self):
        self.ready()
        database = self.database()
        before = hashlib.sha256(database.read_bytes()).digest()
        snapshot = self.run_scout("--snapshot")
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual([row["price"] for row in snapshot["active_watches"][0]["observations"]], [9000])
        signal = self.run_scout()
        self.assertEqual(signal["status"], "signals")
        self.assertEqual([row["eventKey"] for row in signal["alerts"]], ["fresh"])
        self.assertEqual(self.run_scout(), signal)
        self.assertEqual(hashlib.sha256(database.read_bytes()).digest(), before)

    def test_empty_and_missing_sources(self):
        self.ready()
        self.assertEqual(self.run_scout()["status"], "no_source")
        self.assertFalse((self.data / "trip-bot.db").exists())
        database = self.database()
        with sqlite3.connect(database) as db:
            db.execute("UPDATE watches SET active = 0")
        self.assertEqual(self.run_scout()["status"], "empty")
        self.assertEqual(self.run_scout("--snapshot")["status"], "empty")

    def test_invalid_budget_or_coverage_blocks_signals(self):
        self.database()
        for budget in [None, 1000, {"amount": True}, {"amount": -1}, {"amount": float("inf")}, {"amount": 1000, "scope": "flight_and_stay", "currency": "TWD"}]:
            with self.subTest(budget=budget):
                self.ready()
                self.put("shared/travel-workflow/preferences.json", {"budget": budget})
                self.assertEqual(self.run_scout(), {"status": "waiting", "missing": ["budget"]})
        for coverage in [None, {}, {"status": "verified", "start": "2030-01-01", "end": "2026-01-01", "checked_at": "2026-01-01T00:00:00Z"}, {"status": "verified", "start": "2026-01-01", "end": "2030-01-01", "checked_at": "not-a-date"}]:
            with self.subTest(coverage=coverage):
                self.ready()
                self.put("shared/annual-schedule/calendar.json", {"coverage": coverage})
                self.assertEqual(self.run_scout(), {"status": "waiting", "missing": ["calendar_coverage"]})

    def test_another_installation_cannot_read_the_database(self):
        self.ready()
        self.database()
        for owner in [{}, {"hermes_root": str(self.root / "someone-else")}]:
            (self.data / "workflow-owner.json").write_text(json.dumps(owner), encoding="utf-8")
            self.assertEqual(self.run_scout()["status"], "no_source")
            self.assertEqual(self.run_scout("--snapshot")["status"], "no_source")


if __name__ == "__main__":
    unittest.main()
