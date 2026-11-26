"""Python AST support used by repository search and safe edit validation."""

import ast
import re
from pathlib import PurePosixPath
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

    def related_imports(self, path, source):
        """Return workspace-relative module candidates and imported symbol names."""
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, ValueError):
            return []
        parent = PurePosixPath(path).parent.parts
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = parent[:max(0, len(parent) - node.level + 1)] if node.level else ()
                module = (*base, *(node.module.split(".") if node.module else ()))
                symbols = tuple(alias.name for alias in node.names if alias.name != "*")
                if not module:
                    continue
            elif isinstance(node, ast.Import):
                module = ()
                symbols = ()
                for alias in node.names:
                    parts = tuple(alias.name.split("."))
                    found.append((("/".join(parts) + ".py", "/".join((*parts, "__init__.py"))), ()))
                continue
            else:
                continue
            dotted = "/".join(module)
            candidates = (dotted + ".py", "/".join((*module, "__init__.py")))
            found.append((candidates, symbols))
        return found

    def symbol_excerpt(self, path, source, symbols):
        """Extract imported Python declarations without passing whole unrelated modules."""
        try:
            tree = ast.parse(source)
        except (SyntaxError, RecursionError, ValueError):
            return None
        wanted = set(symbols)
        kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        declarations = [node for node in ast.walk(tree)
                        if isinstance(node, kinds) and (not wanted or node.name in wanted)]
        if not declarations:
            return None
        declarations.sort(key=lambda node: (node.lineno, node.end_lineno))
        lines = source.splitlines()
        first_node = declarations[0]
        first = min([first_node.lineno, *(decorator.lineno for decorator in first_node.decorator_list)])
        last = declarations[-1].end_lineno
        excerpt = "\n".join(lines[first - 1:last])
        if len(excerpt) > 1500:
            excerpt = "\n".join(lines[first - 1:first_node.end_lineno])
        text = excerpt[:1500]
        definition = self.qualify_definition(source, first_node.lineno)
        item = {"name": path, "line": first, "text": text, "language": self.name}
        if definition:
            item.update(definition=definition["name"], definition_line=first_node.lineno)
        return item

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

    def normalize_addition(self, source, replacement):
        """Drop exact copies of existing tests when a draft redundantly includes them."""
        try:
            existing = ast.parse(source)
            proposed = ast.parse(dedent(replacement))
        except (SyntaxError, RecursionError, ValueError):
            return replacement
        existing_by_name = {}
        for node in ast.walk(existing):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                existing_by_name.setdefault(node.name, set()).add(ast.dump(node))
        lines = replacement.splitlines(keepends=True)
        remove = set()
        for node in ast.walk(proposed):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            if ast.dump(node) not in existing_by_name.get(node.name, set()):
                continue
            first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            remove.update(range(first, node.end_lineno + 1))
        if not remove:
            return replacement
        return "".join(line for number, line in enumerate(lines, 1) if number not in remove)

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
