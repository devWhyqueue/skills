#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../../.." && pwd)

if command -v uv >/dev/null 2>&1; then
  UV_BIN=$(command -v uv)
elif [[ -x /home/yannik/.local/bin/uv ]]; then
  UV_BIN=/home/yannik/.local/bin/uv
else
  echo "uv is required but was not found." >&2
  exit 1
fi

VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  "${UV_BIN}" venv "${REPO_ROOT}/.venv"
fi

"${UV_BIN}" sync \
  --project "${REPO_ROOT}" \
  --locked \
  --no-install-project \
  --python "${VENV_PYTHON}"

exec "${VENV_PYTHON}" "${REPO_ROOT}/.skills/pdf/scripts/compress_pdfs.py" "$@"
