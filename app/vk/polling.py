"""Bots Long Poll: бот сам запрашивает события ВК, без публичного HTTPS и Callback API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from vkbottle import API
from vkbottle.polling import BotPolling

from app.config import get_settings
from app.db.session import create_session
from app.vk.handlers import handle_vk_event

logger = logging.getLogger(__name__)


async def _ensure_longpoll_settings(api: API, group_id: int) -> None:
    """Включает Long Poll и нужные типы событий в сообществе."""
    await api.request(
        "groups.setLongPollSettings",
        {
            "group_id": group_id,
            "enabled": 1,
            "api_version": "5.199",
            "message_new": 1,
            "message_event": 1,
        },
    )
    logger.info(
        "Long Poll API сообщества %s: включён (message_new, message_event)",
        group_id,
    )


async def _resolve_group_id(api: API) -> int:
    settings = get_settings()
    if settings.vk_group_id:
        return settings.vk_group_id
    response = (await api.request("groups.getById", {}))["response"]
    groups = response.get("groups") or []
    if not groups:
        raise RuntimeError(
            "Не удалось определить id сообщества. Задайте VK_GROUP_ID в .env "
            "или используйте ключ сообщества (не пользовательский)."
        )
    return int(groups[0]["id"])


async def _process_update(api: API, update: dict[str, Any]) -> None:
    event_type = update.get("type")
    logger.info("ВК событие (Long Poll): %s", event_type or "без типа")
    session = create_session()
    try:
        await handle_vk_event(session, api, update)
        session.commit()
        logger.debug("Событие ВК %s обработано и записано в базу", event_type)
    except Exception:
        session.rollback()
        logger.exception("Ошибка при обработке события ВК типа %s", event_type)
    finally:
        session.close()


async def run_vk_longpoll(api: API) -> None:
    """Бесконечный опрос Bots Long Poll. Отмена задачи — штатная остановка."""
    group_id = await _resolve_group_id(api)
    try:
        await _ensure_longpoll_settings(api, group_id)
    except Exception:
        logger.exception(
            "Не удалось включить Long Poll через API. "
            "Проверьте в сообществе: Управление → Работа с API → Long Poll API "
            "(включить и события «Входящее сообщение», «Действие с сообщением»)."
        )
        raise

    polling = BotPolling(api=api, group_id=group_id, wait=25, skip_old_events=True)
    logger.info("=== Ожидаю события ВК через Bots Long Poll (сообщество %s) ===", group_id)

    try:
        async for event in polling.listen():
            for update in event.get("updates") or []:
                # Параллельно, как в vkbottle: одно событие не блокирует следующие.
                asyncio.create_task(_process_update(api, update))
    except asyncio.CancelledError:
        polling.stop()
        logger.info("Long Poll остановлен")
        raise
