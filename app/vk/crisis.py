"""Грубый фильтр острых формулировок: без эзотерического разбора и без списания."""

import re

_CRISIS_PATTERNS = [
    r"суицид",
    r"самоубийств",
    r"поконч\w* с собой",
    r"убить себя",
    r"убью себя",
    r"хочу умереть",
    r"не хочу жить",
    r"наложить на себя руки",
    r"прыгн\w* (с|из|под)",
    r"повесить(ся)?",
    r"мне незачем жить",
    r"жизнь не имеет смысла и я хочу уйти",
]


def is_crisis(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in _CRISIS_PATTERNS)
