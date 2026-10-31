from app.billing.yookassa import apply_succeeded_payment, create_payment, is_stub_payment_id
from app.config import get_settings
from app.db.models import Payment, User


def test_apply_new_question_payment():
    user = User(
        vk_id=5,
        free_questions=0,
        free_clarifications=0,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        status="awaiting_payment",
        pending_payment_id="pay-1",
    )
    record = Payment(
        yookassa_id="pay-1",
        vk_user_id=5,
        action="new_question",
        status="pending",
        amount="100.00",
    )
    apply_succeeded_payment(user, record)
    assert record.status == "succeeded"
    assert user.paid_questions == 1
    assert user.status == "awaiting_question"
    assert user.pending_payment_id is None


def test_apply_succeeded_payment_keeps_pending_text():
    user = User(
        vk_id=8,
        free_questions=0,
        free_clarifications=0,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        status="awaiting_payment",
        pending_payment_id="pay-3",
        pending_text="Сохранённый вопрос про работу и страх.",
    )
    record = Payment(
        yookassa_id="pay-3",
        vk_user_id=8,
        action="new_question",
        status="pending",
        amount="100.00",
    )
    apply_succeeded_payment(user, record)
    assert user.paid_questions == 1
    assert user.pending_text == "Сохранённый вопрос про работу и страх."


def test_apply_continue_payment():
    user = User(
        vk_id=6,
        free_questions=0,
        free_clarifications=0,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        status="awaiting_payment",
        pending_payment_id="pay-2",
    )
    record = Payment(
        yookassa_id="pay-2",
        vk_user_id=6,
        action="continue",
        status="pending",
        amount="100.00",
    )
    apply_succeeded_payment(user, record)
    assert user.paid_continues == 1
    assert user.status == "awaiting_clarification"


def test_create_stub_payment_without_keys(monkeypatch):
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "")
    get_settings.cache_clear()
    user = User(
        vk_id=7,
        free_questions=0,
        free_clarifications=0,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        status="active",
    )
    record = create_payment(user, "new_question")
    assert is_stub_payment_id(record.yookassa_id)
    assert record.confirmation_url == "https://yookassa.ru"
    assert user.status == "awaiting_payment"
    assert user.pending_payment_id == record.yookassa_id
    get_settings.cache_clear()
