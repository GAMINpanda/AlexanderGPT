import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def runner_location(runtime_dir):
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    configured = os.environ.get("LOCAL_AI_LLAMA_SERVER")
    bundled = runtime_dir / "runner" / name
    candidates = [configured] if configured else [str(bundled), name]
    for candidate in candidates:
        executable = shutil.which(os.path.expanduser(candidate))
        if executable:
            return str(Path(executable).absolute())
    raise ValueError(
        f"Could not find an executable {name}. Install a compatible llama.cpp build, "
        f"place its runner in {bundled.parent}, or set LOCAL_AI_LLAMA_SERVER."
    )


def runner_arguments(runtime_dir, *, alias, port, context, thinking, cache_ram=None, cache_prompt=True):
    windows = sys.platform == "win32"
    apple_silicon = sys.platform == "darwin" and platform.machine().casefold() == "arm64"
    model = Path(os.environ.get("LOCAL_AI_MODEL", runtime_dir / "Qwen3-4B-Q4_K_M.gguf")).expanduser()
    if not model.is_file():
        raise ValueError(f"Model file missing: {model}. Place the GGUF there or set LOCAL_AI_MODEL.")

    layers = os.environ.get("LOCAL_AI_GPU_LAYERS", "28" if windows else "auto" if apple_silicon else "0")
    device = os.environ.get("LOCAL_AI_DEVICE", "Vulkan0" if windows and layers != "0" else "")
    kv = os.environ.get("LOCAL_AI_KV", "q8_0" if windows and layers != "0" else "f16")
    flash = os.environ.get("LOCAL_AI_FLASH", "on" if windows and layers != "0" else "auto")
    args = [
        runner_location(runtime_dir), "--model", str(model.absolute()),
        "--alias", alias, "--host", "127.0.0.1", "--port", str(port),
        "--cors-origins", "localhost", "--gpu-layers", layers,
        "--ctx-size", str(context), "--parallel", "1", "--jinja",
        "--cache-type-k", kv, "--cache-type-v", kv, "--flash-attn", flash,
        "--batch-size", "256", "--ubatch-size", "128",
        "--reasoning-budget", str(thinking), "--no-context-shift",
    ]
    if device:
        args += ["--device", device]
    if cache_ram is not None:
        args += ["--cache-ram", str(cache_ram)]
    if not cache_prompt:
        args.append("--no-cache-prompt")
    return args


def process_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_runner(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
