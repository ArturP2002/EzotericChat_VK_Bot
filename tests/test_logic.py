from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Review, User
from app.llm.prompt import sanitize_answer
from app.services.entitlements import (
    NoCredit,
    available_continues,
    available_questions,
    can_submit_review,
    consume_continue,
    consume_question,
    is_smalltalk,
    refund,
)
from app.vk.crisis import is_crisis
from app.vk.split import split_message


def test_split_short():
    assert split_message("hello") == ["hello"]


def test_split_long_by_paragraph():
    chunk = "абзац.\n\n"
    text = chunk * 800
    parts = split_message(text, limit=500)
    assert all(len(p) <= 500 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_crisis_positive():
    assert is_crisis("Я хочу умереть, не вижу смысла")
    assert is_crisis("Подумываю покончить с собой")


def test_crisis_negative():
    assert not is_crisis("Боюсь увольняться с работы, застрял")


def test_smalltalk():
    assert is_smalltalk("привет")
    assert is_smalltalk("спасибо")
    assert not is_smalltalk("Не могу уволиться, уже год боюсь")


def test_sanitize_strips_codes():
    raw = "Смотри Код 10. ПРЕЛОМЛЕНИЕ и Код 19. СТРАХ в этой ситуации."
    cleaned = sanitize_answer(raw)
    assert "Код" not in cleaned
    assert "ПРЕЛОМЛЕНИЕ" not in cleaned
    assert "фильтр восприятия" in cleaned
    assert "Если хотите, могу" in cleaned


def test_entitlements_consume_and_refund():
    user = User(
        vk_id=1,
        free_questions=1,
        free_clarifications=1,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
    )
    assert available_questions(user) == 1
    assert consume_question(user) == "free"
    assert available_questions(user) == 0
    user.bonus_questions = 1
    assert consume_question(user) == "bonus"
    user.paid_questions = 1
    assert consume_question(user) == "paid"
    with pytest.raises(NoCredit):
        consume_question(user)
    refund(user, "paid", "question")
    assert user.paid_questions == 1

    assert consume_continue(user) == "free"
    assert available_continues(user) == 0
    user.paid_continues = 1
    assert consume_continue(user) == "paid"


def test_review_cooldown(monkeypatch):
    user = User(
        vk_id=2,
        free_questions=0,
        free_clarifications=0,
        bonus_questions=0,
        paid_questions=0,
        paid_continues=0,
        last_bonus_at=datetime.now(timezone.utc).replace(tzinfo=None),
        reviews=[],
    )
    assert can_submit_review(user) is False
    user.last_bonus_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    assert can_submit_review(user) is True
    user.reviews = [Review(text="x", status="pending")]
    assert can_submit_review(user) is False
