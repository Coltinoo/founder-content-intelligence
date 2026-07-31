"""AI analysis layer.

Two interchangeable backends behind one interface:

* ``LLMBackend`` — OpenAI structured outputs, driven by the editable prompt
  files in ``prompts/``.
* ``HeuristicBackend`` — deterministic, no credentials required. Quotes and
  evidence passages are *sliced verbatim from the source text*, themes are
  matched against a keyword taxonomy, and scores come from transparent formulas.

The heuristic backend exists so the product is demonstrable and testable without
an API key, and so every LLM output has a non-LLM baseline to compare against.
Which backend produced a row is always recorded and always shown in the UI.
"""

from .client import AIClient, LLMUnavailable  # noqa: F401
from .prompts import PromptLibrary, load_prompt  # noqa: F401

__all__ = ["AIClient", "LLMUnavailable", "PromptLibrary", "load_prompt"]
