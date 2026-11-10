"""Run the portable scanner, bound to exactly one Hermes installation.

Installed location: ROOT/profiles/PROFILE/scripts/scan-trip.py.
No arguments runs tick. Other arguments pass through to the scanner CLI.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def lock_file(handle):
    """Keep a persistent lock file; the OS releases the lock on process exit."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command or ["tick"]
    if "--telegram" in command:
        parser.error("Direct Telegram delivery is disabled; use native Hermes delivery.")
    root = args.root.resolve()
    config = json.loads((root / "shared/travel-workflow/runtime.json").read_text(encoding="utf-8-sig"))
    scanner = Path(config["scanner_dir"])
    node = Path(config["node"])
    if not scanner.is_absolute() or not node.is_absolute() or not node.is_file():
        parser.error("scanner_dir and node must be valid absolute paths.")
    scanner = scanner.resolve()
    cli = scanner / "src/cli.ts"
    tsx = scanner / "node_modules/tsx/dist/cli.mjs"
    if not cli.is_file() or not tsx.is_file():
        parser.error("Scanner or dependencies missing; install scanner dependencies first.")
    data = scanner / "data"
    data.mkdir(exist_ok=True)
    lock = data / "scan.lock"
    with lock.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        try:
            lock_file(handle)
        except OSError:
            print("scanner: already running; skipped")
            return 0
        owner = data / "workflow-owner.json"
        if owner.exists():
            saved = json.loads(owner.read_text(encoding="utf-8"))
            if Path(saved["hermes_root"]).resolve() != root:
                parser.error("Scanner data belongs to another Hermes root. Use a separate checkout per installation.")
        else:
            if any(path.name not in {"scan.lock"} for path in data.iterdir()):
                parser.error("Existing unowned scanner data cannot be adopted. Use a fresh scanner checkout.")
            with owner.open("x", encoding="utf-8") as target:
                json.dump({"hermes_root": str(root)}, target)
        env = os.environ.copy()
        env["HERMES_HOME"] = str(root)
        env["TRIP_BOT_DB"] = str(data / "trip-bot.db")
        # The vendored scanner has no direct delivery capability. Do not pass
        # unrelated account credentials to its child process either.
        env.pop("TELEGRAM_BOT_TOKEN", None)
        env.pop("TELEGRAM_CHAT_ID", None)
        result = subprocess.run([str(node), str(tsx), str(cli), *command], cwd=scanner, env=env)
        return result.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"scanner: configuration or execution failed: {error}", file=sys.stderr)
        sys.exit(1)
