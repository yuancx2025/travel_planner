"""Backward compatibility: Re-export prompts from agents.prompts.

This module maintains backward compatibility by re-exporting all functionality
from agents.prompts. All prompts have been migrated to agents/prompts/.
"""

from __future__ import annotations

# Re-export everything from agents.prompts for backward compatibility
from agents.prompts import (
    PromptTemplate,
    load_prompt_template,
    render_prompt,
)

__all__ = ["PromptTemplate", "load_prompt_template", "render_prompt"]
