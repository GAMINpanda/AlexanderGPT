"""Extension interface for optional source-language structure and validation."""


class LanguageValidationError(ValueError):
    """A proposed source edit failed a language-specific structural check."""


class LanguageProvider:
    """Provide syntax-aware behavior for a set of file suffixes.

    Implement only the capabilities a language supports. The terminal agent keeps
    line-based search and edits as a fallback when no provider handles a file.
    """

    name = "Source"
    extensions = ()
    search_globs = ()

    def declaration_pattern(self, symbol_pattern):
        return None

    def declaration_name(self, line):
        return None

    def qualify_definition(self, source, line):
        return None

    def align_edit(self, source, replacement, first, last, shown_start, shown_end, adding_test):
        return first, last

    def insertion_anchor(self, source, shown_start, shown_end):
        return None

    def validate_edit(self, source, updated, *, test_task=False, baseline=None):
        return None
