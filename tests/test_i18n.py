"""English / Spanish interface."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from supplier_agent.i18n import Translator
from supplier_agent.i18n_es import ES, ES_PATTERNS

APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


class CatalogueTests(unittest.TestCase):
    def test_translations_keep_every_placeholder(self):
        for english, spanish in ES.items():
            self.assertEqual(set(PLACEHOLDER.findall(english)), set(PLACEHOLDER.findall(spanish)), english)

    def test_patterns_compile_and_translate_generated_sentences(self):
        t = Translator("es")
        self.assertEqual(len(ES_PATTERNS), len(t.patterns))
        self.assertIn("NIF", t.sentence("same Tax ID; name similarity 98.0%"))
        self.assertNotEqual(
            t.sentence("TAX_ID is missing; exact-match coverage is reduced."), "TAX_ID is missing; exact-match coverage is reduced."
        )

    def test_english_is_unchanged_and_unknown_text_falls_back(self):
        self.assertEqual(Translator("en")("Review queue"), "Review queue")
        self.assertEqual(Translator("es")("Review queue"), "Cola de revisión")
        self.assertEqual(Translator("es")("Some brand new label"), "Some brand new label")
        self.assertEqual(Translator("xx")("Review queue"), "Review queue")

    def test_long_text_matches_regardless_of_line_breaks(self):
        t = Translator("es")
        key = next(key for key in ES if len(key) > 120)
        self.assertEqual(t("\n" + key.replace(" ", "\n", 3) + "\n"), ES[key])


class SpanishInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"SUPPLIER_REVIEW_DB": str(Path(self.temp.name) / "reviews.sqlite3")})
        environment.start()
        self.addCleanup(environment.stop)

    def test_every_page_renders_in_spanish(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=120)
        app.session_state["language"] = "es"
        app.run()
        self.assertFalse(app.exception)
        self.assertIn("Encuentra proveedores duplicados", " ".join(item.value for item in app.markdown))
        for page in ["Review queue", "Clusters", "What's new", "Check a supplier", "Investigation", "Review history", "Guide"]:
            app.radio(key="page").set_value(page).run()
            self.assertFalse(app.exception, page)
            self.assertFalse(app.error, page)
        app.radio(key="page").set_value("Review queue").run()
        self.assertIn("Tipo de hallazgo", [box.label for box in app.selectbox])
        # widget values stay in English so the logic is identical in both languages
        self.assertEqual(app.radio(key="page").value, "Review queue")

    def test_language_can_come_from_the_environment(self):
        with patch.dict(os.environ, {"SUPPLIER_DESK_LANG": "es"}):
            app = AppTest.from_file(str(APP_PATH), default_timeout=120).run()
        self.assertEqual(app.session_state["language"], "es")


if __name__ == "__main__":
    unittest.main()
