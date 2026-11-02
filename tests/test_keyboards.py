import json

from app.config import get_settings
from app.db.models import User
from app.vk.keyboards import after_answer_keyboard, awaiting_question_keyboard, payment_keyboard


def _labels(keyboard_json: str) -> list[str]:
    data = json.loads(keyboard_json)
    return [btn["action"]["label"] for row in data["buttons"] for btn in row]


def _buttons(keyboard_json: str) -> list[dict]:
    data = json.loads(keyboard_json)
    return [btn for row in data["buttons"] for btn in row]


def _user(**kwargs) -> User:
    defaults = dict(
        vk_id=1,
        free_questions=0,
        free_clarifications=1,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        reviews=[],
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_after_answer_has_no_clarify_and_red_new_question():
    user = _user(free_questions=0, free_clarifications=1)
    kb = after_answer_keyboard(user, topic_active=True)
    labels = _labels(kb)
    assert "Уточнить" not in labels
    assert "Продолжить" not in labels
    assert "Новый вопрос (100 ₽)" in labels
    assert "Отзыв" in labels
    assert "Общение" in labels
    assert "Выход" in labels

    colors = {btn["action"]["label"]: btn.get("color") for btn in _buttons(kb)}
    assert colors["Новый вопрос (100 ₽)"] == "negative"
    assert colors["Выход"] in (None, "secondary")
    payloads = [btn["action"].get("payload") for btn in _buttons(kb)]
    assert not any("clarify" in str(p) for p in payloads)


def test_idle_keyboard_asks_first_question():
    user = _user(vk_id=2, free_questions=1)
    labels = _labels(after_answer_keyboard(user, topic_active=False))
    assert "Задать вопрос" in labels
    assert "Новый вопрос" not in labels
    colors = {btn["action"]["label"]: btn.get("color") for btn in _buttons(after_answer_keyboard(user, topic_active=False))}
    assert colors["Задать вопрос"] == "negative"


def test_awaiting_question_keyboard_has_no_ask_cta():
    labels = _labels(awaiting_question_keyboard())
    assert "Задать вопрос" not in labels
    assert "Новый вопрос" not in labels
    assert "Выход" in labels
    assert "Общение" in labels


def test_payment_keyboard_stub_has_check(monkeypatch):
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "")
    get_settings.cache_clear()
    data = json.loads(payment_keyboard("https://yookassa.ru/pay/1"))
    labels = [btn["action"]["label"] for row in data["buttons"] for btn in row]
    assert data["buttons"][0][0]["action"]["type"] == "open_link"
    assert data["buttons"][0][0]["action"]["link"] == "https://yookassa.ru/pay/1"
    assert "Проверить платёж" in labels
    assert "Отмена" in labels
    payloads = [btn["action"].get("payload", "") for row in data["buttons"] for btn in row]
    assert any("check_payment" in str(p) for p in payloads)
    get_settings.cache_clear()


def test_payment_keyboard_live_has_no_check(monkeypatch):
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "shop")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "secret")
    get_settings.cache_clear()
    labels = _labels(payment_keyboard("https://yookassa.ru/pay/1"))
    assert "Оплатить" in labels
    assert "Отмена" in labels
    assert "Проверить платёж" not in labels
    get_settings.cache_clear()
