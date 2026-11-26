@echo off
setlocal
set "PYTHONPATH="
set "LITELLM_LOCAL_MODEL_COST_MAP=True"
"%~dp0aider-env\Scripts\aider.exe" --openai-api-base http://127.0.0.1:8080/v1 --openai-api-key local --model openai/qwen-coder --weak-model openai/qwen-coder --edit-format whole --map-tokens 0 --no-auto-commits --no-analytics --no-check-update %*
