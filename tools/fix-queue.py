"""Queue and guard for the agent that fixes reported problems and opens pull requests.

`next` prints the oldest open issue the agent may work on, as JSON. This repository is public, so
only text written by the repository owner is passed on: issues and comments from anyone else are
left out, because the agent treats what it reads here as its task.

`check-pr` fails when an agent branch changes code without a test, or touches its own guard rails.
"""
import argparse
import json
import subprocess
import sys

SKIP_LABELS = {"agent-blocked", "manual"}
BRANCH_PREFIX = "agent/issue-"
PROTECTED = (".github/", "tools/fix-queue.py", ".claude/skills/fix-issue/")
CODE_SUFFIXES = (".py", ".ts")


def is_test(path):
    return path.startswith("tests/") or path.endswith(".test.ts")


def pick(issues, open_branches, owner):
    """The oldest owner-written issue that is not set aside and has no agent pull request open."""
    waiting = []
    for issue in issues:
        if issue["author"]["login"] != owner:
            continue
        if SKIP_LABELS & {label["name"] for label in issue["labels"]}:
            continue
        if f"{BRANCH_PREFIX}{issue['number']}" in open_branches:
            continue
        waiting.append(issue)
    if not waiting:
        return None
    issue = min(waiting, key=lambda item: item["number"])
    comments = issue.get("comments", [])
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "owner_comments": [c["body"] for c in comments if c["author"]["login"] == owner],
        "comments_left_out": sum(1 for c in comments if c["author"]["login"] != owner),
        "branch": f"{BRANCH_PREFIX}{issue['number']}",
    }


def pr_problems(files):
    problems = [f"agent branches may not change {path}" for path in files if path.startswith(PROTECTED)]
    code = [path for path in files if path.endswith(CODE_SUFFIXES) and not is_test(path)]
    if code and not any(is_test(path) for path in files):
        problems.append("code changed without a test that reproduces the problem: " + ", ".join(code))
    return problems


def gh_json(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("next", help="print the next issue to fix")
    check = commands.add_parser("check-pr", help="check the files an agent branch changed")
    check.add_argument("--base", default="origin/main")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.command == "next":
        owner = gh_json("repo", "view", "--json", "owner")["owner"]["login"]
        issues = gh_json("issue", "list", "--state", "open", "--limit", "100",
                         "--json", "number,title,body,author,labels,comments")
        pulls = gh_json("pr", "list", "--state", "open", "--limit", "100", "--json", "headRefName")
        issue = pick(issues, {pull["headRefName"] for pull in pulls}, owner)
        print(json.dumps({"issue": issue}, ensure_ascii=False, indent=2))
        return 0

    diff = subprocess.run(["git", "diff", "--name-only", f"{args.base}...HEAD"],
                          capture_output=True, text=True, encoding="utf-8", check=True)
    problems = pr_problems(diff.stdout.split())
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
