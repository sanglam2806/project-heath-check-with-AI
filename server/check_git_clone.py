"""
Standalone diagnostic: attempts to clone a Git repo using the exact same
git_workspace.clone_repo() the app itself calls (git_scan.py for the main
scan, deep_dive_agent's caller for Layer 4), and reports precisely why it
failed -- git not installed, bad URL, auth rejected, branch not found,
timeout, or something else. Does not touch any DB/ticket/scan state --
safe to run standalone against a real repo.

Usage:
    cd server
    python check_git_clone.py <repo_url> [branch] [token] [username]

Token via env var instead of a command-line arg (recommended -- command-line
args can end up in shell history / process listings):
    set GIT_TEST_TOKEN=ghp_xxx...
    python check_git_clone.py https://gitlab.example.com/group/repo.git main
"""
import os
import sys

import git_workspace


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python check_git_clone.py <repo_url> [branch] [token] [username]")
        print("(or set GIT_TEST_TOKEN env var instead of passing token as an arg)")
        return 1

    repo_url = sys.argv[1]
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"
    token = sys.argv[3] if len(sys.argv) > 3 else os.getenv("GIT_TEST_TOKEN", "")
    username = sys.argv[4] if len(sys.argv) > 4 else ""

    print(f"Repo URL : {repo_url}")
    print(f"Branch   : {branch}")
    print(f"Token    : {'set (' + str(len(token)) + ' chars)' if token else '(none)'}")
    print(f"Username : {username or '(none)'}")
    print("-" * 60)

    try:
        path = git_workspace.clone_repo(repo_url, branch, token, username)
    except git_workspace.GitWorkspaceError as exc:
        print(f"RESULT: FAILED -- {exc}")
        print(f"(i18n key: {exc.key})")
        print()
        _print_hint(exc.key)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"RESULT: FAILED (unexpected exception) -- {type(exc).__name__}: {exc}")
        return 1

    file_count = sum(len(files) for _, _, files in os.walk(path))
    print(f"RESULT: SUCCESS -- cloned to {path}")
    print(f"File count under clone: {file_count}")
    git_workspace.cleanup_workspace(path)
    print("Cleaned up the test clone.")
    return 0


def _print_hint(key: str) -> None:
    hints = {
        "gitworkspace.git_not_installed": (
            "-> Install Git on this machine and make sure `git` is on PATH "
            "(e.g. `winget install Git.Git` on Windows), then restart the terminal/backend."
        ),
        "gitworkspace.url_required": "-> The repo URL field is empty.",
        "gitworkspace.http_only": "-> Use an http:// or https:// URL, not git@/ssh://.",
        "gitworkspace.timeout": (
            "-> The clone took longer than 120s. Could be a very large repo, a slow/"
            "unreachable host, or a firewall silently dropping the connection -- try "
            "`git clone <url>` manually from this same machine to compare."
        ),
        "gitworkspace.branch_not_found": "-> Double-check the exact branch name (case-sensitive).",
        "gitworkspace.auth_required": (
            "-> The token is invalid/expired, or lacks read access to this repo. For a "
            "self-hosted GitLab that authenticates against a real account, also try "
            "passing the username as the 4th argument."
        ),
        "gitworkspace.clone_failed": (
            "-> Generic git failure -- re-run this script and check the stderr excerpt "
            "logged by the backend (or add a print(result.stderr) in git_workspace.clone_repo "
            "temporarily) for the exact git error message."
        ),
    }
    hint = hints.get(key)
    if hint:
        print(hint)


if __name__ == "__main__":
    sys.exit(main())
