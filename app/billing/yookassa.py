"""Платежи ЮKassa: создание ссылки, повтор висящего платежа, зачёт успеха.

Без shopId/секрета создаётся локальный stub-платёж с той же моделью статусов;
кнопка «Проверить платёж» (только в этом режиме) засчитывает его как успешный.
"""

import logging
import uuid
from typing import Any

from yookassa import Configuration, Payment as YooPayment

from app.config import get_settings
from app.db.models import Payment, User
from app.logging_setup import ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ
from app.services.entitlements import grant_continue_credit, grant_question_credit

logger = logging.getLogger(__name__)

STUB_PREFIX = "stub-"


def is_stub_payment_id(payment_id: str | None) -> bool:
    return bool(payment_id) and str(payment_id).startswith(STUB_PREFIX)


def configure() -> None:
    settings = get_settings()
    if settings.payments_live:
        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key


def create_payment(user: User, action: str) -> Payment:
    settings = get_settings()
    if not settings.payments_live:
        return _create_stub_payment(user, action)

    configure()
    idempotency_key = str(uuid.uuid4())
    description = (
        "Новый вопрос в «Новая Игра»"
        if action == "new_question"
        else "Продолжение разбора в «Новая Игра»"
    )
    logger.info(
        "Создаю платёж ЮKassa: пользователь %s, «%s», сумма %s ₽",
        user.vk_id,
        ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(action, action),
        settings.price_rub,
    )
    created = YooPayment.create(
        {
            "amount": {"value": settings.price_value, "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": settings.yookassa_return_url,
            },
            "capture": True,
            "description": description,
            "metadata": {
                "vk_user_id": str(user.vk_id),
                "action": action,
            },
        },
        idempotency_key,
    )
    confirmation_url = None
    confirmation = getattr(created, "confirmation", None)
    if confirmation is not None:
        confirmation_url = getattr(confirmation, "confirmation_url", None)
    record = Payment(
        yookassa_id=created.id,
        vk_user_id=user.vk_id,
        action=action,
        status=created.status,
        amount=settings.price_value,
        confirmation_url=confirmation_url,
    )
    _attach_pending(user, action, record.yookassa_id, confirmation_url)
    logger.info(
        "ЮKassa приняла платёж %s, статус %s, ссылка %s",
        created.id,
        created.status,
        "есть" if confirmation_url else "нет",
    )
    return record


def _create_stub_payment(user: User, action: str) -> Payment:
    settings = get_settings()
    payment_id = f"{STUB_PREFIX}{uuid.uuid4()}"
    confirmation_url = settings.yookassa_payment_url.strip() or "https://yookassa.ru"
    logger.info(
        "Создаю stub-платёж %s: пользователь %s, «%s», сумма %s ₽",
        payment_id,
        user.vk_id,
        ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(action, action),
        settings.price_rub,
    )
    record = Payment(
        yookassa_id=payment_id,
        vk_user_id=user.vk_id,
        action=action,
        status="pending",
        amount=settings.price_value,
        confirmation_url=confirmation_url,
    )
    _attach_pending(user, action, payment_id, confirmation_url)
    return record


def _attach_pending(
    user: User,
    action: str,
    payment_id: str,
    confirmation_url: str | None,
) -> None:
    user.pending_action = action
    user.pending_payment_id = payment_id
    user.pending_payment_url = confirmation_url
    user.status = "awaiting_payment"


def reuse_pending(user: User, action: str) -> Payment | None:
    """Пока платёж висит — не плодим новую ссылку."""
    if (
        user.status == "awaiting_payment"
        and user.pending_action == action
        and user.pending_payment_id
        and user.pending_payment_url
    ):
        logger.info(
            "Пользователь %s уже ждёт оплату %s, отдаю ту же ссылку",
            user.vk_id,
            user.pending_payment_id,
        )
        return Payment(
            yookassa_id=user.pending_payment_id,
            vk_user_id=user.vk_id,
            action=action,
            status="pending",
            amount=get_settings().price_value,
            confirmation_url=user.pending_payment_url,
        )
    return None


def apply_succeeded_payment(user: User, record: Payment) -> None:
    if record.status == "succeeded":
        return
    record.status = "succeeded"
    if record.action == "new_question":
        grant_question_credit(user, "paid")
        user.status = "awaiting_question"
    else:
        grant_continue_credit(user)
        user.status = "awaiting_clarification"
    if user.pending_payment_id == record.yookassa_id:
        user.pending_action = None
        user.pending_payment_id = None
        user.pending_payment_url = None
    logger.info(
        "Кредит начислен пользователю %s за «%s»",
        user.vk_id,
        ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(record.action, record.action),
    )


def parse_notification(body: dict[str, Any]) -> tuple[str, str] | None:
    obj = body.get("object") or {}
    payment_id = obj.get("id")
    status = obj.get("status")
    if not payment_id or not status:
        return None
    return str(payment_id), str(status)


def fetch_status(payment_id: str) -> str:
    if is_stub_payment_id(payment_id):
        # Stub остаётся pending, пока пользователь не нажмёт «Проверить платёж».
        return "pending"
    configure()
    remote = YooPayment.find_one(payment_id)
    return remote.status
