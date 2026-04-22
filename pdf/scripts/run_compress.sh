#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPRESS_SCRIPT="${SCRIPT_DIR}/compress_pdfs.py"

if [[ ! -f "${COMPRESS_SCRIPT}" ]]; then
  echo "compress_pdfs.py was not found next to run_compress.sh" >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run --with pikepdf --with pillow python "${COMPRESS_SCRIPT}" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "${COMPRESS_SCRIPT}" "$@"
fi

echo "Either uv or python3 is required but was not found." >&2
exit 1
