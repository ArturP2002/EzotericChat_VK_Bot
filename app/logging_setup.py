"""Настройка журнала бота: консоль и вращающийся файл, сообщения на русском."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

# Человекочитаемые имена кнопок для журнала.
ИМЕНА_КНОПОК = {
    "clarify": "Уточнить",
    "continue": "Продолжить",
    "new_question": "Новый вопрос",
    "social": "Общение",
    "exit": "Выход",
    "review": "Отзыв",
    "cancel_payment": "Отмена оплаты",
    "check_payment": "Проверить платёж",
    "rev_ok": "Одобрить отзыв",
    "rev_no": "Отклонить отзыв",
}

ИМЕНА_КРЕДИТОВ = {
    "free": "бесплатный",
    "bonus": "бонусный",
    "paid": "оплаченный",
}

ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ = {
    "new_question": "новый вопрос",
    "continue": "продолжение темы",
}


def kratko(text: str | None, limit: int = 240) -> str:
    """Короткий фрагмент текста для журнала, без переносов."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def imya_knopki(cmd: str) -> str:
    return ИМЕНА_КНОПОК.get(cmd, cmd or "неизвестно")


def nastroit_zhurnal() -> logging.Logger:
    """Включает подробный журнал. Повторный вызов ничего не ломает."""
    global _CONFIGURED
    from app.config import get_settings

    logger = logging.getLogger("app")
    if _CONFIGURED:
        return logger

    settings = get_settings()
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)

    handlers: list[logging.Handler] = [console]

    if settings.log_to_file:
        log_dir = Path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Чужие библиотеки не должны забивать журнал отладкой HTTP.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yookassa").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    _CONFIGURED = True
    logger.setLevel(level)
    return logger


def zhurnal_zapuska() -> None:
    """Пишет сводку настроек при старте, без секретов."""
    from app.config import get_settings

    settings = get_settings()
    logger = logging.getLogger("app")
    logger.info("=== Бот «Новая Игра» запускается ===")
    logger.info("Адрес: %s:%s", settings.host, settings.port)
    logger.info("База данных: %s", settings.database_url)
    logger.info("Сообщество ВК id: %s", settings.vk_group_id or "не задан")
    logger.info("Токен ВК: %s", "задан" if settings.vk_token else "НЕ ЗАДАН")
    if settings.uses_vk_longpoll:
        logger.info("События ВК: Bots Long Poll (туннель для ВК не нужен)")
    else:
        logger.info("События ВК: Callback API (нужны HTTPS-туннель и подтверждение)")
        logger.info(
            "Секрет Callback API: %s",
            "задан" if settings.vk_secret else "не задан",
        )
        logger.info(
            "Строка подтверждения ВК: %s",
            "задана" if settings.vk_confirmation else "не задана",
        )
    logger.info("Администратор ВК id: %s", settings.admin_vk_id or "не задан")
    logger.info(
        "Общий чат: %s, peer_id %s",
        "ссылка задана" if settings.community_chat_url else "ссылка не задана",
        settings.community_chat_peer_id or "не задан",
    )
    if settings.llm_stub:
        logger.info("ИИ: заглушка (LLM_STUB=true), DeepSeek не вызывается")
    elif settings.deepseek_api_key:
        logger.info("ИИ: DeepSeek, модель %s", settings.deepseek_model)
    else:
        logger.warning("ИИ: ключ DeepSeek не задан — ответы не получатся")
    if not settings.payments_enabled:
        logger.info("Оплата: выключена (PAYMENTS_ENABLED=false)")
    elif settings.payments_live:
        logger.info("Оплата: ЮKassa (боевые ключи), цена %s ₽", settings.price_rub)
    else:
        logger.info(
            "Оплата: stub без ключей ЮKassa, цена %s ₽, ссылка %s",
            settings.price_rub,
            settings.yookassa_payment_url,
        )
    if settings.log_to_file:
        logger.info("Файл журнала: %s/bot.log", settings.log_dir)
    logger.info("Уровень журнала: %s", settings.log_level.upper())
