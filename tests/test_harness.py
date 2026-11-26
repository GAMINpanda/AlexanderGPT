import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

SERVER_DIR = pathlib.Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import compact_chat as chat
import harness_context as context
from chat_memory import ChatMemory
from local_files import read_shared_file, validate_excerpts

class ContextTests(unittest.TestCase):
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
                 patch.object(context, "REVIEW_TOKENS", 64), patch.object(context, "REVIEW_WINDOW", 160), \
                 patch.object(context, "CONTEXT", 512), patch.object(chat, "CONTEXT_SIZE", 512):
                result = chat.review_answer({"conversation": conversation, "turn": turn})
                self.assertEqual(result["working_context"], 512)
                infer.assert_called_once()
                with self.assertRaises(ValueError):
                    chat.review_answer({"conversation": str(uuid4()), "turn": turn})
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
            result = chat.plan_file_search("Find the login handler in my repository")
            self.assertEqual(result, {"query": "login", "reason": "I need the handler location."})

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
            ]) as answer:
                result = chat.select_answer(
                    {"mode": "auto"}, "", "Why should I compare these approaches?",
                    {"evidence": []}, [], [], {}, None, None,
                )
            self.assertEqual(result["answer"], "A reasoned reply.")
            self.assertEqual(diagnostic.events["escalations"], 1)
            self.assertTrue(answer.call_args.args[2])
        finally:
            chat.DIAGNOSTICS.reset(token)


if __name__ == "__main__":
    unittest.main()
