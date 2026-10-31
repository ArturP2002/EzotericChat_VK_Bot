"""Отправка сообщений в личку ВК. Длинный текст режется на части по лимиту 4096."""

import logging
import random

from vkbottle import API

from app.logging_setup import kratko
from app.vk.split import split_message

logger = logging.getLogger(__name__)


class VkSender:
    def __init__(self, api: API) -> None:
        self.api = api

    async def send(
        self,
        user_id: int,
        text: str,
        keyboard: str | None = None,
    ) -> None:
        await self.send_to_peer(user_id, text, keyboard=keyboard)

    async def send_to_peer(
        self,
        peer_id: int,
        text: str,
        keyboard: str | None = None,
    ) -> None:
        parts = split_message(text)
        last = len(parts) - 1
        logger.info(
            "Исходящее peer_id=%s (%s част.) «%s»%s",
            peer_id,
            len(parts),
            kratko(text),
            ", с клавиатурой" if keyboard else "",
        )
        for i, part in enumerate(parts):
            kwargs = {
                "peer_id": peer_id,
                "random_id": random.randint(1, 2_147_483_647),
                "message": part or ".",
                "dont_parse_links": 0,
            }
            if keyboard and i == last:
                kwargs["keyboard"] = keyboard
            try:
                await self.api.messages.send(**kwargs)
            except Exception:
                logger.exception(
                    "Не отправилось сообщение peer_id=%s (часть %s/%s)",
                    peer_id,
                    i + 1,
                    len(parts),
                )
                raise

    async def typing(self, user_id: int) -> None:
        try:
            await self.api.messages.set_activity(user_id=user_id, type="typing")
        except Exception:
            logger.debug("Не удалось показать «печатает» пользователю %s", user_id, exc_info=True)

    async def answer_event(self, event_id: str, user_id: int, peer_id: int) -> None:
        """Снимает «крутилку» на inline-кнопке."""
        await self.api.messages.send_message_event_answer(
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id,
        )
