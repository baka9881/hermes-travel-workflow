import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow_setup", REPO / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeHermes:
    """Stands in for the Hermes CLI by editing each profile's jobs.json."""

    def __init__(self, root):
        self.root = root
        self.calls = []

    def path(self, profile):
        return self.root / "profiles" / profile / "cron" / "jobs.json"

    def add(self, profile, job_id, name, **fields):
        path = self.path(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"jobs": []}
        data["jobs"].append({"id": job_id, "name": name, "enabled": False, "state": "paused",
                             "deliver": "local", "last_status": None, "last_error": None,
                             "last_delivery_error": None, "failure_streak": 0, **fields})
        path.write_text(json.dumps(data), encoding="utf-8")

    def __call__(self, root, *args):
        self.calls.append(args)
        profile, verb, job_id = args[1], args[3], args[4]
        path = self.path(profile)
        data = json.loads(path.read_text(encoding="utf-8"))
        job = next(j for j in data["jobs"] if j["id"] == job_id)
        if verb == "resume":
            job.update(enabled=True, state="scheduled")
        elif verb == "pause":
            job.update(enabled=False, state="paused")
        elif verb == "edit":
            job["deliver"] = args[args.index("--deliver") + 1]
        path.write_text(json.dumps(data), encoding="utf-8")
        return ""


class SetupCommandTests(unittest.TestCase):
    def setUp(self):
        # Retain fixtures: the user's policy forbids recursive cleanup.
        self.root = Path(tempfile.mkdtemp(prefix="hermes-setup-test-"))
        (self.root / ".travel-workflow-install.json").write_text(json.dumps({"version": 1, "profiles": {}}), encoding="utf-8")
        self.hermes = FakeHermes(self.root)
        self.hermes.add("trip", "s1", "travel-workflow/scanner")
        self.hermes.add("travel-commander", "w1", "travel-workflow/weekly")
        self.hermes.add("travel-commander", "a1", "travel-workflow/alerts")
        self.hermes.add("travel-commander", "x1", "someone-else/job")
        self.original_run = setup.run
        setup.run = self.hermes

    def tearDown(self):
        setup.run = self.original_run

    def quiet(self, function, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = function(*args)
        return result, out.getvalue()

    def receipt(self):
        return json.loads((self.root / ".travel-workflow-install.json").read_text(encoding="utf-8"))

    def test_resume_and_pause_touch_only_managed_jobs_once(self):
        self.quiet(setup.set_state, self.root, "resume")
        self.assertEqual(sorted(c[4] for c in self.hermes.calls), ["a1", "s1", "w1"])
        self.quiet(setup.set_state, self.root, "resume")
        self.assertEqual(len(self.hermes.calls), 3)
        self.quiet(setup.set_state, self.root, "pause")
        self.assertEqual([c[3] for c in self.hermes.calls[3:]], ["pause"] * 3)

    def test_delivery_changes_digest_jobs_and_is_remembered(self):
        self.quiet(setup.set_delivery, self.root, "telegram")
        self.assertEqual(sorted(c[4] for c in self.hermes.calls), ["a1", "w1"])
        self.assertEqual(self.receipt()["delivery"], "telegram")
        self.assertEqual(setup.delivery_for(self.receipt(), None), "telegram")
        self.assertEqual(setup.delivery_for({"version": 1}, None), "local")
        self.assertEqual(setup.delivery_for(self.receipt(), "local"), "local")

    def test_unmanaged_root_is_refused(self):
        other = Path(tempfile.mkdtemp(prefix="hermes-setup-unmanaged-"))
        with self.assertRaisesRegex(RuntimeError, "not managed"):
            setup.set_state(other, "resume")
        self.assertEqual(self.hermes.calls, [])

    def test_check_reports_missing_dependencies_and_failing_jobs(self):
        runtime = self.root / "shared/travel-workflow/runtime.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text(json.dumps({"scanner_dir": str(self.root / "no-scanner"), "node": str(self.root / "no-node")}), encoding="utf-8")
        data = json.loads(self.hermes.path("travel-commander").read_text(encoding="utf-8"))
        data["jobs"][1].update(last_status="error", last_error="model quota", failure_streak=3)
        self.hermes.path("travel-commander").write_text(json.dumps(data), encoding="utf-8")
        status, report = self.quiet(setup.check, self.root)
        self.assertEqual(status, 1)
        self.assertIn("scanner dependencies", report)
        self.assertIn("node", report)
        self.assertIn("travel-workflow/alerts", report)
        self.assertIn("model quota", report)
        self.assertIn("paused", report)
        self.assertEqual(self.hermes.calls, [])


if __name__ == "__main__":
    unittest.main()
