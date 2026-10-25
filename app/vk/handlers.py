"""Разбор входящих событий ВК: текст в личке и нажатия inline-кнопок."""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session
from vkbottle import API

from app.config import get_settings
from app.logging_setup import imya_knopki, kratko
from app.services.dialog import DialogService
from app.services.locks import user_lock
from app.services.reviews import handle_admin_decision
from app.vk.sender import VkSender

logger = logging.getLogger(__name__)


def _payload(raw: Any) -> dict:
    """Payload кнопки ВК приходит строкой JSON или уже словарём."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Не удалось разобрать payload кнопки: %s", kratko(raw, 80))
            return {}
    return {}


def _message_text(message: dict) -> str:
    text = (message.get("text") or "").strip()
    payload = _payload(message.get("payload"))
    if payload.get("cmd") and not text:
        return ""
    return text


async def handle_vk_event(session: Session, api: API, event: dict) -> None:
    event_type = event.get("type")
    obj = event.get("object") or {}
    sender = VkSender(api)
    settings = get_settings()

    if event_type == "message_new":
        message = obj.get("message") or obj
        from_id = int(message.get("from_id") or 0)
        peer_id = int(message.get("peer_id") or from_id)
        if from_id <= 0:
            logger.debug("Пропускаю сообщение не от пользователя: from_id=%s", from_id)
            return
        # Беседа сообщества — не продукт, бот отвечает только в личке.
        if peer_id != from_id:
            logger.info(
                "Сообщение из беседы peer_id=%s от %s — в общем чате бот молчит",
                peer_id,
                from_id,
            )
            return
        text = _message_text(message)
        payload = _payload(message.get("payload"))
        logger.info(
            "Личка: пользователь %s написал «%s»",
            from_id,
            kratko(text) or "(пусто / только кнопка)",
        )
        async with user_lock(from_id):
            dialog = DialogService(session, sender)
            if payload.get("cmd"):
                logger.info(
                    "Пользователь %s нажал «%s» вместе с текстом",
                    from_id,
                    imya_knopki(str(payload.get("cmd"))),
                )
                await dialog.on_button(from_id, payload)
                if text:
                    await dialog.on_text(from_id, text)
            else:
                await dialog.on_text(from_id, text)
        return

    if event_type == "message_event":
        user_id = int(obj.get("user_id") or 0)
        peer_id = int(obj.get("peer_id") or user_id)
        event_id = str(obj.get("event_id") or "")
        payload = _payload(obj.get("payload"))
        if user_id <= 0:
            return
        try:
            await sender.answer_event(event_id, user_id, peer_id)
        except Exception:
            logger.exception(
                "Не удалось ответить ВК на нажатие кнопки пользователя %s",
                user_id,
            )

        cmd = str(payload.get("cmd") or "")
        logger.info("Кнопка: пользователь %s нажал «%s»", user_id, imya_knopki(cmd))
        async with user_lock(user_id):
            if cmd in {"rev_ok", "rev_no"} and user_id == settings.admin_vk_id:
                review_id = int(payload.get("id") or 0)
                logger.info(
                    "Администратор %s %s отзыв #%s",
                    user_id,
                    "одобряет" if cmd == "rev_ok" else "отклоняет",
                    review_id,
                )
                await handle_admin_decision(
                    session,
                    sender,
                    review_id,
                    approve=cmd == "rev_ok",
                    admin_id=user_id,
                )
                return
            if cmd in {"rev_ok", "rev_no"}:
                logger.warning(
                    "Нажатие модерации от %s проигнорировано: это не ADMIN_VK_ID",
                    user_id,
                )
                return
            dialog = DialogService(session, sender)
            await dialog.on_button(user_id, payload)
        return

    logger.debug("Событие ВК типа %s не обрабатывается", event_type)
