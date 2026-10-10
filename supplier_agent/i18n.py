"""Interface translations (English and Spanish).

English text is the key. ``Translator`` looks a string up in the catalogue for
the chosen language and falls back to English, so an untranslated string never
breaks the interface. ``TranslatedStreamlit`` wraps the ``streamlit`` module
so labels, help texts, options and table headers are translated without
changing the app's logic or widget values.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pandas as pd

from .i18n_es import ES, ES_PATTERNS

LANGUAGES = {"en": "English", "es": "Español"}
CATALOGUES: dict[str, dict[str, str]] = {"es": ES}
PATTERNS: dict[str, list[tuple[re.Pattern[str], str]]] = {"es": [(re.compile(p), r) for p, r in ES_PATTERNS]}

_TAG_TEXT = re.compile(r">([^<>]+)<")
_EDGE = re.compile(r"^([\s●◐○–★·•\-]*)(.*?)([\s:.*]*)$", re.DOTALL)
MISSING: set[str] = set()  # untranslated strings seen in this process (used to maintain the catalogue)


class Translator:
    def __init__(self, language: str = "en") -> None:
        self.language = language if language in LANGUAGES else "en"
        self.catalogue = CATALOGUES.get(self.language, {})
        # Long Markdown keys are matched with whitespace collapsed, so line breaks do not matter.
        self.collapsed = {" ".join(key.split()): value for key, value in self.catalogue.items()}
        self.patterns = PATTERNS.get(self.language, [])
        self.missing: set[str] = set()

    def __call__(self, text: str, **values: Any) -> str:
        template = self.lookup(text)
        return template.format(**values) if values else template

    def lookup(self, text: str) -> str:
        if self.language == "en" or not isinstance(text, str) or not text.strip():
            return text
        if text in self.catalogue:
            return self.catalogue[text]
        collapsed = " ".join(text.split())
        if collapsed in self.collapsed:
            return self.collapsed[collapsed]
        if "<" in text and ">" in text:
            return _TAG_TEXT.sub(lambda match: ">" + self._segment(match.group(1)) + "<", text)
        translated = self._segment(text)
        if translated == text and any(char.isalpha() for char in text):
            self.missing.add(text)
            MISSING.add(text)
        return translated

    def _segment(self, text: str) -> str:
        if text in self.catalogue:
            return self.catalogue[text]
        prefix, core, suffix = _EDGE.match(text).groups()
        if core in self.catalogue:
            return prefix + self.catalogue[core] + suffix
        return self.sentence(text)

    def sentence(self, text: str) -> str:
        """Translate generated sentences (finding summaries, evidence) with regex patterns."""
        if self.language == "en" or not isinstance(text, str):
            return text
        result = text
        for pattern, replacement in self.patterns:
            result = pattern.sub(replacement, result)
        return result


_TEXT_KWARGS = ("label", "help", "placeholder", "body", "text", "caption")
_PLAIN = (str, int, float, bool, type(None))


class TranslatedStreamlit:
    """Proxy around ``streamlit`` (or any DeltaGenerator) that translates displayed text."""

    def __init__(self, target: Any, translate: Translator) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_t", translate)

    # Context managers (st.sidebar, st.expander, st.form, columns…)
    def __enter__(self):
        self._target.__enter__()
        return self

    def __exit__(self, *exc):
        return self._target.__exit__(*exc)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target, name, value)

    def _wrap(self, value: Any) -> Any:
        if isinstance(value, _PLAIN) or isinstance(value, pd.DataFrame):
            return value
        if isinstance(value, (list, tuple)) and value and all(hasattr(item, "_get_delta_path_str") for item in value):
            return type(value)(TranslatedStreamlit(item, self._t) for item in value)
        if hasattr(value, "_get_delta_path_str") or getattr(value, "__name__", "") == "streamlit":
            return TranslatedStreamlit(value, self._t)
        return value

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if name in {"session_state", "secrets", "query_params", "column_config", "cache_data", "cache_resource", "testing"}:
            return attribute
        if not callable(attribute):
            return self._wrap(attribute)
        translate = self._t

        def call(*args, **kwargs):
            args = list(args)
            if args and isinstance(args[0], str):
                args[0] = translate(args[0])
            elif args and isinstance(args[0], pd.DataFrame):
                args[0] = args[0].rename(columns=lambda column: translate(str(column)))
            if isinstance(kwargs.get("column_config"), dict):
                kwargs["column_config"] = {translate(str(key)): value for key, value in kwargs["column_config"].items()}
            for key in _TEXT_KWARGS:
                if isinstance(kwargs.get(key), str):
                    kwargs[key] = translate(kwargs[key])
            if name in {"selectbox", "radio", "multiselect", "segmented_control", "pills", "select_slider"}:
                original: Callable[[Any], Any] = kwargs.get("format_func", str)
                kwargs["format_func"] = lambda value, _original=original: translate(str(_original(value)))
            return self._wrap(attribute(*args, **kwargs))

        return call


def translate_frame(frame: pd.DataFrame, translate: Translator, columns: tuple[str, ...]) -> pd.DataFrame:
    """Translate generated sentences in the given columns (values, not headers)."""
    if translate.language == "en" or frame.empty:
        return frame
    frame = frame.copy()
    for column in columns:
        if column in frame.columns:
            frame[column] = frame[column].map(lambda value: translate.sentence(value) if isinstance(value, str) else value)
    return frame
