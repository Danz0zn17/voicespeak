"""Setup helper: capture the next physical input as an id, for button-learning.

Used by the on-device setup flow ("press the button you want for X") so mappings
are learned, never hardcoded.
"""

from __future__ import annotations

from .base import InputSource, merge


def learn_next(sources: list[InputSource]) -> str:
    """Block until one physical input fires; return its id (e.g. 'gpio:17')."""
    for input_id in merge(sources):
        return input_id
    raise RuntimeError("No input received")
