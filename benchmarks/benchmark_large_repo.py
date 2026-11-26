"""Run fixed-seed navigation, history, and edit tasks in a pinned large repository."""

import argparse
import ast
from contextlib import ExitStack
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import monotonic
from urllib.request import urlopen
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local-ai" / "agent-tasks" / "python-stdlib"
PIN = "6fc9bf58a755731706618355a1ec2cbb027ef428"
sys.path.insert(0, str(ROOT / "server"))
import terminal_agent as agent


NAVIGATION = [
    {"name": "unquote_plus", "prompt": "Where is unquote_plus defined in this codebase? What does it do with plus signs before decoding?",
     "path": "Lib/urllib/parse.py", "line": 780,
     "checks": [r"unquote_plus", r"Lib[/\\]urllib[/\\]parse\.py", r"plus", r"space"]},
    {"name": "with_suffix", "prompt": "Find the method in this codebase that returns a new path with a different file extension. Cite its definition.",
     "path": "Lib/pathlib.py", "line": 770,
     "checks": [r"with_suffix", r"Lib[/\\]pathlib\.py"]},
    {"name": "html_base_callback", "prompt": "Find the base parser callback in this codebase invoked for an opening HTML tag. Cite the method definition, not an override.",
     "path": "Lib/html/parser.py", "line": 430,
     "checks": [r"HTMLParser\.handle_starttag", r"Lib[/\\]html[/\\]parser\.py"]},
    {"name": "overview", "prompt": "Could you tell me about this codebase?",
     "checks": [r"CPython", r"standard library", r"network|file|path"]},
]

FILES = {
    "agent_bench_inventory.py": "def available(stock, held):\n    return stock - held\n",
    "test_agent_bench_inventory.py": (
        "import unittest\nfrom agent_bench_inventory import available\n\n"
        "class InventoryTests(unittest.TestCase):\n"
        "    def test_available_normally(self):\n        self.assertEqual(available(10, 3), 7)\n"
        "    def test_available_excess_holds(self):\n        self.assertEqual(available(2, 5), 0)\n"
    ),
    "agent_bench_reservation.py": "def available(stock, held):\n    return max(0, stock - held)\n",
    "test_agent_bench_reservation.py": (
        "import unittest\nfrom agent_bench_reservation import available\n\n"
        "class ReservationTests(unittest.TestCase):\n"
        "    def test_available_normally(self):\n        self.assertEqual(available(10, 3), 7)\n"
    ),
    "agent_bench_settings.py": "DEFAULT_TIMEOUT = 30\n",
    "test_agent_bench_settings.py": (
        "import unittest\nfrom agent_bench_settings import DEFAULT_TIMEOUT\n\n"
        "class SettingsTests(unittest.TestCase):\n"
        "    def test_default_timeout(self):\n        self.assertEqual(DEFAULT_TIMEOUT, 30)\n"
    ),
}

EDIT_TASKS = {
    "bugfix": "Fix agent_bench_inventory.py so available returns zero when held exceeds stock. Keep the public function signature.",
    "add_test": "Add a regression test to test_agent_bench_reservation.py proving available(2, 5) returns zero. Keep the existing test.",
    "two_file": "Set DEFAULT_TIMEOUT to 45 in agent_bench_settings.py and update test_agent_bench_settings.py to expect 45. Keep both names and unrelated code.",
}


def capture_functions(tree):
    return {node.name: ast.dump(node) for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")}


def make_clone(destination):
    subprocess.run(["git", "clone", "--shared", "--quiet", str(SOURCE), str(destination)],
                   check=True, stdin=subprocess.DEVNULL, timeout=60)
    for name, text in FILES.items():
        (destination / name).write_text(text, encoding="utf-8", newline="\n")


def check_fixtures():
    if not SOURCE.is_dir() or not (SOURCE / ".git").exists():
        raise SystemExit("Install the local CPython task fixture with .local-ai/agent-tasks/install.py first.")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=SOURCE, text=True)
    if revision != PIN or status:
        raise SystemExit(f"Expected clean CPython fixture {PIN}; found {revision} with status {status!r}.")
    files = agent.Workspace(SOURCE).names()
    if len(files) < 1700:
        raise SystemExit(f"Expected a large CPython workspace (at least 1,700 files); found {len(files)}.")
    for task in NAVIGATION:
        if task.get("path") and not agent.chat.references_workspace(task["prompt"]):
            raise SystemExit(f"Navigation prompt {task['name']} does not trigger workspace lookup.")
    source = (SOURCE / "Lib/urllib/parse.py").read_text(encoding="utf-8")
    if source.splitlines()[779].strip() != "def unquote_plus(string, encoding='utf-8', errors='replace'):":
        raise SystemExit("Pinned CPython symbol line does not match the answer key.")
    with tempfile.TemporaryDirectory(dir=ROOT / ".local-ai") as temporary:
        clone = Path(temporary) / "fixture"
        make_clone(clone)
        for name, text in FILES.items():
            if (clone / name).read_text(encoding="utf-8") != text:
                raise SystemExit(f"Fixture mismatch: {name}")
        result = subprocess.run([sys.executable, "-E", "-B", "-m", "unittest", "-v",
                                 "test_agent_bench_inventory"], cwd=clone, capture_output=True, text=True)
        if result.returncode == 0:
            raise SystemExit("The bug-fix fixture should fail its initial test suite.")
        if "test_available_excess_holds" not in result.stderr:
            raise SystemExit("The failing inventory boundary test did not run.")
        for module in ("test_agent_bench_reservation", "test_agent_bench_settings"):
            result = subprocess.run([sys.executable, "-E", "-B", "-m", "unittest", "-v", module],
                                    cwd=clone, capture_output=True, text=True)
            if result.returncode:
                raise SystemExit(f"The {module} fixture should pass before editing: {result.stderr}")
    print(f"Fixture checks passed: CPython {revision[:8]}, {len(files)} tracked workspace files, edit tasks isolated.")


def runtime(output, cleanup):
    try:
        with urlopen(agent.chat.BACKEND + "/health", timeout=2) as response:
            existing = json.load(response).get("status") == "ok"
    except OSError:
        existing = False
    process = None
    if not existing:
        args = agent.runner_arguments(agent.chat.RUNTIME_DIR, alias=agent.chat.MODEL, port=8080, context=4096,
                                      thinking=agent.limits.THINK, cache_ram=agent.limits.CACHE_RAM)
        log = cleanup.enter_context((output.parent / "runner.log").open("wb"))
        process = subprocess.Popen([*args, "--no-webui"], stdout=log, stderr=subprocess.STDOUT,
                                   **agent.process_options())
        cleanup.callback(agent.stop_runner, process)
    if agent.runner_context(process) != 4096:
        raise SystemExit("This benchmark needs a 4,096-token runner. Stop it or restart it at 4K.")
    agent.chat.CONTEXT_SIZE = agent.limits.CONTEXT = 4096


class Trial:
    def __init__(self, workspace, name, seed, report):
        self.workspace = workspace
        self.client = agent.Session(workspace, [sys.executable, "-E", "-B", "-m", "unittest", "-v"],
                                    agent.ChatMemory(report.parent / f"{name}.sqlite3"), name)
        self.seed = seed
        self.calls = []
        self.searches = []
        self.original_complete = agent.chat.complete
        self.original_backend = agent.chat.backend
        self.original_search = workspace.search
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(agent.chat, "complete", self.observe))
        self.stack.enter_context(patch.object(agent.chat, "backend", self.backend))
        self.stack.enter_context(patch.object(workspace, "search", self.search))

    def observe(self, messages, **kwargs):
        result, metrics = self.original_complete(messages, **kwargs)
        self.calls.append({"input_tokens": metrics["prompt_tokens"],
                           "generated_tokens": metrics["generated_tokens"],
                           "prompt": [message.get("content", "") for message in messages],
                           "response": result.get("message", {}).get("content", "")})
        return result, metrics

    def backend(self, path, payload):
        if path == "/v1/chat/completions":
            payload = {**payload, "seed": self.seed, "cache_prompt": False}
        return self.original_backend(path, payload)

    def search(self, query, **kwargs):
        started = monotonic()
        result = self.original_search(query, **kwargs)
        self.searches.append({"query": query, "hits": [item for item, _ in result],
                              "elapsed_ms": round((monotonic() - started) * 1000)})
        return result

    def close(self):
        self.stack.close()

    def run(self, prompt):
        start = monotonic()
        answer = self.client.run(prompt)["output"]
        return {"prompt": prompt, "answer": answer,
                "seconds": round(monotonic() - start, 3),
                "calls": len(self.calls), "input_tokens": sum(c["input_tokens"] for c in self.calls),
                "generated_tokens": sum(c["generated_tokens"] or 0 for c in self.calls),
                "search_ms": self.searches[-1].get("elapsed_ms") if self.searches else None,
                "retrieval": self.searches[-1]["hits"] if self.searches else []}


def citation_pass(task, answer):
    content_pass = all(re.search(pattern, answer, re.I) for pattern in task["checks"])
    if task.get("line") is None:
        location_pass = True
    else:
        path = re.search(task["checks"][1], answer, re.I)
        around = answer[max(0, path.start() - 100):path.end() + 100] if path else ""
        location_pass = re.search(rf"(?:line\s*{task['line']}\b|:{task['line']}\b)", around, re.I) is not None
    return content_pass and location_pass


def navigation_trials(workspace, folder, seed, output):
    rows = []
    for task in NAVIGATION:
        trial = Trial(workspace, f"{seed}-nav-{task['name']}", seed, output)
        result = trial.run(task["prompt"])
        target_found = False
        if task.get("path"):
            target_found = any(
                hit["name"] == task["path"] and
                (hit.get("definition_line") == task["line"] or
                 re.search(rf"(?m)^{task['line']} \|", hit.get("text", "")))
                for hit in result["retrieval"]
            )
        result.update({"task": task["name"], "passed": citation_pass(task, result["answer"]),
                       "target_in_top_three": target_found})
        rows.append(result)
        trial.close()
    return rows


def history_trial(workspace, seed, output):
    trial = Trial(workspace, f"{seed}-history", seed, output)
    trial.client.remember("For the CPython repository migration, record release label PINECONE-57.",
                          "Recorded release label PINECONE-57.")
    for index in range(4):
        trial.client.remember(f"Unrelated packaging discussion number {index}.", "The package uses wheels.")
    result = trial.run("What release label did we record for the CPython repository migration?")
    result.update({"task": "history", "passed": "PINECONE-57" in result["answer"]})
    trial.close()
    return result


def test_command(*names):
    return [sys.executable, "-E", "-B", "-m", "unittest", "-v", *names]


def edit_trial(workspace, seed, output, task_name):
    prompt = EDIT_TASKS[task_name]
    trial = Trial(workspace, f"{seed}-edit-{task_name}", seed, output)
    test_module = {
        "bugfix": "test_agent_bench_inventory",
        "add_test": "test_agent_bench_reservation",
        "two_file": "test_agent_bench_settings",
    }[task_name]
    command = test_command(test_module)
    baseline = subprocess.run(command, cwd=workspace.root, capture_output=True, text=True)
    steps = [(prompt, None)]
    if task_name == "two_file":
        steps = [("Set DEFAULT_TIMEOUT to 45 in agent_bench_settings.py.", "agent_bench_settings.py"),
                 ("Update test_agent_bench_settings.py to expect DEFAULT_TIMEOUT to be 45; keep its existing test.",
                  "test_agent_bench_settings.py")]
    proposals = []
    started = monotonic()
    for step, expected_file in steps:
        response = trial.client.run("/edit " + step)["output"]
        pending = trial.client.pending
        valid = bool(pending and pending.name in step_files(task_name) and
                     (expected_file is None or pending.name == expected_file))
        proposals.append({"step": step, "valid": valid, "response": response,
                          "path": pending.name if pending else None,
                          "diff": pending.diff if pending else None})
        if not valid:
            break
        trial.client.apply(pending.id)
    suite = subprocess.run(command, cwd=workspace.root, capture_output=True, text=True)
    retry_output = None
    if suite.returncode and proposals and all(row["valid"] for row in proposals):
        trial.client.last_task = steps[-1][0]
        trial.client.last_failure = suite.stderr[-2400:] or suite.stdout[-2400:]
        retry_output = trial.client.run("/retry")["output"]
        pending = trial.client.pending
        if pending and pending.name in step_files(task_name):
            trial.client.apply(pending.id)
            suite = subprocess.run(command, cwd=workspace.root, capture_output=True, text=True)
    passed = bool(proposals and all(row["valid"] for row in proposals) and suite.returncode == 0)
    if task_name == "bugfix":
        passed = passed and (workspace.root / "agent_bench_inventory.py").read_text(encoding="utf-8").strip() != FILES["agent_bench_inventory.py"].strip()
    elif task_name == "add_test":
        original = capture_functions(ast.parse(FILES["test_agent_bench_reservation.py"]))
        updated = capture_functions(ast.parse((workspace.root / "test_agent_bench_reservation.py").read_text(encoding="utf-8")))
        passed = passed and all(updated.get(name) == body for name, body in original.items()) and len(updated) == 2
        if passed:
            path = workspace.root / "agent_bench_reservation.py"
            good = path.read_bytes()
            try:
                path.write_text(FILES["agent_bench_reservation.py"].replace("max(0, stock - held)", "stock - held"), encoding="utf-8")
                mutated = subprocess.run(command, cwd=workspace.root, capture_output=True, text=True)
                passed = mutated.returncode != 0 and "test_available_excess_holds" in mutated.stderr
            finally:
                path.write_bytes(good)
    elif task_name == "two_file":
        passed = passed and (workspace.root / "agent_bench_settings.py").read_text(encoding="utf-8").strip() == "DEFAULT_TIMEOUT = 45" and \
            "DEFAULT_TIMEOUT, 45" in (workspace.root / "test_agent_bench_settings.py").read_text(encoding="utf-8")
    result = {"task": task_name, "prompt": prompt, "baseline_passed": baseline.returncode == 0,
              "proposals": proposals, "passed": passed, "retry": retry_output, "suite_output": suite.stderr[-2500:],
              "seconds": round(monotonic() - started, 3), "model_calls": len(trial.calls),
              "input_tokens": sum(c["input_tokens"] for c in trial.calls),
              "generated_tokens": sum(c["generated_tokens"] or 0 for c in trial.calls),
              "calls": trial.calls}
    trial.close()
    return result


def step_files(task):
    return {
        "bugfix": {"agent_bench_inventory.py"},
        "add_test": {"test_agent_bench_reservation.py"},
        "two_file": {"agent_bench_settings.py", "test_agent_bench_settings.py"},
    }[task]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--case", action="append", choices=["navigation", "history", *EDIT_TASKS])
    parser.add_argument("--output", type=Path, default=ROOT / ".local-ai" / "large-benchmark" / "results.json")
    parser.add_argument("--check-fixtures", action="store_true", help="Validate the pinned repository and tasks without model inference.")
    args = parser.parse_args()
    check_fixtures()
    if args.check_fixtures:
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    seeds = args.seed or [7, 19, 42]
    cases = args.case or ["navigation", "history", *EDIT_TASKS]
    report = {"repository": str(SOURCE), "revision": PIN, "base_files": len(agent.Workspace(SOURCE).names()),
              "context": 4096, "seeds": seeds, "cases": cases, "cache_prompt": False, "runs": []}

    def save():
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary, ExitStack() as cleanup:
        runtime(args.output, cleanup)
        for seed in seeds:
            clone = Path(temporary) / f"repo-{seed}"
            make_clone(clone)
            workspace = agent.Workspace(clone)
            row = {"seed": seed, "workspace_files": len(workspace.names()), "navigation": [], "edits": []}
            if "navigation" in cases:
                row["navigation"] = navigation_trials(workspace, Path(temporary), seed, args.output)
            if "history" in cases:
                row["history"] = history_trial(workspace, seed, args.output)
            for task in EDIT_TASKS:
                if task in cases:
                    result = edit_trial(workspace, seed, args.output, task)
                    row["edits"].append(result)
                    print(f"seed {seed} {task}: {'PASS' if result['passed'] else 'FAIL'} ({result['model_calls']} calls)", flush=True)
            report["runs"].append(row)
            save()
    report["summary"] = {
        "navigation_passed": sum(item["passed"] for row in report["runs"] for item in row["navigation"]),
        "navigation_attempts": sum(len(row["navigation"]) for row in report["runs"]),
        "retrieval_hits": sum(item["target_in_top_three"] for row in report["runs"] for item in row["navigation"] if "target_in_top_three" in item),
        "history_passed": sum(row["history"]["passed"] for row in report["runs"] if "history" in row),
        "history_attempts": sum("history" in row for row in report["runs"]),
        "edits_passed": sum(item["passed"] for row in report["runs"] for item in row["edits"]),
        "edit_attempts": sum(len(row["edits"]) for row in report["runs"]),
    }
    save()
    print(f"Results saved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
