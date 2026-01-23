from __future__ import annotations

import subprocess


def _run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        stderr = (p.stderr or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{stderr}")
    return p.stdout


def detect_base_ref(preferred: str = "develop") -> str:
    return preferred


def merge_base(base_ref: str, head_ref: str) -> str:
    return _run(["git", "merge-base", base_ref, head_ref]).strip()


def changed_files(base_ref: str, head_ref: str) -> list[str]:
    base = merge_base(base_ref, head_ref)
    out = _run(["git", "diff", "--name-only", f"{base}..{head_ref}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def diff_for_file(base_ref: str, head_ref: str, path: str, *, unified: int = 3) -> str:
    base = merge_base(base_ref, head_ref)
    return _run(
        [
            "git",
            "diff",
            f"--unified={int(unified)}",
            f"{base}..{head_ref}",
            "--",
            path,
        ]
    )


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def current_branch() -> str:
    try:
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    except Exception:
        return "unknown"
    return branch if branch else "unknown"


def has_changes() -> bool:
    p = run(["git", "status", "--porcelain"])
    if p.returncode != 0:
        raise RuntimeError(f"git status failed:\n{p.stderr}")
    return bool((p.stdout or "").strip())


def status_entries() -> list[tuple[str, str]]:
    """
    Return (status, path) entries in the working tree (including untracked).
    Uses `--porcelain=v1 -z` to handle whitespace and renames robustly.
    """
    p = run(["git", "status", "--porcelain=v1", "-z"])
    if p.returncode != 0:
        raise RuntimeError(f"git status failed:\n{p.stderr}")

    out = p.stdout or ""
    if not out:
        return []

    entries = out.split("\0")
    results: list[tuple[str, str]] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        if not entry:
            i += 1
            continue

        status = entry[:2]
        rest = entry[3:] if len(entry) >= 4 else ""
        if rest:
            results.append((status, rest))

        if status and status[0] in {"R", "C"}:
            if i + 1 < len(entries) and entries[i + 1]:
                results.append((status, entries[i + 1]))
            i += 2
        else:
            i += 1

    return results


def ensure_clean_working_tree(
    allowed_dirty_paths: list[str] | None = None,
    *,
    ignore_untracked: bool = False,
) -> None:
    entries = status_entries()
    if ignore_untracked:
        entries = [e for e in entries if e[0] != "??"]

    if not entries:
        return

    allowed = set(allowed_dirty_paths or [])
    if allowed and all(path in allowed for _, path in entries):
        return

    msg = "Working tree is not clean."
    if allowed:
        msg += " Unrelated changes detected outside the PR-changed Python files."
    msg += " Commit/stash your current changes before running this skill."
    raise RuntimeError(msg)


def commit(message: str, *, paths: list[str] | None = None) -> None:
    if paths:
        run(["git", "add", "--", *paths])
    else:
        run(["git", "add", "-A"])
    p = run(["git", "commit", "-m", message])
    if p.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{p.stderr}")


def ls_files() -> list[str]:
    p = run(["git", "ls-files"])
    if p.returncode != 0:
        return []
    return [line.strip() for line in (p.stdout or "").splitlines() if line.strip()]
