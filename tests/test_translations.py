"""Checks on the translations, which are kept in English and Spanish."""

from __future__ import annotations

import json
from pathlib import Path
import re

INTEGRATION = Path(__file__).resolve().parents[1] / "custom_components" / "wisemirror"


def _strings(language: str) -> dict[str, str]:
    """Flatten a translation file into dotted keys."""

    def flatten(tree: dict, prefix: str = "") -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in tree.items():
            if isinstance(value, dict):
                out.update(flatten(value, f"{prefix}{key}."))
            else:
                out[f"{prefix}{key}"] = value
        return out

    path = INTEGRATION / "translations" / f"{language}.json"
    return flatten(json.loads(path.read_text(encoding="utf-8")))


def test_spanish_has_every_english_string():
    """A string missing in one language falls back to English without a word."""
    assert set(_strings("es")) == set(_strings("en"))


def test_placeholders_match_between_languages():
    """A placeholder the translation lacks or invents breaks the message."""
    english, spanish = _strings("en"), _strings("es")
    for key, text in english.items():
        assert set(re.findall(r"\{\w+\}", spanish[key])) == set(
            re.findall(r"\{\w+\}", text)
        ), key


def test_every_raised_error_has_a_message():
    """A missing message shows the bare translation key to the user."""
    raised = {
        match
        for path in INTEGRATION.glob("*.py")
        for match in re.findall(
            r'translation_domain=DOMAIN,\s*translation_key="(\w+)"',
            path.read_text(encoding="utf-8"),
        )
    }
    messages = {
        key.split(".")[1] for key in _strings("en") if key.startswith("exceptions.")
    }

    assert raised, "the scan found no translated errors"
    assert raised == messages
