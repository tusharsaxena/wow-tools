"""The Ka0s theme, taken from the Ka0s shield logo: navy-black, deep blue, electric-blue glow, steel silver."""
from __future__ import annotations

from textual.theme import Theme

KA0S_THEME = Theme(
    name="ka0s",
    primary="#2F8CFF",
    secondary="#8A96A8",
    accent="#5CC8FF",
    foreground="#D3DAE3",
    background="#05080F",
    surface="#0B1526",
    panel="#10213D",
    success="#4CC38A",
    warning="#E8B04B",
    error="#E5534B",
    dark=True,
)
