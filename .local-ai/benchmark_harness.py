import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.error import HTTPError
import uuid
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASES = [
    ("simple", "What is 14 * 6? Answer with the number only.", r"^84\.?$", False),
    ("irrelevant_history", "What port does our Glacier service use? Answer with the number only.", r"\b9467\b", True),
    ("long_history", "What exact backup label did I specify for Northstar? Reply with the label.", r"\bRAVEN-42\b", True),
    ("multi_step", "A service processes 120 jobs in 5 minutes. At the same rate, how many minutes to process 384 jobs? Show the calculation.", r"\b16\b", False),
    ("coding", "Give Python code to order values descending using sorted, without mutating values.", r"sorted\s*\(\s*[A-Za-z_]\w*\s*,\s*reverse\s*=\s*True\s*\)", False),
    ("math", "If x + y = 19 and x - y = 5, derive x and y. Give both values.", r"\b12\b[\s\S]*\b7\b|\b7\b[\s\S]*\b12\b", False),
]


def load(directory, name, database, backend_url):
    original = sys.modules.pop("chat_memory", None)
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(name, directory / "compact-chat.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("chat_memory", None)
        if original:
            sys.modules["chat_memory"] = original
        sys.path.pop(0)
    module.BACKEND = backend_url
    module.MEMORY = module.ChatMemory(database)
    backend = module.backend
    records = []

    def measured(path, payload):
        if path != "/v1/chat/completions":
            return backend(path, payload)
        response = backend(path, {**payload, "seed": 19, "cache_prompt": False})
        records.append(response.get("usage", {}))
        return response

    module.backend = measured
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.ChatHandler)
    module.UI_HOST = f"127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return module, server, records


def request(host, path, data):
    req = urllib.request.Request(
        f"http://{host}/{path}", json.dumps(data).encode(), {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def run_case(module, usages, case):
    name, prompt, expected, long_history = case
    conversation = str(uuid.uuid4())
    if long_history:
        module.MEMORY.remember(conversation, str(uuid.uuid4()),
                               "Remember Northstar backup label RAVEN-42 and Glacier service port 9467.",
                               "Recorded both values.", "")
        for index in range(18):
            module.MEMORY.remember(conversation, str(uuid.uuid4()),
                                   f"Wallpaper revision {index}: " + "Describes unrelated wallpaper colors. " * 20,
                                   "Desktop wallpaper change acknowledged.", "")

    offset = len(usages)
    started = time.perf_counter()
    turn = {"summary": "", "prompt": prompt, "conversation": conversation}
    try:
        # The archived browser had Think enabled by default. The new browser defaults to Auto.
        reply = request(module.UI_HOST, "answer", {**turn, "thinking": True, "mode": "auto"})
        request(module.UI_HOST, "compact", {**turn, "turn": str(uuid.uuid4()), "answer": reply["answer"]})
        completed = True
    except (OSError, ValueError):
        completed, reply = False, {}
    data = usages[offset:]
    return {
        "case": name,
        "correct": bool(re.search(expected, reply.get("answer", ""), re.I)),
        "completed": completed,
        "seconds": round(time.perf_counter() - started, 3),
        "calls": len(data),
        "input_tokens": sum(item.get("prompt_tokens", 0) for item in data),
        "generated_tokens": sum(item.get("completion_tokens", 0) for item in data),
        "answer": reply.get("answer", ""),
    }


def validate_live(module):
    conversation = str(uuid.uuid4())
    prompt = "Remember this project's service must bind to port 9467. Say OK."
    request(module.UI_HOST, "compact", {
        "summary": "", "conversation": conversation, "turn": str(uuid.uuid4()),
        "prompt": prompt, "answer": "OK.",
    })
    state = module.MEMORY.state(conversation)
    assert "9467" in json.dumps(state), state
    try:
        request(module.UI_HOST, "answer", {"summary": "", "prompt": "word " * 5000, "mode": "quick"})
    except HTTPError as error:
        assert error.code == 400 and b"input budget" in error.read()
    else:
        raise AssertionError("Oversized current prompt was not rejected.")
    print("Live validation passed for structured task persistence and oversized prompt handling.", flush=True)


def main():
    os.environ["LOCAL_AI_CONTEXT"] = "4096"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark-results.json")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--variant", choices=("baseline", "optimised"))
    args = parser.parse_args()
    backend_url = f"http://127.0.0.1:{args.port}"
    with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryFile() as log:
        temp = Path(temp)
        baseline = temp / "baseline"
        baseline.mkdir()
        with zipfile.ZipFile(ROOT / "benchmark-baseline.zip") as archive:
            for name in ("compact-chat.py", "chat_memory.py"):
                (baseline / name).write_bytes(archive.read(name))
        process = subprocess.Popen([
            str(ROOT / "runner/llama-server.exe"), "-m", str(ROOT / "Qwen3-4B-Q4_K_M.gguf"),
            "--alias", "qwen-coder", "--host", "127.0.0.1", "--port", str(args.port),
            "--device", "Vulkan0", "--gpu-layers", "28", "--ctx-size", "4096", "--parallel", "1",
            "--jinja", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0", "--flash-attn", "on",
            "--batch-size", "256", "--ubatch-size", "128", "--reasoning-budget", "640",
            "--no-context-shift", "--no-cache-prompt",
        ], stdout=log, stderr=log, env={key: value for key, value in os.environ.items()
                                      if not key.startswith("LLAMA_ARG_")})
        servers = []
        try:
            for _ in range(60):
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read().decode(errors="replace"))
                try:
                    with urllib.request.urlopen(backend_url + "/health", timeout=2) as response:
                        if json.load(response)["status"] == "ok":
                            break
                except OSError:
                    time.sleep(1)
            else:
                raise RuntimeError("Backend did not become ready.")
            variants = {}
            for label, directory in (("baseline", baseline), ("optimised", ROOT)):
                if args.variant and label != args.variant:
                    continue
                module, server, usages = load(directory, label, temp / (label + ".sqlite3"), backend_url)
                servers.append(server)
                variants[label] = (module, usages)
            results = {label: [] for label in variants}
            for index, case in enumerate(CASES):
                ordered = list(variants.items())
                if index % 2:
                    ordered.reverse()
                for label, (module, usages) in ordered:
                    row = run_case(module, usages, case)
                    results[label].append(row)
                    print(label, row["case"], row["correct"], row["seconds"], flush=True)
            if args.variant and args.output.exists():
                results = {**json.loads(args.output.read_text(encoding="utf-8")), **results}
            expected = {case[0]: case[2] for case in CASES}
            for rows in results.values():
                for row in rows:
                    row["correct"] = bool(re.search(expected[row["case"]], row["answer"], re.I))
            args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
            if "optimised" in variants:
                validate_live(variants["optimised"][0])
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            if process.poll() is None:
                process.terminate()
            process.wait()


if __name__ == "__main__":
    main()
