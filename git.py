from __future__ import annotations

import subprocess


def _run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        stderr = (p.stderr or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{stderr}")
    return p.stdout


def uncommitted_changed_files() -> list[str]:
    """
    Return paths that differ from HEAD (staged, unstaged) plus untracked paths.
    Caller typically filters to .py and existing files.
    """
    paths: set[str] = set()
    p = run(["git", "diff", "--name-only", "HEAD"])
    if p.returncode == 0 and p.stdout:
        for line in p.stdout.splitlines():
            if line.strip():
                paths.add(line.strip())
    for status, path in status_entries():
        if status == "??" and path:
            paths.add(path)
    return sorted(paths)


def diff_for_file_uncommitted(path: str, *, unified: int = 3) -> str:
    """Return uncommitted diff for path (working tree vs HEAD); empty string on error."""
    p = run(
        [
            "git",
            "diff",
            f"--unified={int(unified)}",
            "HEAD",
            "--",
            path,
        ]
    )
    return (p.stdout or "") if p.returncode == 0 else ""


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result without raising on non-zero exit."""
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def current_branch() -> str:
    """Return current branch name, or 'unknown' if not in a repo or on detached HEAD."""
    try:
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    except (RuntimeError, FileNotFoundError):
        return "unknown"
    return branch if branch else "unknown"


def _parse_porcelain_status(out: str) -> list[tuple[str, str]]:
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


def status_entries() -> list[tuple[str, str]]:
    """Return (status, path) entries in the working tree (including untracked)."""
    p = run(["git", "status", "--porcelain=v1", "-z"])
    if p.returncode != 0:
        raise RuntimeError(f"git status failed:\n{p.stderr}")
    out = p.stdout or ""
    return _parse_porcelain_status(out) if out else []
