from __future__ import annotations

from pathlib import Path
from typing import Optional

from git import ls_files


def find_package_root(path: Path) -> Optional[Path]:
    cur = path.parent
    while cur != cur.parent:
        if (cur / "__init__.py").exists():
            return cur
        cur = cur.parent
    return None


def derive_scope_from_files(files: list[str]) -> str:
    scopes: list[str] = []

    for f in files:
        p = Path(f)
        parts = p.parts

        if len(parts) >= 2 and parts[0] == "src":
            scopes.append(parts[1])
            continue

        pkg_root = find_package_root(p)
        if pkg_root is not None:
            scopes.append(pkg_root.name)
            continue

        if len(parts) >= 2:
            scopes.append(parts[0])
        else:
            scopes.append("core")

    unique = sorted(set(s for s in scopes if s))
    if not unique:
        return "core"
    if len(unique) == 1:
        return unique[0]
    return "multi"


def normalize_package_value(value: str) -> str:
    v = (value or "").strip()
    v = v.replace("\\", "/")
    v = v.strip("/")
    v = v.replace(".", "/")
    return v


def git_ls_files() -> list[str]:
    return ls_files()


def resolve_package_dir(value: str) -> Path:
    """
    Resolve a user-provided package value into a directory path.

    Supported values:
    - "abc" (package name)
    - "src/abc" (path)
    - "abc.def" (dotted path => "abc/def")
    """
    normalized = normalize_package_value(value)
    if not normalized:
        raise ValueError("Package must be a non-empty string.")

    candidates: list[Path] = [Path(normalized)]
    if not normalized.startswith("src/"):
        candidates.append(Path("src") / Path(normalized))

    for cand in candidates:
        if cand.exists() and cand.is_dir():
            return cand

    suffix = f"/{normalized}/__init__.py"
    matches = [p for p in git_ls_files() if p.endswith(suffix)]
    unique_dirs = sorted({str(Path(m).parent) for m in matches})

    if len(unique_dirs) == 1:
        return Path(unique_dirs[0])
    if len(unique_dirs) > 1:
        examples = ", ".join(d.replace("\\", "/") for d in unique_dirs[:5])
        all_matches = "\n".join(f"- {d.replace('\\', '/')}" for d in unique_dirs)
        raise RuntimeError(
            f"Package '{value}' is ambiguous; found multiple matches: {examples}.\n"
            f"Pass a more specific package path, for example one of:\n{all_matches}\n"
            f"Tip: dotted paths are supported (e.g. 'data_pipelines.dags.{Path(normalized).name}')."
        )

    raise RuntimeError(
        f"Could not resolve package '{value}'. Provide a package name or a package path "
        f"(e.g. '{normalized}' or 'src/{normalized}')."
    )
