"""
Standalone diagnostic: calls the EXACT same git_scan.fetch_git_evidence()
the app uses for /api/git-jira-scan, and prints step-by-step what it found
-- total tree entries, how many were selected as source/doc paths (before
any cap), and how many actually got read successfully. Pinpoints whether a
"no Evidence Files" symptom is coming from the file-tree fetch, the path
selection/filtering, or the content-reading step.

Usage:
    cd server
    python check_source_evidence.py <repo_url> <branch> <token> [source_path] [doc_path] [provider]

Token via env var instead of a command-line arg (recommended):
    set GIT_TEST_TOKEN=glpat-xxx...
    python check_source_evidence.py https://gitlab.example.com/group/my-repo.git main "" src docs gitlab
"""
import os
import sys

import git_scan


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python check_source_evidence.py <repo_url> <branch> <token> [source_path] [doc_path] [provider]")
        print("(or set GIT_TEST_TOKEN env var instead of passing token as an arg)")
        return 1

    repo_url = sys.argv[1]
    branch = sys.argv[2] if len(sys.argv) > 2 else "main"
    token = sys.argv[3] if len(sys.argv) > 3 else os.getenv("GIT_TEST_TOKEN", "")
    source_path = sys.argv[4] if len(sys.argv) > 4 else ""
    doc_path = sys.argv[5] if len(sys.argv) > 5 else ""
    provider = sys.argv[6] if len(sys.argv) > 6 else ""

    print(f"Repo URL    : {repo_url}")
    print(f"Branch      : {branch}")
    print(f"Token       : {'set (' + str(len(token)) + ' chars)' if token else '(none)'}")
    print(f"Source Path : {source_path or '(root)'}")
    print(f"Doc Path    : {doc_path or '(anywhere in repo)'}")
    print(f"Provider    : {provider or '(auto-detect)'}")
    print("-" * 70)

    try:
        evidence = git_scan.fetch_git_evidence(repo_url, branch, token, provider, doc_path, source_path)
    except Exception as exc:
        print(f"RESULT: FAILED -- {type(exc).__name__}: {exc}")
        return 1

    workspace_path = evidence.get("workspace_path")
    tree_paths = evidence.get("tree_paths") or set()
    source_files = evidence.get("source_files") or []
    doc_files = evidence.get("doc_files") or []
    image_files = evidence.get("image_files") or []

    print("=" * 70)
    print(f"WORKSPACE_PATH (local clone used?) : {workspace_path or '(none -- fell back to REST API fetch)'}")
    print(f"TOTAL TREE ENTRIES from the API    : {len(tree_paths)}")
    print("=" * 70)

    sample = sorted(tree_paths)[:20]
    print(f"Sample of the first 20 raw tree paths (alphabetical) -- this is the REAL path")
    print(f"format the API/clone returns, to compare against what you typed as source_path:")
    for p in sample:
        print(f"    {p!r}")
    if not sample:
        print("    (tree_paths is completely empty)")

    needle = (source_path or "pimsathon").strip("/").lower()
    matches_ci = sorted(p for p in tree_paths if needle in p.lower())[:20]
    print(f"\nCase-insensitive search for {needle!r} anywhere in any tree path ({len(matches_ci)} shown, max 20):")
    for p in matches_ci:
        print(f"    {p!r}")
    if not matches_ci:
        print(f"    -> '{needle}' does not appear ANYWHERE in the {len(tree_paths)} tree paths at all.")
    print()

    selected_source = git_scan._select_source_paths(tree_paths, source_path)
    selected_doc = git_scan._select_doc_paths(tree_paths, doc_path)
    print(f"Source paths SELECTED (by extension/path, before reading) : {len(selected_source)}")
    print(f"Doc paths SELECTED (by extension/path, before reading)    : {len(selected_doc)}")
    if selected_source[:10]:
        print("  Sample selected source paths:")
        for p in selected_source[:10]:
            print(f"    - {p}")
    if not selected_source:
        print("  -> NONE selected. This means _select_source_paths found zero matching tree")
        print("     entries under this source_path -- check the exact folder name/case, and")
        print("     whether `tree_paths` itself is empty/truncated (see count above).")

    print(f"Source files ACTUALLY READ (content non-empty) : {len(source_files)}")
    print(f"Doc files ACTUALLY READ (content non-empty)     : {len(doc_files)}")
    print(f"Image files found                                : {len(image_files)}")
    if source_files[:5]:
        print("  Sample source files read:")
        for p, text in source_files[:5]:
            print(f"    - {p} ({len(text)} chars)")
    elif selected_source:
        print("  -> Paths were SELECTED but zero were actually read successfully.")
        print("     If workspace_path is set above, check the clone actually contains these")
        print("     paths (git checkout may have failed partway, or paths differ by case).")
        print("     If workspace_path is (none), the per-file REST API fetch is failing")
        print("     silently per-file (e.g. token lacks API scope, or rate-limited).")

    if workspace_path:
        git_scan.git_workspace.cleanup_workspace(workspace_path)
        print()
        print("(cleaned up the test clone)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
