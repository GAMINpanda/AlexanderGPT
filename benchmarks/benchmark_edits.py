"""Reproducible 4K edit benchmark with isolated workspaces and evidence controls."""

import argparse
import ast
from contextlib import ExitStack
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic
from unittest.mock import patch
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import terminal_agent as agent


PARCEL = {
    "billing.py": '''def invoice_total(subtotal_cents, dispatch_cents):
    if subtotal_cents < 0 or dispatch_cents < 0:
        raise ValueError("Amounts must be non-negative")
    return subtotal_cents - dispatch_cents
''',
    "dispatch.py": '''ZONE_PRICE = {"local": 250, "regional": 475, "remote": 800}


def quote_dispatch(parcel_count, zone):
    """Return the charge in cents for the parcels in this quote."""
    if parcel_count < 1:
        raise ValueError("At least one parcel is required")
    if zone not in ZONE_PRICE:
        raise ValueError("Unknown zone")
    return ZONE_PRICE[zone] * parcel_count
''',
    "test_parcel.py": '''import unittest
from billing import invoice_total
from dispatch import quote_dispatch


class ParcelTests(unittest.TestCase):
    def test_invoice(self):
        self.assertEqual(invoice_total(2000, 250), 2250)

    def test_negative_invoice(self):
        with self.assertRaises(ValueError):
            invoice_total(-1, 250)

    def test_regional_quote(self):
        self.assertEqual(quote_dispatch(2, "regional"), 950)

    def test_invalid_zone(self):
        with self.assertRaises(ValueError):
            quote_dispatch(1, "other")
''',
}
RESERVATIONS = {
    "inventory.py": '''def available(stock, held):
    if stock < 0 or held < 0:
        raise ValueError("Counts must be non-negative")
    return max(0, stock - held)


def can_reserve(stock, held, requested):
    if requested < 1:
        raise ValueError("Request must be positive")
    return requested < available(stock, held)
''',
    "report.py": '''from inventory import available


def stock_report(stock, held):
    return {"remaining": available(stock, held), "on_hold": held}
''',
    "test_inventory.py": '''import unittest
from inventory import available, can_reserve
from report import stock_report


class InventoryTests(unittest.TestCase):
    def test_can_reserve(self):
        self.assertTrue(can_reserve(10, 3, 4))

    def test_declines_oversell(self):
        self.assertFalse(can_reserve(10, 3, 8))

    def test_stock_report(self):
        self.assertEqual(stock_report(10, 3), {"remaining": 7, "on_hold": 3})
''',
}


@dataclass(frozen=True)
class Case:
    name: str
    repository: str
    fixture: dict
    prompt: str
    target: str
    supporting: tuple
    check: str
    old: str
    new: str
    tests: int = 0
    mutation: tuple = ()


CASES = (
    Case("billing", "parcel", PARCEL,
         "Fix invoice_total in billing.py so the invoice includes dispatch. Keep validation and tests unchanged.",
         "billing.py", ("test_parcel.py",),
         "from billing import invoice_total\nassert invoice_total(500, 90) == 590\n",
         "subtotal_cents - dispatch_cents", "subtotal_cents + dispatch_cents"),
    Case("regional-discount", "parcel", PARCEL,
         "Update quote_dispatch in dispatch.py. Regional quotes with three or more parcels should receive a single 100-cent discount on the whole quote. Preserve other prices and validation.",
         "dispatch.py", ("test_parcel.py",),
         '''from dispatch import quote_dispatch
assert quote_dispatch(3, "regional") == 1325
assert quote_dispatch(4, "regional") == 1800
assert quote_dispatch(2, "regional") == 950
assert quote_dispatch(3, "local") == 750
assert quote_dispatch(3, "remote") == 2400
''',
         'return ZONE_PRICE[zone] * parcel_count',
         'total = ZONE_PRICE[zone] * parcel_count\n    return total - 100 if zone == "regional" and parcel_count >= 3 else total'),
    Case("last-stock", "reservations", RESERVATIONS,
         "Fix can_reserve in inventory.py so a request for exactly the remaining stock succeeds. Keep validation and the oversell check.",
         "inventory.py", ("test_inventory.py",),
         '''from inventory import can_reserve
assert can_reserve(10, 3, 7)
assert not can_reserve(10, 3, 8)
try:
    can_reserve(10, 3, 0)
except ValueError:
    pass
else:
    raise AssertionError("accepted a zero request")
''',
         "requested < available", "requested <= available"),
    Case("add-stock-test", "reservations", RESERVATIONS,
         "Add a regression test to test_inventory.py proving available returns zero when held exceeds stock. Keep the three existing tests.",
         "test_inventory.py", ("inventory.py",),
         "from inventory import available\nassert available(2, 5) == 0\n",
         '        self.assertEqual(stock_report(10, 3), {"remaining": 7, "on_hold": 3})',
         '        self.assertEqual(stock_report(10, 3), {"remaining": 7, "on_hold": 3})'
         '\n\n    def test_excess_holds(self):\n        self.assertEqual(available(2, 5), 0)',
         tests=4, mutation=("inventory.py", "max(0, stock - held)", "stock - held")),
)


def make_workspace(path, case):
    path.mkdir()
    fixture = dict(case.fixture)
    if case.name == "regional-discount":
        # Isolate this task from the intentionally failing billing control.
        fixture["billing.py"] = fixture["billing.py"].replace(
            "subtotal_cents - dispatch_cents", "subtotal_cents + dispatch_cents",
        )
    for name, source in fixture.items():
        (path / name).write_bytes(source.encode())
    subprocess.run(["git", "init", "-q", str(path)], check=True, stdin=subprocess.DEVNULL, timeout=15)
    return fixture


def python(root, *args):
    return subprocess.run([sys.executable, "-E", "-B", *args], cwd=root, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)


def verify(root, case, fixture):
    changed = {name for name, source in fixture.items() if (root / name).read_bytes() != source.encode()}
    if changed != {case.target}:
        return {"passed": False, "reason": "Unexpected changed files", "files": sorted(changed)}
    if case.tests:
        provider = agent.language_for_path(case.target)
        if provider is None:
            return {"passed": False, "reason": "No language provider for structural test checks"}
        previous = provider.test_functions(ast.parse(fixture[case.target]))
        current = provider.test_functions(ast.parse((root / case.target).read_text(encoding="utf-8")))
        if any(current.get(name) != body for name, body in previous.items()) or len(current) != case.tests:
            return {"passed": False, "reason": "Existing tests changed or required test missing"}
    suite = python(root, "-m", "unittest", "-v")
    hidden = python(root, "-c", case.check)
    mutation_detected = None
    if case.mutation and not suite.returncode and not hidden.returncode:
        name, old, new = case.mutation
        path = root / name
        source = path.read_bytes()
        try:
            path.write_bytes(source.replace(old.encode(), new.encode(), 1))
            mutated = python(root, "-m", "unittest", "-v")
            mutation_detected = mutated.returncode == 1 and "test_" in mutated.stderr and "AssertionError" in mutated.stderr
        finally:
            path.write_bytes(source)
    return {"passed": not suite.returncode and not hidden.returncode and mutation_detected is not False,
            "suite": suite.stderr[-4000:], "hidden": hidden.stderr[-2000:], "mutation_detected": mutation_detected}


def check_fixtures(root, cases):
    for case in cases:
        workspace = root / case.name
        fixture = make_workspace(workspace, case)
        before = python(workspace, "-c", case.check)
        if bool(before.returncode) == bool(case.tests):
            raise RuntimeError(f"{case.name}: unexpected reference baseline")
        source = fixture[case.target]
        if source.count(case.old) != 1:
            raise RuntimeError(f"{case.name}: reference patch must have one exact match")
        (workspace / case.target).write_bytes(source.replace(case.old, case.new).encode())
        if not (outcome := verify(workspace, case, fixture))["passed"]:
            raise RuntimeError(f"{case.name}: reference edit failed: {outcome}")
        print(f"{case.name}: fixture and reference edit verified", flush=True)


def attempt(folder, case, seed, oracle):
    root = folder / "workspace"
    folder.mkdir()
    fixture = make_workspace(root, case)
    workspace = agent.Workspace(root)
    history = agent.ChatMemory(folder / "history.sqlite3")
    client = agent.Session(workspace, [sys.executable, "-E", "-B", "-m", "unittest", "-v"], history, case.name)
    chat = agent.chat
    original_complete, original_backend = chat.complete, chat.backend
    original_search = workspace.search
    calls, edits = [], []

    def observe(messages, **kwargs):
        result, metrics = original_complete(messages, **kwargs)
        calls.append({"input": metrics["prompt_tokens"], "generated": metrics["generated_tokens"],
                      "source": [message["content"] for message in messages if message["role"] != "system"],
                      "proposal": result["message"].get("content", "")})
        return result, metrics

    def seeded(path, payload):
        if path == "/v1/chat/completions":
            payload = {**payload, "seed": seed, "cache_prompt": False}
        return original_backend(path, payload)

    def evidence(query, **kwargs):
        if not oracle:
            return original_search(query, **kwargs)
        rows = []
        for name in (case.target, *case.supporting):
            raw, source = workspace.read(name)
            rows.append(({"name": name, "line": 1, "text": source[:1500]}, raw))
        return rows

    def finish_proposal():
        proposal = client.pending
        if proposal is None:
            return {"passed": False, "reason": "No valid proposal"}
        if proposal.name != case.target:
            return {"passed": False, "reason": "Unexpected target", "target": proposal.name}
        edits.append(proposal.diff)
        client.apply(proposal.id)
        return verify(root, case, fixture)

    start = monotonic()
    with (
        patch.object(chat, "complete", observe),
        patch.object(chat, "backend", seeded),
        patch.object(workspace, "search", evidence),
    ):
        initial = client.run("/edit " + case.prompt)["output"]
        first_valid = len(calls) == 1 and client.pending is not None and client.pending.name == case.target
        initial_result = finish_proposal()
        result, retry = initial_result, None
        if edits and not result["passed"]:
            client.last_failure = (result.get("suite", "") + "\n" + result.get("hidden", "")).strip()[-2400:]
            if client.last_failure:
                retry = client.run("/retry")["output"]
                result = finish_proposal()
    input_tokens = sum(call["input"] for call in calls)
    generated_tokens = sum(call["generated"] or 0 for call in calls)
    return {"case": case.name, "repository": case.repository, "seed": seed, "variant": "oracle" if oracle else "agent",
            "first_proposal_valid": first_valid, "initial_edit_passed": initial_result["passed"],
            "first_proposal_verified": first_valid and initial_result["passed"],
            "passed": result["passed"], "input_tokens": input_tokens, "generated_tokens": generated_tokens,
            "tokens_per_verified_fix": input_tokens + generated_tokens if result["passed"] else None,
            "seconds": round(monotonic() - start, 3), "model_calls": len(calls),
            "initial": initial, "initial_result": initial_result, "retry": retry, "result": result,
            "diffs": edits, "calls": calls}


def lookup_check(folder, seed):
    case = CASES[0]
    make_workspace(folder, case)
    workspace = agent.Workspace(folder)
    client = agent.Session(workspace, None, agent.ChatMemory(folder / ".history.sqlite3"), "lookup")
    backend = agent.chat.backend

    def seeded(path, payload):
        return backend(path, {**payload, "seed": seed, "cache_prompt": False}
                       if path == "/v1/chat/completions" else payload)

    with patch.object(agent.chat, "backend", seeded):
        output = client.run("Where is invoice_total defined in this codebase?")["output"]
    return {"seed": seed, "passed": "billing.py" in output and ("billing.py:1" in output or "line 1" in output),
            "output": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[case.name for case in CASES])
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / ".local-ai" / "edit-benchmark" / "results.json")
    parser.add_argument("--check-fixtures", action="store_true", help="Check reference patches without loading a model.")
    parser.add_argument("--no-oracle", action="store_true", help="Skip supplied-evidence controls for failed edits.")
    args = parser.parse_args()
    cases = [case for case in CASES if not args.case or case.name in args.case]
    seeds = args.seed or [7, 19, 42]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as directory, ExitStack() as cleanup:
        work = Path(directory)
        fixture_check = work / "fixtures"
        fixture_check.mkdir()
        check_fixtures(fixture_check, cases)
        if args.check_fixtures:
            return
        process = None
        try:
            with urlopen(agent.chat.BACKEND + "/health", timeout=2) as response:
                existing = json.load(response)["status"] == "ok"
        except OSError:
            existing = False
        if not existing:
            runner = agent.runner_arguments(agent.chat.RUNTIME_DIR, alias=agent.chat.MODEL, port=8080, context=4096,
                                            thinking=agent.limits.THINK, cache_ram=agent.limits.CACHE_RAM)
            log = cleanup.enter_context((args.output.parent / "runner.log").open("wb"))
            process = subprocess.Popen([*runner, "--no-webui"], stdout=log, stderr=subprocess.STDOUT,
                                       **agent.process_options())
            cleanup.callback(agent.stop_runner, process)
        runner_context = agent.runner_context(process)
        if runner_context != 4096:
            raise SystemExit("This comparison requires a 4,096-token runner. Stop the active runner or restart it at 4K.")
        agent.chat.CONTEXT_SIZE = agent.limits.CONTEXT = 4096
        report = {"context": 4096, "reply_tokens": agent.limits.REPLY, "seeds": seeds, "cache_prompt": False,
                  "reused_runner": existing, "lookups": [], "edits": []}

        def save():
            args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        for index, seed in enumerate(seeds):
            report["lookups"].append(lookup_check(work / f"lookup-{index}", seed))
            save()
            for case in cases:
                row = attempt(work / f"{index}-{case.name}", case, seed, oracle=False)
                report["edits"].append(row)
                print(f"{case.name} seed {seed}: {'PASS' if row['passed'] else 'FAIL'} ({row['model_calls']} calls)",
                      flush=True)
                save()
                if not row["passed"] and not args.no_oracle:
                    report["edits"].append(attempt(work / f"{index}-{case.name}-oracle", case, seed, oracle=True))
                    save()
        normal = [row for row in report["edits"] if row["variant"] == "agent"]
        report["summary"] = {key: sum(row[key] for row in normal)
                             for key in ("first_proposal_valid", "first_proposal_verified", "passed")}
        report["summary"]["attempts"] = len(normal)
        save()
    print(f"Results saved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
