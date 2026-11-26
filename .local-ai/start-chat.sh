#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
case "${1:-}" in
    4k) export LOCAL_AI_CONTEXT=4096 ;;
    8k) export LOCAL_AI_CONTEXT=8192 ;;
    "") ;;
    *) printf 'Usage: sh %s [4k|8k]\n' "$0" >&2; exit 2 ;;
esac

python_bin=${LOCAL_AI_PYTHON:-python3}
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf 'Python 3.10+ is required. Set LOCAL_AI_PYTHON to its executable.\n' >&2
    exit 1
fi
exec "$python_bin" -E "$script_dir/../server/compact_chat.py"
