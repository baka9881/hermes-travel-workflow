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
PROFILES = ("trip", "travel-commander", "schedule-manager")
PROFILE_NAMES = ("Trip Agent", "旅遊總指揮官 小居", "Schedule Manager")
REPLY_CHECK = "travel-reply-check"
REPLY_CHECK_FILES = ("plugin.yaml", "__init__.py")
JOBS = (("trip", "travel-workflow/scanner"),
        ("travel-commander", "travel-workflow/weekly"),
        ("travel-commander", "travel-workflow/alerts"))
DELIVERED_JOBS = JOBS[1:]
RECEIPT = ".travel-workflow-install.json"
# Applied once to each newly created profile. Compress before small-window providers reject the
# request (one rejected ~75K tokens), but above the ~40K the role, tools and skills already use: at
# 50K one reply compressed six times and re-ran the same searches after each. Prune old tool output
# first, and keep each web page read short. No "♻️ 閘道已上線" ping in the chat after every gateway
# restart (2026-11-12: the user kept getting it). Start a fresh conversation with the first message
# after 04:00 instead of compressing one endless chat (needs the hermes-session-reset-policy plugin;
# the roles carry unanswered button questions over in pending_question). Later user changes to these
# settings are left alone.
PROFILE_SETTINGS = (("compression.threshold_tokens", "64000"),
                    ("compression.proactive_prune_tokens", "45000"),
                    ("web.extract_char_limit", "5000"),
                    ("telegram.gateway_restart_notification", "false"),
                    ("session_reset.mode", "daily"),
                    ("session_reset.at_hour", "4"),
                    # Buttons stay usable for 10 minutes; Hermes' default 90 s expired them before
                    # the user had read the plan on a phone (Telegram test, 2026-11-14).
                    ("agent.clarify_timeout", "600"))


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
        hint = (f"; to switch delivery run: setup.py delivery {deliver} --root <root>"
                if job.get("deliver") != deliver and name != "travel-workflow/scanner" else "")
        raise RuntimeError(f"Existing job differs; refusing to change: {name}{hint}")
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
    required += [PACKAGE / "scripts" / f"{p}.py" for p in ("travel-scout", "scan-trip", "phone-check", "booking-links",
                                                                "trip-cost", "calendar-check", "place-photo", "page_evidence")]
    required += [PACKAGE / "state" / f"{p}.json" for p in ("calendar", "preferences", "opportunities")]
    required += [PACKAGE / "skills" / "travel-planning" / "SKILL.md"]
    required += [PACKAGE / "plugins" / REPLY_CHECK / f for f in REPLY_CHECK_FILES]
    missing = [str(p) for p in required if not p.is_file()]
    if missing or not scanner.is_dir():
        raise RuntimeError(f"Package files missing: {missing}; scanner={scanner}")
    receipt_path = root / RECEIPT
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
    delivery = delivery_for(receipt, delivery)
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
            for key, value in PROFILE_SETTINGS:
                run(root, "-p", profile, "config", "set", key, value)
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
        ("scripts/travel-scout.py", "profiles/travel-commander/scripts/travel-scout.py"),
        ("scripts/scan-trip.py", "profiles/trip/scripts/scan-trip.py"),
        ("scripts/phone-check.py", "shared/travel-workflow/phone-check.py"),
        ("scripts/booking-links.py", "shared/travel-workflow/booking-links.py"),
        ("scripts/trip-cost.py", "shared/travel-workflow/trip-cost.py"),
        ("scripts/page_evidence.py", "shared/travel-workflow/page_evidence.py"),
        ("scripts/calendar-check.py", "shared/travel-workflow/calendar-check.py"),
        ("scripts/place-photo.py", "shared/travel-workflow/place-photo.py"),
        ("skills/travel-planning/SKILL.md", "profiles/travel-commander/skills/travel-planning/SKILL.md"),
    ]:
        same_or_create(root / target, rendered(PACKAGE / source, root))
    # 2026-11-14: a button question went out with a total the cost tool had not printed; this
    # plugin holds such a question back until it matches (plugins/travel-reply-check).
    for profile in PROFILES:
        for name in REPLY_CHECK_FILES:
            same_or_create(root / "profiles" / profile / "plugins" / REPLY_CHECK / name,
                           (PACKAGE / "plugins" / REPLY_CHECK / name).read_bytes())
        run(root, "-p", profile, "plugins", "enable", REPLY_CHECK)
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
    ensure_job(root, "travel-commander", "travel-workflow/weekly", "0 9 * * 1", weekly, delivery, continuity=True)
    ensure_job(root, "travel-commander", "travel-workflow/alerts", "*/15 * * * *", alert, delivery,
               monitor="travel-scout.py", continuity=True)
    if receipt.get("delivery") != delivery:
        receipt["delivery"] = delivery
        save_receipt(receipt_path, receipt)
    print(f"Installed in {root}. New jobs are paused; existing job state was preserved.")
    if not (scanner / "node_modules/tsx/dist/cli.mjs").is_file():
        print("Scanner dependencies are not installed yet: npm --prefix scanner ci --ignore-scripts")


def delivery_for(receipt, requested):
    """An explicit --deliver wins; otherwise keep what this root was installed with."""
    return requested or receipt.get("delivery") or "local"


def managed(root):
    root = root.expanduser().resolve()
    path = root / RECEIPT
    if not path.is_file() or read_json(path).get("version") != 1:
        raise RuntimeError(f"Root is not managed by this installer: {root}")
    return root, read_json(path)


def managed_job(root, profile, name):
    matches = [j for j in jobs(root, profile) if j.get("name") == name]
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise RuntimeError(f"Expected exactly one {name} job in {profile}, found {len(matches)}; run install first")
    return matches[0]


def set_state(root, action):
    root, _ = managed(root)
    found = [(profile, managed_job(root, profile, name)) for profile, name in JOBS]
    for profile, job in found:
        if (job.get("enabled") is True) == (action == "resume"):
            print(f"{job['name']}: already {'running' if action == 'resume' else 'paused'}")
            continue
        run(root, "-p", profile, "cron", action, job["id"])
        print(f"{job['name']}: {'resumed' if action == 'resume' else 'paused'}")


def set_delivery(root, target):
    root, receipt = managed(root)
    found = [(profile, managed_job(root, profile, name)) for profile, name in DELIVERED_JOBS]
    for profile, job in found:
        if job.get("deliver") != target:
            run(root, "-p", profile, "cron", "edit", job["id"], "--deliver", target)
        print(f"{job['name']}: deliver {target}")
    receipt["delivery"] = target
    save_receipt(root / RECEIPT, receipt)


def gateway_serving(root, profile):
    """True when a Hermes gateway is serving this profile's cron jobs."""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(root)
    result = subprocess.run(["hermes", "-p", profile, "cron", "status"], env=env, text=True,
                            encoding="utf-8", errors="replace", capture_output=True)
    output = result.stdout + result.stderr
    if "No scheduler is serving" in output:
        return False
    return "Gateway is running" in output


def check(root):
    """Read-only health report. Returns 1 when something needs attention."""
    root, _ = managed(root)
    problems = []
    try:
        runtime = read_json(root / "shared/travel-workflow/runtime.json")
        scanner, node = Path(runtime["scanner_dir"]), Path(runtime["node"])
    except (OSError, ValueError, KeyError, TypeError):
        scanner = node = None
        problems.append("runtime.json missing or unreadable; run install")
    if node is not None and not node.is_file():
        problems.append(f"node not found at {node}; run install again from a shell where node 24+ is on PATH")
    if scanner is not None and not (scanner / "node_modules/tsx/dist/cli.mjs").is_file():
        problems.append(f"scanner dependencies missing in {scanner}: npm --prefix scanner ci --ignore-scripts")
    print(f"Hermes root: {root}")
    for profile, name in JOBS:
        found = [j for j in jobs(root, profile) if j.get("name") == name]
        if len(found) != 1:
            problems.append(f"{name}: expected one job in {profile}, found {len(found)}")
            continue
        job = found[0]
        state = "running" if job.get("enabled") else "paused"
        print(f"  {name} ({profile}): {state}, deliver={job.get('deliver')}, last={job.get('last_status') or 'never'}")
        error = job.get("last_error") or job.get("last_delivery_error")
        if job.get("failure_streak") or job.get("last_status") == "error" or error:
            problems.append(f"{name}: {job.get('failure_streak', 0)} failure(s) in a row; last error: {error or 'unknown'}")
    running = [name for profile, name in JOBS
               if any(j.get("name") == name and j.get("enabled") for j in jobs(root, profile))]
    serving = all(gateway_serving(root, profile) for profile in sorted({p for p, _ in JOBS}))
    print(f"  gateway: {'running' if serving else 'not running'}")
    if running and not serving:
        problems.append(f"{', '.join(running)} will not run until a Hermes gateway serves this root: "
                        f"set HERMES_HOME to it, then run hermes gateway run (or gateway install)")
    scout = root / "profiles/travel-commander/scripts/travel-scout.py"
    if scout.is_file():
        result = subprocess.run([sys.executable, str(scout), "--root", str(root)], capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        try:
            signal = json.loads(result.stdout)
        except ValueError:
            signal = {"status": "error"}
        detail = ", ".join(signal.get("missing", [])) if signal.get("status") == "waiting" else ""
        print(f"  alert gate: {signal.get('status')}{' (missing ' + detail + ')' if detail else ''}")
    if problems:
        print("Needs attention:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("No problems found.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("install", help="install or verify the workflow in a Hermes root")
    command.add_argument("--root", type=Path, required=True)
    command.add_argument("--deliver", choices=("local", "telegram"),
                         help="digest/alert delivery for a new root (default: local, or the root's current setting)")
    for name, text in [("check", "read-only health report"), ("resume", "start the three workflow jobs"),
                       ("pause", "pause the three workflow jobs")]:
        sub.add_parser(name, help=text).add_argument("--root", type=Path, required=True)
    command = sub.add_parser("delivery", help="switch digest/alert delivery")
    command.add_argument("target", choices=("local", "telegram"))
    command.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check":
            return check(args.root)
        if args.command in ("resume", "pause"):
            set_state(args.root, args.command)
        elif args.command == "delivery":
            set_delivery(args.root, args.target)
        else:
            install(args.root, args.deliver)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"{args.command} stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
