#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
aider="$script_dir/aider-env/bin/aider"
if [ ! -x "$aider" ]; then
    if ! aider=$(command -v aider); then
        printf 'Install Aider on PATH or in .local-ai/aider-env.\n' >&2
        exit 1
    fi
fi
unset PYTHONPATH
export LITELLM_LOCAL_MODEL_COST_MAP=True
exec "$aider" --openai-api-base http://127.0.0.1:8080/v1 --openai-api-key local \
    --model openai/qwen-coder --weak-model openai/qwen-coder --edit-format whole \
    --map-tokens 0 --no-auto-commits --no-analytics --no-check-update "$@"
