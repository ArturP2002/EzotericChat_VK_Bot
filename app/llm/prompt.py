"""Системный промпт «Новая Игра» и очистка ответа от названий Кодов."""

from functools import lru_cache
from pathlib import Path
import re

from app.vk.texts import GENERIC_OFFERS

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "system_nova_igra.md"

CODE_LABELS = [
    "ЦЕЛОСТНОСТЬ",
    "ПУТЬ ДУШИ",
    "ИЗОБИЛИЕ",
    "ПРЕЛОМЛЕНИЕ",
    "ПУЛЬСАЦИЯ",
    "ПИТАНИЕ",
    "ПЕРЕХОД",
    "БЛАГОДАРЕНИЕ",
    "МЕРЦАНИЕ",
    "ДВИЖЕНИЕ",
    "СТЕРЖЕНЬ",
    "Я ЕСТЬ",
    "ЯСНО",
    "ТВОРЕЦ",
    "ИЛЛЮЗИЯ",
    "МАТЕРИЯ",
    "ДОРОГА",
    "СВЕТ",
    "ТЕНЬ",
    "ЛЮБОВЬ",
    "СТРАХ",
    "МУЖСКОЕ",
    "ЖЕНСКОЕ",
    "ДУША",
]

REPLACEMENTS = {
    "ЦЕЛОСТНОСТЬ": "Источник",
    "ПУТЬ ДУШИ": "духовные задачи",
    "ИЗОБИЛИЕ": "достаточность для пути",
    "ПРЕЛОМЛЕНИЕ": "фильтр восприятия",
    "ПУЛЬСАЦИЯ": "ритм усвоения опыта",
    "ПИТАНИЕ": "встреча с опытом",
    "ПЕРЕХОД": "усвоение опыта",
    "БЛАГОДАРЕНИЕ": "завершение и отпускание",
    "МЕРЦАНИЕ": "смена внутреннего поля",
    "ДВИЖЕНИЕ": "смена состояния",
    "СТЕРЖЕНЬ": "внутренняя опора",
    "Я ЕСТЬ": "память о том, кто вы есть",
    "ЯСНО": "внутренняя сверка",
    "ТВОРЕЦ": "осознанный автор своей жизни",
    "ИЛЛЮЗИЯ": "временная форма Игры",
    "МАТЕРИЯ": "физический мир",
    "ДОРОГА": "действия в мире",
    "СВЕТ": "взгляд из целостности",
    "ТЕНЬ": "опыт через разделение",
    "ЛЮБОВЬ": "движение к единству",
    "СТРАХ": "забывание своей природы",
    "МУЖСКОЕ": "принцип действия и формы",
    "ЖЕНСКОЕ": "принцип пространства и смысла",
    "ДУША": "душа",
}


@lru_cache
def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


_OLD_OFFER = re.compile(r"^Если хотите, могу\s+(?!помочь:)(.+)$", re.MULTILINE)


def ensure_offers(text: str) -> str:
    """В конце — заголовок и пункты 1., 2. Если модель дала старый формат, собираем его заново."""
    raw = (text or "").rstrip()
    old_lines = _OLD_OFFER.findall(raw)
    if old_lines:
        body = _OLD_OFFER.sub("", raw).rstrip()
        numbered = "\n".join(
            f"{i}. {item.strip().rstrip('.')}."
            for i, item in enumerate(old_lines, 1)
        )
        return f"{body}\n\nЕсли хотите, могу помочь:\n{numbered}"
    if "Если хотите, могу помочь:" in raw:
        return raw
    if "Если хотите, могу" in raw:
        return raw
    return raw + GENERIC_OFFERS


def sanitize_answer(text: str) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"Код\s*\d+\.?\s*", "", cleaned, flags=re.IGNORECASE)
    for label in sorted(CODE_LABELS, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(label)}\b", REPLACEMENTS[label], cleaned)
    return ensure_offers(cleaned.strip())
