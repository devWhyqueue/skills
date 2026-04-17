from __future__ import annotations

from pathlib import Path
from typing import Optional

from git import run as git_run


def find_package_root(path: Path) -> Optional[Path]:
    """Return the nearest parent directory containing __init__.py, or None."""
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def _scope_for_file(file_path: str) -> str:
    """Derive a single scope string for one file path."""
    p = Path(file_path)
    parts = p.parts
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    pkg_root = find_package_root(p)
    if pkg_root is not None:
        return pkg_root.name
    return parts[0] if len(parts) >= 2 else "core"


def derive_scope_from_files(files: list[str]) -> str:
    """Return a single scope label from a list of file paths (e.g. package name or 'multi')."""
    scopes = [s for s in (_scope_for_file(f) for f in files) if s]
    unique = sorted(set(scopes))
    if not unique:
        return "core"
    if len(unique) == 1:
        return unique[0]
    return "multi"


def normalize_package_value(value: str) -> str:
    """Normalize a package name or path: strip, normalize slashes, remove leading/trailing /."""
    v = (value or "").strip()
    v = v.replace("\\", "/")
    v = v.strip("/")
    v = v.replace(".", "/")
    return v


def git_ls_files() -> list[str]:
    """Return list of paths tracked by git in the current tree."""
    p = git_run(["git", "ls-files"])
    if p.returncode != 0:
        return []
    return [line.strip() for line in (p.stdout or "").splitlines() if line.strip()]


def _try_candidate_dirs(normalized: str) -> Path | None:
    """Try normalized path and src/normalized; return first existing dir or None."""
    candidates: list[Path] = [Path(normalized)]
    if not normalized.startswith("src/"):
        candidates.append(Path("src") / Path(normalized))
    for cand in candidates:
        if cand.exists() and cand.is_dir():
            return cand
    return None


def _resolve_via_ls_files(normalized: str) -> list[str]:
    """Find package dirs by git ls-files matching normalized/__init__.py."""
    suffix = f"/{normalized}/__init__.py"
    matches = [p for p in git_ls_files() if p.endswith(suffix)]
    return sorted({str(Path(m).parent) for m in matches})


def _raise_ambiguous(value: str, normalized: str, unique_dirs: list[str]) -> None:
    """Raise RuntimeError for ambiguous package resolution."""
    normalized_dirs = [d.replace("\\", "/") for d in unique_dirs]
    examples = ", ".join(normalized_dirs[:5])
    all_matches = "\n".join(f"- {d}" for d in normalized_dirs)
    raise RuntimeError(
        f"Package '{value}' is ambiguous; found multiple matches: {examples}.\n"
        f"Pass a more specific package path, for example one of:\n{all_matches}\n"
        f"Tip: dotted paths are supported (e.g. 'data_pipelines.dags.{Path(normalized).name}')."
    )


def resolve_package_dir(value: str) -> Path:
    """Resolve a package name or path (e.g. 'abc', 'src/abc', 'abc.def') to a directory."""
    normalized = normalize_package_value(value)
    if not normalized:
        raise ValueError("Package must be a non-empty string.")
    cand = _try_candidate_dirs(normalized)
    if cand is not None:
        return cand
    unique_dirs = _resolve_via_ls_files(normalized)
    if len(unique_dirs) == 1:
        return Path(unique_dirs[0])
    if len(unique_dirs) > 1:
        _raise_ambiguous(value, normalized, unique_dirs)
    raise RuntimeError(
        f"Could not resolve package '{value}'. Provide a package name or a package path "
        f"(e.g. '{normalized}' or 'src/{normalized}')."
    )
