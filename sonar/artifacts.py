from __future__ import annotations

import shutil
from pathlib import Path


def snapshot_sonar_artifacts() -> dict[str, bool]:
    paths = [Path(".sonar"), Path(".scannerwork"), Path(".ruff_cache")]
    return {str(p): p.exists() for p in paths}


def cleanup_sonar_artifacts(snapshot: dict[str, bool]) -> None:
    for path_str, existed in snapshot.items():
        if existed:
            continue

        path = Path(path_str)
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
