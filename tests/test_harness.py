import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SERVER_DIR = pathlib.Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import compact_chat as chat
import harness_context as context
import llama_runtime as runtime
import languages
import terminal_agent as agent
from chat_memory import ChatMemory
from local_files import is_local_absolute, read_shared_file, validate_excerpts


class TerminalAgentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.source = self.root / "pricing.py"
        self.original = b"def discount_price(price, discount):\r\n    return price + discount\r\n"
        self.source.write_bytes(self.original)
        self.memory = ChatMemory(self.root / ".agent-test.sqlite3")
        self.session = agent.Session(agent.Workspace(self.root), None, self.memory, "test")
        self.hits = [({"name": self.source.name, "line": 1,
                       "text": self.original.decode().replace("\r\n", "\n")}, self.original)]

    def test_language_registry_selects_python_provider_and_leaves_unknown_files_generic(self):
        self.assertIsInstance(languages.for_path("src/pricing.py"), languages.PythonLanguage)
        self.assertIsInstance(languages.for_path("types.pyi"), languages.PythonLanguage)
        self.assertIsNone(languages.for_path("src/app.js"))

    def test_unregistered_language_keeps_generic_line_edit_path(self):
        source = b"export const amount = 1;\n"
        hits = [({"name": "app.js", "line": 1, "text": source.decode()}, source)]
        reply = {"message": {"content": json.dumps({
            "path": "app.js", "start": 1, "end": 1,
            "new": "export const amount = 2;", "note": "Update amount.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(reply, {})):
            self.session.propose("Update app.js.", hits, "")
        self.assertEqual(self.session.pending.updated, b"export const amount = 2;\n")

    def test_repository_lookup_retries_uncited_answers_with_one_source(self):
        hit = ({"name": "pricing.py", "line": 1, "text": self.original.decode().replace("\r\n", "\n")}, self.original)
        answers = [
            {"answer": "This is probably a Java discount handler."},
            {"answer": "discount_price is defined at pricing.py:1."},
        ]
        with patch.object(self.session.workspace, "search", return_value=[hit]), \
             patch.object(chat, "run_research", return_value={"evidence": [], "notes": "", "warning": ""}), \
             patch.object(chat, "select_answer", side_effect=answers) as select:
            result = self.session.run("Find the discount_price function in this codebase.")
        self.assertEqual(select.call_count, 2)
        self.assertIn("pricing.py:1", result["output"])

    def test_repository_lookup_falls_back_to_source_pointer_if_retry_is_ungrounded(self):
        hit = ({"name": "pricing.py", "line": 1, "text": self.original.decode().replace("\r\n", "\n"),
                "definition": "discount_price", "definition_line": 1, "language": "Python"}, self.original)
        answers = [{"answer": "An unrelated answer."}, {"answer": "Still no source citation."}]
        with patch.object(self.session.workspace, "search", return_value=[hit]), \
             patch.object(chat, "run_research", return_value={"evidence": [], "notes": "", "warning": ""}), \
             patch.object(chat, "select_answer", side_effect=answers):
            result = self.session.run("Find the discount_price function in this codebase.")
        self.assertIn("discount_price at pricing.py:1", result["output"])

    def propose(self, name="pricing.py"):
        reply = {"message": {"content": json.dumps({
            "path": name, "start": 2, "end": 2, "new": "    return price - discount", "note": "Fix discount.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), patch.object(chat, "complete", return_value=(reply, {})):
            return self.session.propose("Fix discount_price.", self.hits, "")

    def test_edits_require_matching_approval_and_preserve_line_endings(self):
        preview = self.propose()
        self.assertIn("+    return price - discount", preview)
        self.assertEqual(self.source.read_bytes(), self.original)
        with self.assertRaisesRegex(ValueError, "approval ID"):
            self.session.apply("wrong")
        self.session.apply(self.session.pending.id)
        self.assertEqual(self.source.read_bytes(), self.original.replace(b"+", b"-"))

    def test_rejects_stale_source_and_model_paths_outside_excerpts(self):
        with self.assertRaisesRegex(ValueError, "source shown"):
            self.propose(name="../pricing.py")
        self.propose()
        self.source.write_bytes(self.original + b"# another edit\r\n")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            self.session.apply(self.session.pending.id)
        self.assertTrue(self.source.read_bytes().endswith(b"# another edit\r\n"))
        self.assertIsNone(self.session.pending)

    @unittest.skipUnless(shutil.which("git"), "Git is required for workspace search")
    def test_search_uses_git_ignores_and_finds_symbols_without_inference(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        for name in ("ignored.py", ".env"):
            (self.root / name).write_text("discount_price", encoding="utf-8")
        with patch.object(chat, "complete") as complete:
            result = self.session.run("/search discount_price")["output"]
        complete.assert_not_called()
        self.assertIn("pricing.py:1", result)
        self.assertNotIn("ignored.py", result)
        self.assertNotIn(".env", result)
        (self.root / "README.md").write_text("Find the login handler in this codebase.", encoding="utf-8")
        (self.root / "routes.py").write_text("def login_handler(): pass\n", encoding="utf-8")
        hits = self.session.workspace.search("Find the login handler in this codebase", source_only=True)
        self.assertEqual([excerpt["name"] for excerpt, _ in hits], ["routes.py"])

    def test_retry_passes_test_failure_at_most_once(self):
        self.propose()
        self.session.apply(self.session.pending.id)
        self.session.test_command = [sys.executable, "-c", "print('expected 40'); raise SystemExit(1)"]
        self.assertIn("Test exit code 1", self.session.run("/test")["output"])
        with patch.object(self.session.workspace, "search", return_value=self.hits), \
             patch.object(self.session, "propose", return_value="Retry diff") as propose:
            self.assertIn("Retry diff", self.session.run("/retry")["output"])
            self.assertIn("one retry", self.session.run("/retry")["output"])
        propose.assert_called_once_with("Fix discount_price.", self.hits, "expected 40\n")

    def test_invalid_edit_retries_once_with_validation_feedback(self):
        def draft(line):
            return {"message": {"content": json.dumps({
                "path": "pricing.py", "start": line, "end": line,
                "new": "    return price - discount", "note": "Fix discount.",
            })}}, {}

        replies = [draft(20), draft(2)]
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", side_effect=replies) as complete:
            self.session.propose("Fix the total.", self.hits, "")
        self.assertEqual(complete.call_count, 2)
        self.assertIn("Previous proposal rejected", complete.call_args.args[0][0]["content"])
        properties = complete.call_args.kwargs["schema"]["properties"]
        self.assertEqual(properties["path"]["enum"], ["pricing.py", ""])
        self.assertEqual(properties["start"]["enum"], [1, 2])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_syntax_retry_reports_error_location_and_kind(self):
        def draft(new):
            return {"message": {"content": json.dumps({
                "path": "pricing.py", "start": 2, "end": 2,
                "new": new, "note": "Fix discount.",
            })}}, {}

        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", side_effect=[
                 draft("    return price - discount\n  broken"),
                 draft("    return price - discount"),
             ]) as complete:
            self.session.propose("Fix the total.", self.hits, "")
        self.assertIn("syntax error at line", complete.call_args.args[0][0]["content"])
        self.assertIn("indentation", complete.call_args.args[0][0]["content"])

    def test_adding_python_test_cannot_replace_existing_test(self):
        original = "def test_original():\n    assert True\n"
        extra = "def test_extra():\n    assert 2 + 2 == 4\n"
        hits = [({"name": "test_pricing.py", "line": 1, "text": original}, original.encode())]

        def draft(first, last, new):
            return {"message": {"content": json.dumps({
                "path": "test_pricing.py", "start": first, "end": last, "new": new, "note": "Test the total.",
            })}}, {}

        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", side_effect=[draft(1, 2, extra), draft(2, 0, "\n" + extra)]) as complete:
            preview = self.session.propose("Add a regression test.", hits, "")
        self.assertIn("Preserve existing test functions", complete.call_args.args[0][0]["content"])
        self.assertEqual(complete.call_args.kwargs["schema"]["properties"]["start"]["enum"], [2])
        self.assertEqual(complete.call_args.kwargs["schema"]["properties"]["end"]["enum"], [0])
        self.assertIn("+def test_extra()", preview)
        self.assertNotIn("-def test_original()", preview)

    def test_adding_test_keeps_retrieved_implementation_evidence(self):
        tests = "import unittest\nfrom inventory import available\n\nclass InventoryTests(unittest.TestCase):\n    def test_existing(self):\n        self.assertTrue(available(3, 1))\n"
        implementation = "def available(stock, held):\n    return max(0, stock - held)\n"
        hits = [
            ({"name": "test_inventory.py", "line": 1, "text": tests}, tests.encode()),
            ({"name": "inventory.py", "line": 1, "text": implementation}, implementation.encode()),
        ]
        reply = {"message": {"content": json.dumps({
            "path": "test_inventory.py", "start": 6, "end": 0,
            "new": "\n    def test_excess_holds(self):\n        self.assertEqual(available(2, 5), 0)",
            "note": "Check excess holds.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(reply, {})) as complete:
            self.session.propose("Add a regression test to test_inventory.py proving available returns zero when held exceeds stock.", hits, "")
        prompt = "\n".join(message["content"] for message in complete.call_args.args[0])
        self.assertIn("def available(stock, held)", prompt)
        self.assertIn("test_inventory.py", prompt)

    def test_additive_test_drops_an_exact_duplicate_of_an_existing_test(self):
        name = "test_inventory.py"
        source = (
            "import unittest\n\nclass InventoryTests(unittest.TestCase):\n"
            "    def test_available_normally(self):\n        self.assertEqual(available(10, 3), 7)\n"
        )
        proposal = (
            "    def test_available_normally(self):\n        self.assertEqual(available(10, 3), 7)\n"
            "    def test_excess_holds(self):\n        self.assertEqual(available(2, 5), 0)"
        )
        hit = ({"name": name, "line": 1, "text": source}, source.encode())
        reply = {"message": {"content": json.dumps({
            "path": name, "start": 5, "end": 0, "new": proposal, "note": "Test excess holds.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(reply, {})) as complete:
            preview = self.session.propose("Add a regression test to test_inventory.py.", [hit], "")
        self.assertEqual(complete.call_count, 1)
        self.assertNotIn("+    def test_available_normally", preview)
        self.assertIn("+    def test_excess_holds", preview)

    def test_complete_python_function_is_aligned_to_its_shown_definition(self):
        revised = self.original.decode().replace("\r\n", "\n").replace("price + discount", "price - discount")
        reply = {"message": {"content": json.dumps({
            "path": "pricing.py", "start": 2, "end": 2, "new": revised, "note": "Fix discount.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(reply, {})) as complete:
            self.session.propose("Fix pricing.py.", self.hits, "")
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(self.session.pending.updated, self.original.replace(b"+", b"-"))

    def test_failed_new_test_can_be_repaired_without_rewriting_original_tests(self):
        name = "test_pricing.py"
        initial = "def test_original():\n    assert True\n"
        current = initial + "\ndef test_extra():\n    assert False\n"
        hits = [({"name": name, "line": 1, "text": current}, current.encode())]
        self.session.last_edit = agent.Edit("old", name, initial.encode(), current.encode(), "", "Add a test.")
        reply = {"message": {"content": json.dumps({
            "path": name, "start": 5, "end": 5, "new": "    assert 2 + 2 == 4", "note": "Repair the test.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(reply, {})) as complete:
            self.session.propose("Add a test.", hits, "The new test failed.")
        self.assertIn(5, complete.call_args.kwargs["schema"]["properties"]["end"]["enum"])
        self.assertTrue(self.session.pending.updated.decode().startswith(initial))
        self.assertIn("assert 2 + 2 == 4", self.session.pending.updated.decode())

    def test_edit_of_named_file_uses_only_that_file(self):
        other = ({"name": "other.py", "line": 1, "text": "pass\n"}, b"pass\n")
        draft = {"message": {"content": json.dumps({
            "path": "pricing.py", "start": 2, "end": 2,
            "new": "    return price - discount", "note": "Fix discount.",
        })}}
        with patch.object(chat, "count_prompt", return_value=20), \
             patch.object(chat, "complete", return_value=(draft, {})) as complete:
            self.session.propose("Fix pricing.py.", [other, *self.hits], "")
        messages = complete.call_args.args[0]
        self.assertNotIn("other.py", str(messages))
        self.assertIn("2 |     return price + discount", str(messages))

    @unittest.skipUnless(shutil.which("git"), "Git is required for workspace search")
    def test_definition_search_gets_past_many_references(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        references = self.root / "a_references"
        references.mkdir()
        for index in range(610):
            (references / f"example{index}.py").write_text("unquote_plus('a+b')\n", encoding="utf-8")
        (self.root / "z_definition.py").write_text(
            "# Heading\nclass Decoder:\n    def unquote_plus(value):\n        return value.replace('+', ' ')\n",
            encoding="utf-8",
        )
        hits = self.session.workspace.search("Where is unquote_plus defined?", source_only=True)
        self.assertEqual(hits[0][0]["name"], "z_definition.py")
        evidence = agent.numbered(hits[0][0])["text"]
        self.assertIn("3 |     def unquote_plus", evidence)
        self.assertIn("Python definition: Decoder.unquote_plus at line 3", evidence)

    @unittest.skipUnless(shutil.which("git"), "Git is required for workspace search")
    def test_base_lookup_omits_matching_override_when_base_is_visible(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "callback.py").write_text(
            "class Parser:\n    def handle_starttag(self): pass\n", encoding="utf-8",
        )
        (self.root / "derived.py").write_text(
            "from callback import Parser\nclass Custom(Parser):\n    def handle_starttag(self): pass\n",
            encoding="utf-8",
        )
        workspace = self.session.workspace
        ordinary = workspace.search("Find handle_starttag", source_only=True)
        base = workspace.search("Find the base handle_starttag definition", source_only=True)
        self.assertIn("Custom.handle_starttag", [item.get("definition") for item, _ in ordinary])
        self.assertEqual([item.get("definition") for item, _ in base], ["Parser.handle_starttag"])

    def test_plain_repository_question_routes_to_source_and_remembers_answer(self):
        with patch.object(self.session.workspace, "search", return_value=self.hits) as search, \
             patch.object(chat, "select_answer", return_value={"answer": "In pricing.py:1."}) as answer:
            prompt = "Find discount_price in this codebase"
            self.assertIn("In pricing.py:1.", self.session.run(prompt)["output"])
            search.assert_called_once_with(prompt, source_only=True)
            self.assertEqual(answer.call_args.args[0]["files"], [agent.numbered(self.hits[0][0])])
            self.session.run("What file did we just find?")
            self.assertIn("In pricing.py:1.", answer.call_args.args[5][0])

    def test_exact_definition_starts_small_and_can_fall_back(self):
        exact = {**self.hits[0][0], "definition": "discount_price", "definition_line": 1}
        other = {"name": "calls.py", "line": 1, "text": "from pricing import discount_price"}
        hits = [(exact, self.original), (other, other["text"].encode())]
        prompt = "Where is discount_price defined in this codebase?"
        self.assertIsNone(agent.focused_source(prompt + " Include callers.", [exact, other]))
        self.assertIsNone(agent.focused_source(prompt, [exact, {**exact, "name": "second.py"}]))
        with patch.object(self.session.workspace, "search", return_value=hits), \
             patch.object(chat, "select_answer", side_effect=[
                 {"answer": "An answer without a citation."}, {"answer": "See pricing.py:1."},
                 {"answer": "discount_price is defined in pricing.py:1."},
             ]) as answer:
            self.assertIn("pricing.py:1", self.session.run(prompt)["output"])
        first, second, retry = [call.args[0]["files"] for call in answer.call_args_list]
        self.assertEqual(len(first), 1)
        self.assertIs(first[0]["focused"], chat.FOCUSED_FILE)
        self.assertEqual(len(second), 2)
        self.assertEqual(len(retry), 1)

    def test_edit_prompt_adds_test_and_repair_instructions_only_when_needed(self):
        self.assertNotIn("Add a test by setting", agent.edit_instructions(False, False, ""))
        self.assertIn("exact ending line as the insertion anchor", agent.edit_instructions(True, True, ""))
        self.assertIn("Repair the newly added test", agent.edit_instructions(True, False, ""))
        self.assertIn("Use a valid range", agent.edit_instructions(False, False, "Use a valid range"))

    def test_saved_history_can_resume_and_recall_an_older_turn(self):
        self.session.remember("Remember account-handler tag BLUEBIRD.", "Recorded BLUEBIRD.")
        for index in range(5):
            self.session.remember(f"Colour discussion {index}", "Green.")
        resumed = agent.Session(agent.Workspace(self.root), None, self.memory, "test")
        recent, recalled = resumed.history("What was the account-handler tag?")
        self.assertNotIn("BLUEBIRD", "\n".join(recent))
        self.assertIn("BLUEBIRD", "\n".join(recalled))
        separate = agent.Session(agent.Workspace(self.root), None, self.memory, "another")
        self.assertEqual(separate.history("account-handler"), ([], []))

    @unittest.skipUnless(shutil.which("git"), "Git is required for workspace search")
    def test_repository_overview_supplies_readme_and_file_listing(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "README.md").write_text("# Pricing tools\nCalculates discounts.", encoding="utf-8")
        (self.root / ".env").write_text("Hidden.", encoding="utf-8")
        with patch.object(chat, "select_answer", return_value={"answer": "This project calculates discounts."}) as answer:
            response = self.session.run("could you tell me about this codebase", web=True)
            self.assertIn("This project calculates discounts.", response["output"])
            files = answer.call_args.args[0]["files"]
            self.assertIn("pricing.py", files[0]["text"])
            self.assertNotIn(".env", files[0]["text"])
            self.assertIn("Calculates discounts.", files[1]["text"])
            self.assertEqual(answer.call_args.args[3]["queries"], [])


class RuntimeTests(unittest.TestCase):
    def test_native_platform_defaults_and_linux_acceleration_override(self):
        import os

        profiles = [
            ("win32", "AMD64", "28", "Vulkan0", "q8_0", "on"),
            ("darwin", "arm64", "auto", None, "f16", "auto"),
            ("darwin", "x86_64", "0", None, "f16", "auto"),
            ("linux", "aarch64", "0", None, "f16", "auto"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Qwen3-4B-Q4_K_M.gguf").touch()
            with patch.dict(os.environ, {}, clear=True), patch.object(runtime, "runner_location", return_value="runner"):
                for system, architecture, layers, device, kv, flash in profiles:
                    with self.subTest(platform=system, architecture=architecture), \
                         patch.object(runtime.sys, "platform", system), \
                         patch.object(runtime.platform, "machine", return_value=architecture):
                        args = runtime.runner_arguments(root, alias="test", port=8080, context=8192, thinking=640)
                        self.assertEqual(args[args.index("--gpu-layers") + 1], layers)
                        self.assertEqual(args[args.index("--cache-type-v") + 1], kv)
                        self.assertEqual(args[args.index("--flash-attn") + 1], flash)
                        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
                        if device:
                            self.assertEqual(args[args.index("--device") + 1], device)
                        else:
                            self.assertNotIn("--device", args)
                with patch.object(runtime.sys, "platform", "linux"), \
                     patch.dict(os.environ, {"LOCAL_AI_GPU_LAYERS": "auto", "LOCAL_AI_DEVICE": "Vulkan0"}):
                    args = runtime.runner_arguments(root, alias="test", port=8080, context=4096,
                                                    thinking=640, cache_prompt=False)
                    self.assertIn("--device", args)
                    self.assertEqual(args[args.index("--gpu-layers") + 1], "auto")
                    self.assertIn("--no-cache-prompt", args)

    def test_process_options_are_native(self):
        with patch("llama_runtime.os.name", "posix"):
            self.assertEqual(runtime.process_options(), {"start_new_session": True})
        with patch("llama_runtime.os.name", "nt"), \
             patch.object(runtime.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True):
            self.assertEqual(runtime.process_options(), {"creationflags": 512})

    def test_file_path_rules_cover_both_families(self):
        self.assertTrue(is_local_absolute(r"C:\project\main.py", windows=True))
        self.assertFalse(is_local_absolute(r"\\server\share\main.py", windows=True))
        self.assertTrue(is_local_absolute("/home/example/main.py", windows=False))
        self.assertFalse(is_local_absolute("project/main.py", windows=False))
        self.assertFalse(is_local_absolute("//server/main.py", windows=False))

class ContextTests(unittest.TestCase):
    def test_attachment_is_part_of_current_user_message(self):
        def count(messages, options):
            return sum(len(message["content"].split()) for message in messages)

        messages, _, _, _ = context.build_context(
            count, "System", "Summarise the file", [
                ("Local file", "paper.txt\nActual evidence", True),
                ("Recent turn", "I cannot see an attachment.", False),
            ], False, 100, current_labels=("Local file",),
        )
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("Actual evidence", messages[-1]["content"])
        self.assertTrue(messages[-1]["content"].endswith("Summarise the file"))
        self.assertNotIn("cannot see", messages[-1]["content"])

    def test_priority_and_template_budget(self):
        def count(messages, options):
            return 7 + sum(len(entry["content"].split()) for entry in messages)

        sections = [("memory", "port 9467", False), ("tool", "stale " * 220, False),
                    ("duplicate", "port 9467", False), ("recent", "another detail", False)]
        with patch.object(context, "CONTEXT", 130):
            messages, used, dropped, kept = context.build_context(
                count, "system", "current prompt", sections, True, 40,
            )
            self.assertEqual(messages[-1]["content"], "current prompt")
            self.assertLessEqual(used + 40 + 32, 130)
            self.assertEqual(dropped, 1)
            self.assertEqual([key for key, _ in kept], ["memory", "recent"])
            with self.assertRaises(context.BudgetError):
                context.build_context(count, "system", "keep " * 80, [], False, 40)

    def test_adaptive_modes_and_inference_limits(self):
        self.assertEqual(context.route("What is 7 * 8?", "auto"), (False, False))
        self.assertEqual(context.route("Debug this race condition", "auto"), (True, False))
        self.assertEqual(context.route("Why should I choose it?", "auto"), (False, True))
        self.assertEqual(context.route("Debug this", "quick"), (False, False))
        with patch.object(context, "CALLS", 2), patch.object(context, "GENERATED", 100):
            info = context.Diagnostics()
            with self.assertRaises(context.BudgetError):
                info.start(90, reserve=20)
            info.start(40)
            info.finish(40, 15, 10)
            info.start(90)
            with self.assertRaises(context.BudgetError):
                info.start(1)

    def test_review_expands_only_when_required(self):
        from types import SimpleNamespace
        from uuid import uuid4

        def count(messages, options):
            return 7 + sum(len(entry["content"].split()) for entry in messages)

        conversation, turn = str(uuid4()), str(uuid4())
        memory = SimpleNamespace(
            review_target=lambda selected, _: (2, "Original question", "draft " * 80) if selected == conversation else None,
            source=lambda *_: [], recall=lambda *_, **__: [], save_review=lambda *_: None,
        )
        response = ({"message": {"content": "Useful review."}}, {"prompt_tokens": 120})
        token = chat.DIAGNOSTICS.set(context.Diagnostics())
        try:
            with patch.object(chat, "MEMORY", memory), patch.object(chat, "count_prompt", count), \
                 patch.object(chat, "complete", return_value=response) as infer, \
                 patch.object(chat, "backend", return_value={"tokens": [1, 2, 3]}), \
                 patch.object(context, "REVIEW_TOKENS", 64), patch.object(context, "REVIEW_WINDOW", 160), \
                 patch.object(context, "CONTEXT", 512), patch.object(chat, "CONTEXT_SIZE", 512):
                result = chat.review_answer({"conversation": conversation, "turn": turn})
                self.assertEqual(result["working_context"], 512)
                infer.assert_called_once()
                with self.assertRaises(ValueError):
                    chat.review_answer({"conversation": str(uuid4()), "turn": turn})
                infer.reset_mock()
                infer.side_effect = [
                    ({"message": {"content": "Cut off draft"}, "finish_reason": "length"}, {}),
                    response,
                ]
                result = chat.review_answer({"conversation": conversation, "turn": turn})
                self.assertEqual(result["text"], "Useful review.")
                self.assertEqual(result["diagnostics"]["review_budget_retries"], 1)
                self.assertEqual(infer.call_count, 2)
        finally:
            chat.DIAGNOSTICS.reset(token)


class MemoryTests(unittest.TestCase):
    def test_persistence_retrieval_and_exact_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "memory.sqlite3"
            memory = ChatMemory(path)
            state = {"objective": "Migrate Glacier", "constraints": "port 9467"}
            source = {"title": "Docs", "url": "https://example.org", "snippet": "Use port 9467."}
            memory.remember("a", "first", "Remember Glacier uses port 9467.", "Acknowledged.", "", [source], state)
            for index in range(5):
                memory.remember("a", str(index), "New wallpaper", "Blue", "")
            memory.remember("b", "first", "Glacier uses port 1111.", "Acknowledged.", "")
            restored = ChatMemory(path)
            self.assertEqual(restored.state("a"), state)
            self.assertIn("9467", restored.recall("a", "Glacier port")[0])
            self.assertNotIn("1111", " ".join(restored.recall("a", "Glacier port")))
            self.assertEqual(restored.source("a", 1), [source])
            self.assertEqual(restored.source("b", 1), [])
            self.assertEqual(restored.remember("a", "first", "bad retry", "", "")[1], 6)
            self.assertEqual(restored.conversations()[-1], {
                "id": "a", "title": "Remember Glacier uses port 9467.",
            })
            transcript = restored.transcript("a")
            self.assertEqual(transcript["archivedTurns"], 6)
            self.assertEqual(transcript["turns"][0]["sources"], [source])
            self.assertEqual(transcript["taskState"], state)
            self.assertEqual(restored.transcript("unknown")["turns"], [])
            rowid, _, _ = restored.review_target("a", "first")
            restored.save_review(rowid, {"text": "Review of the first reply."})
            self.assertEqual(ChatMemory(path).transcript("a")["turns"][0]["review"]["text"],
                             "Review of the first reply.")
            self.assertIsNone(restored.transcript("b")["turns"][0]["review"])


class ToolTests(unittest.TestCase):
    def test_local_file_path_and_excerpt_validation(self):
        for invalid in (r"\\server\share\code.py", r"C:\NUL", r"C:\note.txt:stream", "relative.py"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                read_shared_file(invalid)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "sample.py"
            path.write_text("print(42)", encoding="utf-8")
            self.assertEqual(read_shared_file(str(path)), {"name": "sample.py", "text": "print(42)"})
        valid = [{"name": "sample.py", "line": 1, "text": "print(42)"}]
        self.assertEqual(validate_excerpts(valid), valid)
        with self.assertRaises(ValueError):
            validate_excerpts([{**valid[0], "line": 0}])

    def test_local_file_request_is_only_a_proposal(self):
        with patch.object(chat, "complete", return_value=(
            {"message": {"content": '{"query":"login","reason":"I need the handler location."}'}}, {},
        )) as complete:
            self.assertIsNone(chat.plan_file_search("Say hello"))
            complete.assert_not_called()
            result = chat.plan_file_search("Find the login handler in the repository")
            self.assertEqual(result, {"query": "login", "reason": "I need the handler location."})
            complete.assert_called_once()

    def test_explicit_local_repository_offer_needs_no_inference(self):
        prompt = "Find authenticate_user in this codebase"
        with patch.object(chat, "complete") as complete:
            result = chat.plan_file_search(prompt)
        self.assertIn("authenticate_user", result["query"])
        complete.assert_not_called()

    def test_search_discards_malformed_sources(self):
        response = io.BytesIO(
            b'{"results":[null,{"url":"javascript:alert(1)","content":"bad"},'
            b'{"url":"https://example.org","title":"Docs","content":"Useful evidence."}]}'
        )
        with patch.object(chat, "urlopen", return_value=response):
            self.assertEqual(chat.search_web("example")[0]["title"], "Docs")

    def test_repeat_query_stops_research(self):
        with patch.object(chat, "plan_search", side_effect=[
            ("same query", ""), ("Same Query!", "notes [1]"), ("same query", "notes [1]"),
        ]), \
             patch.object(chat, "search_web", return_value=[
                 {"url": "https://example.org", "title": "Docs", "snippet": "No additional data."}
             ]) as search:
            result = chat.run_research("", "prompt", None, True, lambda event: None)
            search.assert_called_once()
            self.assertEqual(result["notes"], "notes [1]")
            self.assertIn("repeated", result["warning"])

    def test_duplicate_can_narrow_an_explicit_evidence_gap(self):
        result = chat.narrow_query("latest Acme Widget API version and its license", "Find the version and license", [
            {"id": 1, "title": "Docs", "snippet": "The license is not specified on this page."},
        ])
        self.assertEqual(result, "Acme Widget API license")

    def test_invalid_state_and_arithmetic_verification(self):
        diagnostic = context.Diagnostics()
        token = chat.DIAGNOSTICS.set(diagnostic)
        try:
            with patch.object(chat, "count_prompt", return_value=10), \
                 patch.object(chat, "complete", return_value=({"message": {"content": '{"objective": 123}'}}, {})):
                self.assertEqual(chat.update_task({"objective": "old"}, "new", "reply", []), {"objective": "old"})
            self.assertEqual(chat.verify_arithmetic("What is 14 * 6?", "85", diagnostic), "84")
            self.assertIsNotNone(chat.python_syntax_error("Generate Python", "```python\nx =\n```"))
            self.assertIsNone(chat.python_syntax_error("Generate Python", "```python\nx = 1\n```"))
            self.assertEqual(diagnostic.events["verification_failures"], 2)
        finally:
            chat.DIAGNOSTICS.reset(token)

    def test_model_can_escalate_once(self):
        diagnostic = context.Diagnostics()
        token = chat.DIAGNOSTICS.set(diagnostic)
        try:
            with patch.object(chat, "answer", side_effect=[
                {"answer": "THINK", "limited": False},
                {"answer": "A reasoned reply.", "limited": False},
            ]) as answer, patch.object(chat, "backend", return_value={"tokens": [1, 2, 3]}):
                result = chat.select_answer(
                    {"mode": "auto"}, "", "Why should I compare these approaches?",
                    {"evidence": []}, [], [], {}, None, None,
                )
            self.assertEqual(result["answer"], "A reasoned reply.")
            self.assertEqual(diagnostic.events["escalations"], 1)
            self.assertTrue(answer.call_args.args[2])
        finally:
            chat.DIAGNOSTICS.reset(token)

    def test_final_reply_is_buffered_and_shortened_if_over_budget(self):
        diagnostic = context.Diagnostics()
        token = chat.DIAGNOSTICS.set(diagnostic)
        events = []

        def draft(*args, **kwargs):
            if kwargs.get("concise"):
                return {"answer": "Short answer.", "limited": False}
            args[7]({"reasoning_content": "Think first."})
            args[7]({"content": "Unapproved draft."})
            return {"answer": "Unapproved draft.", "limited": False}

        try:
            with patch.object(chat, "answer", side_effect=draft) as infer, \
                 patch.object(chat, "backend", side_effect=[
                     {"tokens": range(context.REPLY + 1)}, {"tokens": [1, 2]},
                 ]):
                result = chat.select_answer(
                    {"mode": "think"}, "", "Explain the topic", {"evidence": []},
                    [], [], {}, None, events.append,
                )
            self.assertEqual(result["answer"], "Short answer.")
            self.assertEqual(infer.call_count, 2)
            self.assertEqual(events[0], {"reasoning_content": "Think first."})
            self.assertTrue(all("content" not in event for event in events))
            self.assertEqual(diagnostic.events["reply_budget_retries"], 1)
        finally:
            chat.DIAGNOSTICS.reset(token)


if __name__ == "__main__":
    unittest.main()
