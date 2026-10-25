import json

from app.db.models import User
from app.vk.keyboards import after_answer_keyboard, awaiting_question_keyboard, payment_keyboard


def test_after_answer_has_clarify_when_free():
    user = User(
        vk_id=1,
        free_questions=0,
        free_clarifications=1,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        reviews=[],
    )
    data = json.loads(after_answer_keyboard(user, topic_active=True))
    labels = [btn["action"]["label"] for row in data["buttons"] for btn in row]
    assert "Уточнить" in labels
    assert "Новый вопрос (100 ₽)" in labels
    payloads = [btn["action"].get("payload") for row in data["buttons"] for btn in row]
    assert any(p == '{"cmd": "clarify"}' or p == '{"cmd":"clarify"}' or (isinstance(p, str) and "clarify" in p) for p in payloads)


def test_idle_keyboard_asks_first_question():
    user = User(
        vk_id=2,
        free_questions=1,
        free_clarifications=1,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        reviews=[],
    )
    data = json.loads(after_answer_keyboard(user, topic_active=False))
    labels = [btn["action"]["label"] for row in data["buttons"] for btn in row]
    assert "Задать вопрос" in labels
    assert "Новый вопрос" not in labels


def test_awaiting_question_keyboard_has_no_ask_cta():
    data = json.loads(awaiting_question_keyboard())
    labels = [btn["action"]["label"] for row in data["buttons"] for btn in row]
    assert "Задать вопрос" not in labels
    assert "Новый вопрос" not in labels
    assert "Выход" in labels


def test_payment_keyboard_has_link_and_check():
    data = json.loads(payment_keyboard("https://yookassa.ru/pay/1"))
    labels = [btn["action"]["label"] for row in data["buttons"] for btn in row]
    assert data["buttons"][0][0]["action"]["type"] == "open_link"
    assert data["buttons"][0][0]["action"]["link"] == "https://yookassa.ru/pay/1"
    assert "Проверить платёж" in labels
    assert "Отмена" in labels
    payloads = [btn["action"].get("payload", "") for row in data["buttons"] for btn in row]
    assert any("check_payment" in str(p) for p in payloads)
