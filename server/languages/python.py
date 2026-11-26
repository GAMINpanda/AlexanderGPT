"""Python AST support used by repository search and safe edit validation."""

import ast
import re
from textwrap import dedent

from .base import LanguageProvider, LanguageValidationError


class PythonLanguage(LanguageProvider):
    name = "Python"
    extensions = (".py", ".pyi")
    search_globs = ("*.py", "*.pyi")
    _declaration = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([\w]+)\b")

    def declaration_pattern(self, symbol_pattern):
        return (r"^[[:space:]]*(async[[:space:]]+)?(def|class)[[:space:]]+"
                rf"[[:alnum:]_]*({symbol_pattern})[[:alnum:]_]*")

    def declaration_name(self, line):
        match = self._declaration.match(line)
        return match.group(1) if match else None

    def qualify_definition(self, source, line):
        def find(node, parents, bases):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.lineno <= line <= node.end_lineno:
                    return None
                parents = (*parents, node.name)
                if isinstance(node, ast.ClassDef):
                    bases = tuple(base.id if isinstance(base, ast.Name) else base.attr
                                  for base in node.bases if isinstance(base, (ast.Name, ast.Attribute)))
                if node.lineno == line:
                    return {"name": ".".join(parents), "bases": bases}
            for child in ast.iter_child_nodes(node):
                found = find(child, parents, bases)
                if found:
                    return found
            return None

        try:
            return find(ast.parse(source), (), ())
        except (SyntaxError, RecursionError, ValueError):
            return None

    def insertion_anchor(self, source, shown_start, shown_end):
        """Return the end of the last visible test as an unambiguous insertion point."""
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, ValueError):
            return None
        tests = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name.startswith("test_")
                 and shown_start <= node.end_lineno <= shown_end]
        return max((node.end_lineno for node in tests), default=None)

    def align_edit(self, source, replacement, first, last, shown_start, shown_end, adding_test):
        """Keep complete function drafts and additive tests at function boundaries."""
        functions = (ast.FunctionDef, ast.AsyncFunctionDef)
        try:
            body = ast.parse(dedent(replacement)).body
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, ValueError):
            return first, last
        if len(body) != 1 or not isinstance(body[0], functions):
            return first, last
        function = body[0]
        line = replacement.splitlines()[function.lineno - 1]
        indentation = len(line) - len(line.lstrip())
        for node in ast.walk(tree):
            if not isinstance(node, functions) or node.col_offset != indentation:
                continue
            if not shown_start <= node.lineno <= first <= node.end_lineno <= shown_end:
                continue
            if adding_test and last == 0 and function.name.startswith("test_"):
                return node.end_lineno, 0
            if node.name == function.name and first <= last <= node.end_lineno and not node.decorator_list:
                return node.lineno, node.end_lineno
        return first, last

    @staticmethod
    def test_functions(tree, prefix=""):
        found = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                found.update(PythonLanguage.test_functions(node, prefix + node.name + "."))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                name = prefix + node.name
                found.setdefault(name, []).append(ast.dump(node))
        return found

    def validate_edit(self, source, updated, *, test_task=False, baseline=None):
        try:
            tree = ast.parse(updated)
        except SyntaxError as error:
            location = f"line {error.lineno}" if error.lineno else "an unknown line"
            detail = error.msg or "invalid syntax"
            raise LanguageValidationError(
                f"Python syntax error at {location}: {detail}. Correct the indentation or syntax in the proposed edit."
            ) from None
        if test_task:
            try:
                before = self.test_functions(ast.parse(source if baseline is None else baseline))
            except SyntaxError:
                raise ValueError("Existing tests cannot be checked because the original Python file has a syntax error.") from None
            after = self.test_functions(tree)
            if any(after.get(key) != bodies for key, bodies in before.items()) or not (after.keys() - before.keys()):
                raise LanguageValidationError(
                    "Preserve existing test functions exactly and append a new test with a distinct name."
                )
        return None
