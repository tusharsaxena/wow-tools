"""The Macro Editor's templates (config tools spec ME11): curated macros in wowtools/kb/macro_templates.json, each
with its source and the placeholders the user fills in. UI-free."""
from __future__ import annotations

import re
from collections.abc import Mapping

from wowtools.core.kb import MacroTemplate, load_templates

__all__ = ["MacroTemplate", "fill_template", "load_templates"]


def fill_template(t: MacroTemplate, values: Mapping[str, str]) -> str:
    """The template's body with each `{placeholder}` replaced by its value. ValueError when a value is missing,
    empty or holds a line break (a spell name is one line)."""
    filled: dict[str, str] = {}
    for name in t.placeholders:
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} needs a value")
        if "\n" in value or "\r" in value:
            raise ValueError(f"{name} must be one line")
        filled[name] = value.strip()
    # One pass, so a value that itself holds "{...}" is never filled again.
    return re.sub(r"\{([^{}]+)\}", lambda m: filled.get(m.group(1), m.group(0)), t.body)
