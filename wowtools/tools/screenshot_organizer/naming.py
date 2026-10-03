"""WoW's screenshot file names: WoWScrnShot_MMDDYY_HHMMSS.<jpg|jpeg|png|tga>. The date comes from the name only."""
from __future__ import annotations

import re
from datetime import date

SHOT_RE = re.compile(r"^WoWScrnShot_(\d{2})(\d{2})(\d{2})_(\d{6})\.(?:jpe?g|png|tga)$", re.IGNORECASE)


def parse_shot_name(name: str) -> date | None:
    """The day a screenshot was taken, or None if the name is not a WoW screenshot name (or not a real date)."""
    match = SHOT_RE.match(name)
    if match is None:
        return None
    month, day, year = (int(match.group(i)) for i in (1, 2, 3))
    try:
        return date(2000 + year, month, day)
    except ValueError:
        return None


def day_parts(day: date) -> tuple[str, str, str]:
    """The YYYY, MM and DD folder names for a day."""
    return f"{day.year:04d}", f"{day.month:02d}", f"{day.day:02d}"
