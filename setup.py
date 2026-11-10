#!/usr/bin/env python3
"""Install the travel workflow into an explicit, separate Hermes home."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parent
PROFILES = ("trip", "project-manager", "us-market")
PROFILE_NAMES = ("Trip Agent", "旅遊總指揮官 小居", "Schedule Manager")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(root, *args):
    env = os.environ.copy()
    env["HERMES_HOME"] = str(root)
    result = subprocess.run(["hermes", *args], env=env, text=True,
                            encoding="utf-8", errors="replace", capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Hermes command failed: {args!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as out:
        out.write(data)


def same_or_create(path, data, *, preserve=False):
    if path.exists():
        if not preserve and path.read_bytes() != data:
            raise RuntimeError(f"Existing file differs; refusing to overwrite: {path}")
        return
    write_new(path, data)


def rendered(path, root):
    return (path.read_text(encoding="utf-8")
            .replace("{{ROOT}}", root.as_posix())
            .replace("{{PYTHON}}", Path(sys.executable).resolve().as_posix()).encode("utf-8"))


def save_receipt(path, receipt):
    # Receipt is package-owned metadata, never user state.
    tmp = path.with_suffix(".tmp")
    if tmp.exists():
        raise RuntimeError(f"Interrupted receipt update; inspect {tmp}")
    write_new(tmp, (json.dumps(receipt, indent=2) + "\n").encode())
    os.replace(tmp, path)


def jobs(root, profile):
    path = root / "profiles" / profile / "cron" / "jobs.json"
    if not path.exists():
        return []
    data = read_json(path)
    if not isinstance(data.get("jobs"), list):
        raise RuntimeError(f"Unrecognized Hermes jobs format: {path}")
    return data["jobs"]


def ensure_job(root, profile, name, schedule, prompt, deliver, *, script=None,
               monitor=None, continuity=False):
    prompt = prompt.strip()
    matches = [j for j in jobs(root, profile) if j.get("name") == name]
    created = not matches
    python = str(Path(sys.executable).resolve())
    expected = {"prompt": prompt, "deliver": deliver, "script": script,
                "monitor_script": monitor, "no_agent": bool(script),
                "monitor_url": None, "timezone": "Asia/Taipei", "catch_up": False,
                "context_from": ["self"] if continuity else None,
                "interpreter": python if script or monitor else None,
                "failure_deliver": "local" if continuity else None,
                "model": None, "provider": None, "base_url": None,
                "skills": [], "enabled_toolsets": None, "workdir": None}
    if created:
        args = ["-p", profile, "cron", "create", schedule]
        if prompt:
            args.append(prompt)
        args += ["--name", name, "--deliver", deliver, "--catch-up", "off",
                 "--timezone", "Asia/Taipei", "--paused"]
        if script:
            args += ["--script", script, "--no-agent", "--interpreter", python]
        if monitor:
            args += ["--monitor-script", monitor, "--interpreter", python]
        if continuity:
            args += ["--continuity", "--failure-deliver", "local"]
        run(root, *args)
        matches = [j for j in jobs(root, profile) if j.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {name} job in {profile}, found {len(matches)}")
    job = matches[0]
    if (job.get("schedule", {}).get("kind") != "cron"
            or job.get("schedule", {}).get("expr") != schedule
            or job.get("repeat", {}).get("times") is not None
            or any(job.get(key) != value for key, value in expected.items())):
        raise RuntimeError(f"Existing job differs; refusing to change: {name}")
    if created and (job.get("state") != "paused" or job.get("enabled") is not False):
        raise RuntimeError(f"Hermes did not create {name} paused")


def install(root, delivery):
    root = root.expanduser().resolve()
    if root == PACKAGE or PACKAGE in root.parents:
        raise RuntimeError("Choose a Hermes root outside the Git checkout")
    node = shutil.which("node")
    if not node or not shutil.which("hermes"):
        raise RuntimeError("Node and Hermes must be available on PATH")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if int(version.lstrip("v").split(".")[0]) < 24:
        raise RuntimeError(f"Node 24 or newer is required; found {version}")
    scanner = (PACKAGE / "scanner").resolve()
    required = [PACKAGE / "roles" / f"{p}.md" for p in PROFILES]
    required += [PACKAGE / "prompts" / f"{p}.md" for p in ("weekly", "alert")]
    required += [PACKAGE / "scripts" / f"{p}.py" for p in ("travel-scout", "scan-trip")]
    required += [PACKAGE / "state" / f"{p}.json" for p in ("calendar", "preferences", "opportunities")]
    required += [PACKAGE / "skills" / "travel-planning" / "SKILL.md"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing or not scanner.is_dir():
        raise RuntimeError(f"Package files missing: {missing}; scanner={scanner}")
    receipt_path = root / ".travel-workflow-install.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("version") != 1:
            raise RuntimeError("Unrecognized install receipt")
    else:
        if root.exists() and any(root.iterdir()):
            raise RuntimeError(f"Root must be new or already managed: {root}")
        root.mkdir(parents=True, exist_ok=True)
        receipt = {"version": 1, "profiles": {}}
        save_receipt(receipt_path, receipt)
    for profile, display_name in zip(PROFILES, PROFILE_NAMES):
        home = root / "profiles" / profile
        soul = home / "SOUL.md"
        wanted = rendered(PACKAGE / "roles" / f"{profile}.md", root)
        if not home.exists():
            run(root, "profile", "create", profile, "--no-alias", "--no-skills",
                "--description", display_name)
            if not soul.is_file():
                raise RuntimeError(f"Native profile has no scaffold SOUL: {soul}")
            receipt["profiles"][profile] = digest(soul.read_bytes())
            save_receipt(receipt_path, receipt)
        scaffold = receipt["profiles"].get(profile)
        if not scaffold:
            raise RuntimeError(f"Existing unowned profile: {home}")
        if soul.exists() and soul.read_bytes() != wanted:
            if digest(soul.read_bytes()) != scaffold:
                raise RuntimeError(f"Profile SOUL modified; refusing overwrite: {soul}")
            soul.write_bytes(wanted)
        elif not soul.exists():
            write_new(soul, wanted)
    for source, target in [
        ("scripts/travel-scout.py", "profiles/project-manager/scripts/travel-scout.py"),
        ("scripts/scan-trip.py", "profiles/trip/scripts/scan-trip.py"),
        ("skills/travel-planning/SKILL.md", "profiles/project-manager/skills/travel-planning/SKILL.md"),
    ]:
        same_or_create(root / target, rendered(PACKAGE / source, root))
    for name, target in [("calendar", "shared/annual-schedule/calendar.json"),
                         ("preferences", "shared/travel-workflow/preferences.json"),
                         ("opportunities", "shared/travel-workflow/opportunities.json")]:
        same_or_create(root / target, rendered(PACKAGE / "state" / f"{name}.json", root), preserve=True)
    runtime = {"scanner_dir": str(scanner), "timezone": "Asia/Taipei", "node": str(Path(node).resolve())}
    same_or_create(root / "shared/travel-workflow/runtime.json",
                   (json.dumps(runtime, indent=2, ensure_ascii=False) + "\n").encode())
    boards = json.loads(run(root, "kanban", "boards", "list", "--json", "--all"))
    matches = [b for b in boards if b.get("slug") == "command-center"]
    if len(matches) > 1 or (matches and matches[0].get("archived")):
        raise RuntimeError("Ambiguous or archived command-center board")
    if not matches:
        run(root, "kanban", "boards", "create", "command-center")
    weekly = rendered(PACKAGE / "prompts/weekly.md", root).decode("utf-8")
    alert = rendered(PACKAGE / "prompts/alert.md", root).decode("utf-8")
    ensure_job(root, "trip", "travel-workflow/scanner", "*/15 * * * *", "", "local", script="scan-trip.py")
    ensure_job(root, "project-manager", "travel-workflow/weekly", "0 9 * * 1", weekly, delivery, continuity=True)
    ensure_job(root, "project-manager", "travel-workflow/alerts", "*/15 * * * *", alert, delivery,
               monitor="travel-scout.py", continuity=True)
    print(f"Installed in {root}. New jobs are paused; existing job state was preserved.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("install")
    command.add_argument("--root", type=Path, required=True)
    command.add_argument("--deliver", choices=("local", "telegram"), default="local")
    args = parser.parse_args()
    try:
        install(args.root, args.deliver)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Install stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
