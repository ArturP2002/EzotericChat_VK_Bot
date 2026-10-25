import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.models import Base, Review
from app.services.dialog import DialogService
from app.services.reviews import handle_admin_decision
from app.services.users import get_or_create_user
from app.vk import texts


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []

    async def send(self, user_id: int, text: str, keyboard: str | None = None) -> None:
        self.sent.append((user_id, text, keyboard))

    async def typing(self, user_id: int) -> None:
        return None


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    db = factory()
    yield db
    db.close()


@pytest.fixture
def dialog(session, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_STUB", "true")
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "")
    get_settings.cache_clear()
    sender = FakeSender()
    service = DialogService(session, sender)
    service.settings = get_settings()
    return service, sender


@pytest.mark.asyncio
async def test_welcome_then_free_question(dialog, session):
    service, sender = dialog
    await service.on_text(10, "привет")
    assert texts.WELCOME in sender.sent[0][1]
    user = get_or_create_user(session, 10)
    assert user.welcomed is True
    assert user.free_questions == 1

    sender.sent.clear()
    await service.on_text(10, "Не могу уволиться с работы, уже год боюсь сделать шаг.")
    user = get_or_create_user(session, 10)
    assert user.free_questions == 0
    assert user.status == "active"
    joined = "\n".join(item[1] for item in sender.sent)
    assert "Если хотите, могу" in joined
    assert "Код " not in joined


@pytest.mark.asyncio
async def test_free_clarify_then_stub_payment_and_check(dialog, session):
    service, sender = dialog
    await service.on_text(11, "Застрял в работе, боюсь уйти и боюсь остаться.")
    user = get_or_create_user(session, 11)
    assert user.free_questions == 0
    assert user.free_clarifications == 1

    sender.sent.clear()
    await service.on_text(11, "Страх ещё и из-за родителей: они всю жизнь терпели.")
    user = get_or_create_user(session, 11)
    assert user.free_clarifications == 0
    assert user.status == "active"

    sender.sent.clear()
    await service.on_text(11, "А что делать с чувством вины, если всё же уйду?")
    user = get_or_create_user(session, 11)
    assert user.status == "awaiting_payment"
    assert user.pending_payment_id
    assert "yookassa.ru" in (user.pending_payment_url or "")
    joined = "\n".join(item[1] for item in sender.sent)
    assert "Проверить платёж" in joined
    kb = json.loads(sender.sent[-1][2] or "{}")
    labels = [btn["action"]["label"] for row in kb["buttons"] for btn in row]
    assert "Оплатить" in labels
    assert "Проверить платёж" in labels
    assert any("check_payment" in str(btn["action"].get("payload", "")) for row in kb["buttons"] for btn in row)

    sender.sent.clear()
    await service.on_button(11, {"cmd": "check_payment"})
    user = get_or_create_user(session, 11)
    assert user.status == "awaiting_clarification"
    assert user.paid_continues == 1
    assert texts.PAYMENT_OK_CONTINUE in sender.sent[-1][1]


@pytest.mark.asyncio
async def test_exit_resets_topic(dialog, session):
    service, sender = dialog
    await service.on_text(12, "Боюсь менять работу, будто поле держит.")
    await service.on_button(12, {"cmd": "exit"})
    user = get_or_create_user(session, 12)
    assert user.status == "idle"
    assert texts.EXITED in sender.sent[-1][1]


@pytest.mark.asyncio
async def test_first_ask_question_button_does_not_mention_closed_topic(dialog, session):
    service, sender = dialog
    await service.on_text(14, "привет")
    sender.sent.clear()
    await service.on_button(14, {"cmd": "new_question"})
    user = get_or_create_user(session, 14)
    assert user.status == "awaiting_question"
    assert sender.sent[-1][1] == texts.ASK_QUESTION
    assert "Предыдущая тема закрыта" not in sender.sent[-1][1]
    keyboard = sender.sent[-1][2] or ""
    assert "Задать вопрос" not in keyboard
    assert "Новый вопрос" not in keyboard


@pytest.mark.asyncio
async def test_repeat_ask_question_is_short(dialog, session):
    service, sender = dialog
    await service.on_text(16, "привет")
    await service.on_button(16, {"cmd": "new_question"})
    sender.sent.clear()
    await service.on_button(16, {"cmd": "new_question"})
    assert sender.sent[-1][1] == texts.WAITING_FOR_QUESTION
    assert sender.sent[-1][2] is None


@pytest.mark.asyncio
async def test_new_question_after_topic_mentions_closed(dialog, session):
    service, sender = dialog
    await service.on_text(15, "Боюсь менять работу уже много лет и не вижу выхода.")
    user = get_or_create_user(session, 15)
    user.bonus_questions = 1  # ещё один кредит, чтобы не уйти в оплату
    session.flush()
    sender.sent.clear()
    await service.on_button(15, {"cmd": "new_question"})
    user = get_or_create_user(session, 15)
    assert user.status == "awaiting_question"
    assert sender.sent[-1][1] == texts.ASK_NEW_QUESTION
    keyboard = sender.sent[-1][2] or ""
    assert "Задать вопрос" not in keyboard
    assert "Новый вопрос" not in keyboard


@pytest.mark.asyncio
async def test_crisis_does_not_spend_credit(dialog, session):
    service, sender = dialog
    await service.on_text(13, "привет")
    sender.sent.clear()
    await service.on_text(13, "Хочу умереть, не знаю как дальше")
    user = get_or_create_user(session, 13)
    assert user.free_questions == 1
    assert texts.CRISIS in sender.sent[-1][1]


@pytest.mark.asyncio
async def test_review_grants_bonus_after_approval(dialog, session):
    service, sender = dialog
    await service.on_text(20, "Боюсь менять работу уже много лет и не вижу выхода.")
    await service.on_button(20, {"cmd": "review"})
    await service.on_text(
        20,
        "Я заметил страх и смог сделать маленький шаг: поговорил с коллегой.",
    )
    review = session.query(Review).one()
    assert review.status == "pending"
    await handle_admin_decision(session, sender, review.id, True, admin_id=99)
    user = get_or_create_user(session, 20)
    assert user.bonus_questions == 1
    assert texts.REVIEW_APPROVED in sender.sent[-2][1]
