from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def posix(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def truncate(text: str, *, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return (
        text[:keep_head].rstrip()
        + "\n\n... (diff truncated) ...\n\n"
        + text[-keep_tail:].lstrip()
    )


def file_line_count(path: str) -> int:
    try:
        return len(
            Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except Exception:
        return 1


def safe_slug(path: str, *, max_length: int = 120) -> str:
    cleaned = path.replace("\\", "/").strip("/")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("_")
    if not slug:
        slug = "file"
    if len(slug) > max_length:
        digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
        slug = f"{slug[: max_length - 11]}_{digest}"
    return slug
