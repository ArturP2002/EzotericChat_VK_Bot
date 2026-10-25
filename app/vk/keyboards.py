"""Клавиатуры лички: после ответа, в простое, ожидание вопроса, оплата, модерация."""

import json

from vkbottle import Callback, Keyboard, KeyboardButtonColor, OpenLink

from app.config import get_settings
from app.db.models import User
from app.services.entitlements import (
    available_continues,
    available_questions,
    can_submit_review,
)


def _payload(data: dict) -> str:
    """ВК принимает payload кнопки строкой JSON не длиннее 255 символов."""
    return json.dumps(data, ensure_ascii=False)


def _social_and_exit(kb: Keyboard) -> None:
    settings = get_settings()
    chat_url = settings.community_chat_url.strip()
    if chat_url:
        kb.add(OpenLink(chat_url, "Общение"))
    else:
        kb.add(Callback("Общение", _payload({"cmd": "social"})))
    kb.add(Callback("Выход", _payload({"cmd": "exit"})), KeyboardButtonColor.NEGATIVE)


def after_answer_keyboard(user: User, *, topic_active: bool) -> str:
    settings = get_settings()
    price = settings.price_rub
    kb = Keyboard(inline=True)

    if topic_active:
        if available_continues(user) > 0:
            label = "Уточнить" if user.free_clarifications > 0 else "Продолжить"
            kb.add(Callback(label, _payload({"cmd": "clarify"})), KeyboardButtonColor.PRIMARY)
        else:
            kb.add(
                Callback(f"Продолжить ({price} ₽)", _payload({"cmd": "continue"})),
                KeyboardButtonColor.PRIMARY,
            )

    if available_questions(user) > 0:
        # В простое ещё нет темы — «Задать вопрос»; после разбора — «Новый вопрос».
        q_label = "Новый вопрос" if topic_active else "Задать вопрос"
        kb.add(Callback(q_label, _payload({"cmd": "new_question"})))
    else:
        kb.add(Callback(f"Новый вопрос ({price} ₽)", _payload({"cmd": "new_question"})))

    kb.row()
    _social_and_exit(kb)

    if can_submit_review(user):
        kb.row()
        kb.add(Callback("Отзыв о работе", _payload({"cmd": "review"})))

    return kb.get_json()


def idle_keyboard(user: User) -> str:
    return after_answer_keyboard(user, topic_active=False)


def awaiting_question_keyboard() -> str:
    """Ждём текст вопроса: без повторной кнопки «Задать вопрос»."""
    kb = Keyboard(inline=True)
    _social_and_exit(kb)
    return kb.get_json()


def payment_keyboard(url: str) -> str:
    kb = Keyboard(inline=True)
    kb.add(OpenLink(url, "Оплатить"), KeyboardButtonColor.PRIMARY)
    kb.row()
    kb.add(
        Callback("Проверить платёж", _payload({"cmd": "check_payment"})),
        KeyboardButtonColor.POSITIVE,
    )
    kb.row()
    kb.add(Callback("Отмена", _payload({"cmd": "cancel_payment"})), KeyboardButtonColor.NEGATIVE)
    return kb.get_json()


def admin_review_keyboard(review_id: int) -> str:
    kb = Keyboard(inline=True)
    kb.add(Callback("Одобрить", _payload({"cmd": "rev_ok", "id": review_id})), KeyboardButtonColor.POSITIVE)
    kb.add(Callback("Отклонить", _payload({"cmd": "rev_no", "id": review_id})), KeyboardButtonColor.NEGATIVE)
    return kb.get_json()
