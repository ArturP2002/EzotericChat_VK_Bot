"""Сценарий лички: приветствие, вопросы, уточнения, оплата, выход."""

import asyncio
import logging
from typing import Literal

from sqlalchemy.orm import Session

from app.billing.yookassa import (
    apply_succeeded_payment,
    create_payment,
    fetch_status,
    is_stub_payment_id,
    reuse_pending,
)
from app.config import get_settings
from app.db.models import Payment, Topic, TopicMessage, User
from app.llm.deepseek import DeepSeekError, complete
from app.logging_setup import ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ, ИМЕНА_КРЕДИТОВ, imya_knopki, kratko
from app.services.entitlements import (
    available_continues,
    available_questions,
    consume_continue,
    consume_question,
    is_smalltalk,
    refund,
)
from app.services.reviews import begin_review, notify_admin, save_review
from app.services.users import active_topic, close_active_topic, get_or_create_user, start_topic
from app.vk import texts
from app.vk.crisis import is_crisis
from app.vk.keyboards import (
    after_answer_keyboard,
    awaiting_question_keyboard,
    idle_keyboard,
    payment_keyboard,
)
from app.vk.sender import VkSender

logger = logging.getLogger(__name__)

Action = Literal["new_question", "continue"]


class DialogService:
    def __init__(self, session: Session, sender: VkSender) -> None:
        self.session = session
        self.sender = sender
        self.settings = get_settings()

    async def on_text(self, vk_id: int, text: str) -> None:
        user = get_or_create_user(self.session, vk_id)
        body = (text or "").strip()
        logger.info(
            "Текст от %s, статус «%s», бесплатных вопросов %s, уточнений %s",
            vk_id,
            user.status,
            user.free_questions + user.bonus_questions + user.paid_questions,
            user.free_clarifications + user.paid_continues,
        )

        if not user.welcomed:
            user.welcomed = True
            logger.info("Первый вход пользователя %s — отправляю приветствие", vk_id)
            await self.sender.send(vk_id, texts.WELCOME, keyboard=idle_keyboard(user))
            if not body or is_smalltalk(body):
                user.status = "idle"
                return
            # В первом сообщении уже сформулирован вопрос — разбираем его сразу.

        if is_crisis(body):
            logger.warning("Кризисная формулировка от пользователя %s — без разбора и списания", vk_id)
            await self.sender.send(vk_id, texts.CRISIS)
            return

        if user.status == "awaiting_review":
            await self._store_review(user, body)
            return

        if user.status == "awaiting_payment":
            logger.info("Пользователь %s пишет, пока ждём оплату — напоминаю ссылку", vk_id)
            await self._remind_payment(user)
            return

        if user.status in {"awaiting_question", "idle"}:
            if is_smalltalk(body):
                logger.info("Короткая реплика от %s в статусе %s — прошу вопрос", vk_id, user.status)
                if user.status == "awaiting_question":
                    await self.sender.send(
                        vk_id,
                        texts.NOT_A_QUESTION,
                        keyboard=awaiting_question_keyboard(),
                    )
                else:
                    await self.sender.send(
                        vk_id,
                        texts.ASK_QUESTION,
                        keyboard=idle_keyboard(user),
                    )
                return
            await self._handle_new_question(user, body)
            return

        if user.status == "awaiting_clarification":
            if is_smalltalk(body):
                await self.sender.send(vk_id, texts.ASK_CLARIFICATION)
                return
            await self._handle_continue(user, body)
            return

        if user.status == "active":
            if is_smalltalk(body):
                await self.sender.send(vk_id, texts.THANKS_REPLY, keyboard=self._kb(user))
                return
            await self._handle_continue(user, body)
            return

        await self._handle_new_question(user, body)

    async def on_button(self, vk_id: int, payload: dict) -> None:
        user = get_or_create_user(self.session, vk_id)
        cmd = str(payload.get("cmd") or "")
        logger.info("Обработка кнопки «%s» для пользователя %s", imya_knopki(cmd), vk_id)

        if cmd == "exit":
            close_active_topic(self.session, user)
            user.status = "idle"
            user.pending_action = None
            logger.info("Пользователь %s вышел, тема закрыта", vk_id)
            await self.sender.send(vk_id, texts.EXITED, keyboard=idle_keyboard(user))
            return

        if cmd == "social":
            url = self.settings.community_chat_url.strip()
            msg = f"{texts.SOCIAL_CHAT}\n{url}" if url else texts.SOCIAL_CHAT_MISSING
            logger.info("Пользователь %s открывает «Общение», ссылка %s", vk_id, "есть" if url else "не задана")
            await self.sender.send(vk_id, msg, keyboard=self._kb(user))
            return

        if cmd == "review":
            message = begin_review(user)
            logger.info("Пользователь %s хочет оставить отзыв, новый статус %s", vk_id, user.status)
            await self.sender.send(vk_id, message)
            return

        if cmd == "cancel_payment":
            user.status = "active" if active_topic(self.session, user) else "idle"
            user.pending_action = None
            user.pending_payment_id = None
            user.pending_payment_url = None
            logger.info("Пользователь %s отменил ожидание оплаты, статус %s", vk_id, user.status)
            await self.sender.send(vk_id, "Оплату отменили.", keyboard=self._kb(user))
            return

        if cmd == "check_payment":
            await self._check_payment(user)
            return

        if cmd == "new_question":
            await self._request_new_question(user)
            return

        if cmd in {"clarify", "continue"}:
            await self._request_continue(user)
            return

        logger.warning("Неизвестная кнопка «%s» от пользователя %s", cmd, vk_id)

    async def on_payment_succeeded(self, vk_id: int, action: str) -> None:
        user = get_or_create_user(self.session, vk_id)
        logger.info(
            "Сообщаю пользователю %s, что оплата «%s» прошла",
            vk_id,
            ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(action, action),
        )
        if action == "new_question":
            user.status = "awaiting_question"
            await self.sender.send(
                vk_id,
                texts.PAYMENT_OK_QUESTION,
                keyboard=awaiting_question_keyboard(),
            )
        else:
            user.status = "awaiting_clarification"
            await self.sender.send(vk_id, texts.PAYMENT_OK_CONTINUE)

    async def _request_new_question(self, user: User) -> None:
        if available_questions(user) <= 0:
            await self._require_payment(user, "new_question")
            return

        had_topic = active_topic(self.session, user) is not None
        # Уже ждём текст — не дублируем длинное приглашение и те же кнопки.
        if user.status == "awaiting_question" and not had_topic:
            logger.info("Повтор «Задать вопрос» у %s — уже ждём текст", user.vk_id)
            await self.sender.send(user.vk_id, texts.WAITING_FOR_QUESTION)
            return

        close_active_topic(self.session, user)
        user.status = "awaiting_question"
        # Без прошлой темы не говорим, что её «закрыли» — это первый вопрос.
        prompt = texts.ASK_NEW_QUESTION if had_topic else texts.ASK_QUESTION
        logger.info(
            "Пользователь %s начинает вопрос с кредитом (была тема: %s)",
            user.vk_id,
            had_topic,
        )
        await self.sender.send(
            user.vk_id,
            prompt,
            keyboard=awaiting_question_keyboard(),
        )

    async def _request_continue(self, user: User) -> None:
        topic = active_topic(self.session, user)
        if topic is None:
            logger.info("Уточнение без активной темы у %s — прошу новый вопрос", user.vk_id)
            user.status = "idle"
            await self.sender.send(user.vk_id, texts.ASK_QUESTION, keyboard=idle_keyboard(user))
            return
        if available_continues(user) > 0:
            user.status = "awaiting_clarification"
            logger.info("Пользователь %s уточняет тему с кредитом продолжения", user.vk_id)
            await self.sender.send(user.vk_id, texts.ASK_CLARIFICATION)
            return
        await self._require_payment(user, "continue")

    async def _handle_new_question(self, user: User, text: str) -> None:
        if available_questions(user) <= 0:
            await self._require_payment(user, "new_question")
            return
        kind = consume_question(user)
        logger.info(
            "Списан %s вопрос у %s, осталось вопросов %s",
            ИМЕНА_КРЕДИТОВ.get(kind, kind),
            user.vk_id,
            available_questions(user),
        )
        topic = start_topic(self.session, user)
        await self._answer(user, topic, text, credit=("question", kind))

    async def _handle_continue(self, user: User, text: str) -> None:
        topic = active_topic(self.session, user)
        if topic is None:
            await self._handle_new_question(user, text)
            return
        if available_continues(user) <= 0:
            await self._require_payment(user, "continue")
            return
        kind = consume_continue(user)
        logger.info(
            "Списано %s уточнение у %s, осталось уточнений %s",
            ИМЕНА_КРЕДИТОВ.get(kind, kind),
            user.vk_id,
            available_continues(user),
        )
        await self._answer(user, topic, text, credit=("continue", kind))

    async def _answer(
        self,
        user: User,
        topic: Topic,
        text: str,
        credit: tuple[str, str],
    ) -> None:
        history = [{"role": msg.role, "content": msg.content} for msg in topic.messages]
        self.session.add(TopicMessage(topic_id=topic.id, role="user", content=text))
        self.session.flush()
        logger.info(
            "Запрос к ИИ: пользователь %s, тема %s, сообщений в истории %s, текст «%s»",
            user.vk_id,
            topic.id,
            len(history),
            kratko(text),
        )
        try:
            await self.sender.typing(user.vk_id)
            await self.sender.send(user.vk_id, texts.PROCESSING)
            answer = await complete(history, text)
        except DeepSeekError:
            logger.exception("ИИ не ответил пользователю %s — возвращаю кредит %s/%s", user.vk_id, *credit)
            refund(user, credit[1], credit[0])
            if topic.messages and topic.messages[-1].role == "user" and topic.messages[-1].content == text:
                self.session.delete(topic.messages[-1])
            await self.sender.send(user.vk_id, texts.LLM_UNAVAILABLE, keyboard=self._kb(user))
            return

        logger.info(
            "ИИ ответил пользователю %s, длина %s символов, начало «%s»",
            user.vk_id,
            len(answer),
            kratko(answer),
        )
        self.session.add(TopicMessage(topic_id=topic.id, role="assistant", content=answer))
        user.status = "active"
        await self.sender.send(user.vk_id, answer, keyboard=self._kb(user, topic_active=True))

    async def _require_payment(self, user: User, action: Action) -> None:
        human = ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(action, action)
        if not self.settings.payments_enabled:
            logger.info("Нужна оплата «%s» у %s, но оплата выключена", human, user.vk_id)
            await self.sender.send(user.vk_id, texts.PAYMENT_DISABLED, keyboard=self._kb(user))
            return
        pending = reuse_pending(user, action)
        if pending and pending.confirmation_url:
            logger.info("Повторно показываю ту же ссылку оплаты «%s» пользователю %s", human, user.vk_id)
            await self.sender.send(
                user.vk_id,
                texts.PAYMENT_PENDING,
                keyboard=payment_keyboard(pending.confirmation_url),
            )
            return
        try:
            record = await asyncio.to_thread(create_payment, user, action)
        except Exception:
            logger.exception("Не удалось создать платёж «%s» для %s", human, user.vk_id)
            await self.sender.send(
                user.vk_id,
                "Не получилось создать оплату. Попробуйте позже.",
                keyboard=self._kb(user),
            )
            return
        self.session.add(record)
        logger.info(
            "Создан платёж %s на %s ₽, действие «%s», пользователь %s",
            record.yookassa_id,
            self.settings.price_rub,
            human,
            user.vk_id,
        )
        url = record.confirmation_url or self.settings.yookassa_payment_url
        body = texts.PAYMENT_CREATED.format(price=self.settings.price_rub)
        await self.sender.send(user.vk_id, body, keyboard=payment_keyboard(url))

    async def _check_payment(self, user: User) -> None:
        payment_id = user.pending_payment_id
        if user.status != "awaiting_payment" or not payment_id:
            await self.sender.send(user.vk_id, texts.PAYMENT_NOT_FOUND, keyboard=self._kb(user))
            return

        record = (
            self.session.query(Payment)
            .filter_by(yookassa_id=payment_id, vk_user_id=user.vk_id)
            .order_by(Payment.id.desc())
            .first()
        )
        if record is None:
            logger.warning("Платёж %s не найден в базе для пользователя %s", payment_id, user.vk_id)
            await self.sender.send(user.vk_id, texts.PAYMENT_NOT_FOUND, keyboard=self._kb(user))
            return

        if record.status == "succeeded":
            await self.on_payment_succeeded(user.vk_id, record.action)
            return

        if is_stub_payment_id(payment_id):
            # Stub: «Проверить платёж» = успешная оплата (как webhook в бою).
            remote_status = "succeeded"
            logger.info("Stub-платёж %s засчитан по кнопке «Проверить платёж»", payment_id)
        else:
            try:
                remote_status = await asyncio.to_thread(fetch_status, payment_id)
            except Exception:
                logger.exception("Не удалось запросить статус платежа %s", payment_id)
                url = user.pending_payment_url or self.settings.yookassa_payment_url
                await self.sender.send(
                    user.vk_id,
                    texts.PAYMENT_PENDING,
                    keyboard=payment_keyboard(url),
                )
                return

        if remote_status != "succeeded":
            logger.info("Платёж %s ещё не успешен (%s)", payment_id, remote_status)
            url = user.pending_payment_url or record.confirmation_url or self.settings.yookassa_payment_url
            await self.sender.send(
                user.vk_id,
                texts.PAYMENT_PENDING,
                keyboard=payment_keyboard(url),
            )
            return

        apply_succeeded_payment(user, record)
        self.session.flush()
        await self.on_payment_succeeded(user.vk_id, record.action)

    async def _remind_payment(self, user: User) -> None:
        url = user.pending_payment_url or self.settings.yookassa_payment_url
        await self.sender.send(
            user.vk_id,
            texts.PAYMENT_PENDING,
            keyboard=payment_keyboard(url),
        )

    async def _store_review(self, user: User, text: str) -> None:
        if is_smalltalk(text) or len(text) < 20:
            logger.info("Отзыв пользователя %s слишком короткий", user.vk_id)
            await self.sender.send(user.vk_id, texts.REVIEW_EMPTY)
            return
        review = save_review(self.session, user, text)
        self.session.commit()
        logger.info("Отзыв #%s от %s сохранён и уходит администратору", review.id, user.vk_id)
        await notify_admin(self.sender, user, review)
        await self.sender.send(user.vk_id, texts.REVIEW_RECEIVED, keyboard=self._kb(user))

    def _kb(self, user: User, topic_active: bool | None = None) -> str:
        if user.status == "awaiting_question":
            return awaiting_question_keyboard()
        if user.status == "idle":
            return idle_keyboard(user)
        if topic_active is None:
            topic_active = active_topic(self.session, user) is not None
        return after_answer_keyboard(user, topic_active=topic_active)
