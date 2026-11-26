"""Language provider registry for the terminal agent."""

from .base import LanguageProvider
from .python import PythonLanguage


_PROVIDERS = (PythonLanguage(),)


def providers():
    return _PROVIDERS


def for_path(path):
    folded = path.casefold()
    return next((provider for provider in _PROVIDERS
                 if any(folded.endswith(extension) for extension in provider.extensions)), None)
