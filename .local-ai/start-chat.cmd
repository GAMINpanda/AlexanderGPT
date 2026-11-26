@echo off
setlocal
if /I "%~1"=="coder" goto coder
if /I "%~1"=="4k" set "LOCAL_AI_CONTEXT=4096"
if /I "%~1"=="8k" set "LOCAL_AI_CONTEXT=8192"
python -E "%~dp0..\server\compact_chat.py"
exit /b %errorlevel%

:coder
echo Open http://127.0.0.1:8080 once the model loads. Press Ctrl+C to stop.
"%~dp0runner\llama-server.exe" --model "%~dp0qwen2.5-coder-3b-instruct-q4_k_m.gguf" --alias qwen-coder --host 127.0.0.1 --port 8080 --cors-origins localhost --device Vulkan0 --gpu-layers 99 --ctx-size 4096 --parallel 1
