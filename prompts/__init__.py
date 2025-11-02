"""Utilities for loading reusable prompt templates.

The prompts package provides a light wrapper so prompts can be stored as
human-editable files while still supporting programmatic formatting and
overrides via environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = ["PromptTemplate", "load_prompt_template", "render_prompt"]

_PROMPT_ROOT = Path(__file__).resolve().parent
_ENV_PREFIX = "TRAVEL_PLANNER_PROMPT_"


def _resolve_override(name: str) -> str | None:
    """Return override prompt content or path from the environment if set."""
    env_var = _ENV_PREFIX + name.upper()
    override_value = os.getenv(env_var)
    if not override_value:
        return None

    override_path = Path(override_value)
    if override_path.exists():
        return override_path.read_text(encoding="utf-8")

    # Treat the environment variable as literal prompt content.
    return override_value


@dataclass(frozen=True)
class PromptTemplate:
    """A minimal string template helper using ``str.format`` semantics."""

    text: str

    def format(self, **kwargs: Any) -> str:
        return self.text.format(**kwargs)


@lru_cache(maxsize=None)
def load_prompt_template(name: str, filename: str) -> PromptTemplate:
    """Load a prompt template by ``name`` with optional environment override.

    ``name`` is used as the suffix of the environment variable
    ``TRAVEL_PLANNER_PROMPT_<NAME>``. If that variable is set and contains a
    readable file path, its contents are used. Otherwise, the literal value is
    treated as prompt text. When unset, the prompt file is loaded from the
    package directory.
    """

    override = _resolve_override(name)
    if override is not None:
        return PromptTemplate(override)

    path = _PROMPT_ROOT / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return PromptTemplate(path.read_text(encoding="utf-8"))


def render_prompt(name: str, filename: str, **kwargs: Any) -> str:
    """Convenience helper to render a named prompt in one call."""

    template = load_prompt_template(name, filename)
    return template.format(**kwargs)
