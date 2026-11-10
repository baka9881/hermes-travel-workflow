import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node required")
class ScanWrapperTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hermes-wrapper-test-"))
        self.scanner = self.root / "scanner with spaces"
        (self.scanner / "src").mkdir(parents=True)
        (self.scanner / "src/cli.ts").write_text("", encoding="utf-8")
        entry = self.scanner / "node_modules/tsx/dist/cli.mjs"
        entry.parent.mkdir(parents=True)
        entry.write_text("process.stdout.write(JSON.stringify({args:process.argv.slice(3),cwd:process.cwd(),db:process.env.TRIP_BOT_DB}));", encoding="utf-8")
        self.configure(self.root)

    def configure(self, root):
        config = root / "shared/travel-workflow/runtime.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"scanner_dir": str(self.scanner), "node": NODE, "timezone": "Asia/Taipei"}), encoding="utf-8")

    def run_wrapper(self, *args, root=None):
        env = os.environ.copy()
        env["TRIP_BOT_DB"] = str(self.root / "must-not-use.db")
        return subprocess.run([sys.executable, str(REPO / "scripts/scan-trip.py"), "--root", str(root or self.root), *args], capture_output=True, text=True, encoding="utf-8", env=env)

    def test_default_tick_is_isolated_and_checkout_cannot_be_shared(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["args"], ["tick"])
        self.assertEqual(Path(report["cwd"]), self.scanner)
        self.assertEqual(Path(report["db"]), self.scanner / "data/trip-bot.db")
        self.assertEqual(self.run_wrapper("regions").returncode, 0)
        other = self.root / "other-root"
        self.configure(other)
        conflict = self.run_wrapper("regions", root=other)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("another Hermes root", conflict.stderr)

    def test_direct_send_is_rejected_before_data_creation(self):
        result = self.run_wrapper("regions", "--telegram")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.scanner / "data").exists())

    def test_existing_unowned_data_is_not_adopted(self):
        data = self.scanner / "data"
        data.mkdir()
        (data / "settings.json").write_text("{}", encoding="utf-8")
        result = self.run_wrapper("regions")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unowned", result.stderr)


if __name__ == "__main__":
    unittest.main()
