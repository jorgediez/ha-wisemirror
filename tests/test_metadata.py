"""Checks on the files that describe the integration rather than run it."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

REPO = Path(__file__).resolve().parents[1]


def test_the_version_is_declared_once():
    """Both files carry the version, and a release must match both."""
    manifest = json.loads(
        (REPO / "custom_components" / "wisemirror" / "manifest.json").read_text("utf-8")
    )
    project = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))

    assert manifest["version"] == project["project"]["version"]
