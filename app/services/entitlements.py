"""Лимиты: бесплатный вход, бонус за отзыв, оплаченные вопросы и уточнения."""

from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db.models import Review, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NoCredit(Exception):
    """Нет ни бесплатного, ни бонусного, ни оплаченного кредита."""


def available_questions(user: User) -> int:
    return user.free_questions + user.bonus_questions + user.paid_questions


def available_continues(user: User) -> int:
    return user.free_clarifications + user.paid_continues


def consume_question(user: User) -> str:
    if user.free_questions > 0:
        user.free_questions -= 1
        return "free"
    if user.bonus_questions > 0:
        user.bonus_questions -= 1
        return "bonus"
    if user.paid_questions > 0:
        user.paid_questions -= 1
        return "paid"
    raise NoCredit("нет кредита на вопрос")


def consume_continue(user: User) -> str:
    if user.free_clarifications > 0:
        user.free_clarifications -= 1
        return "free"
    if user.paid_continues > 0:
        user.paid_continues -= 1
        return "paid"
    raise NoCredit("нет кредита на уточнение")


def refund(user: User, kind: str, what: str) -> None:
    """Вернуть кредит, если ИИ не ответил."""
    if what == "question":
        if kind == "free":
            user.free_questions += 1
        elif kind == "bonus":
            user.bonus_questions += 1
        else:
            user.paid_questions += 1
    elif what == "continue":
        if kind == "free":
            user.free_clarifications += 1
        else:
            user.paid_continues += 1


def grant_question_credit(user: User, source: str) -> None:
    if source == "paid":
        user.paid_questions += 1
    elif source == "bonus":
        user.bonus_questions += 1
        user.last_bonus_at = _utcnow()
    else:
        user.free_questions += 1


def grant_continue_credit(user: User) -> None:
    user.paid_continues += 1


def pending_review(user: User) -> Review | None:
    for review in user.reviews:
        if review.status == "pending":
            return review
    return None


def can_submit_review(user: User) -> bool:
    settings = get_settings()
    if pending_review(user):
        return False
    if user.last_bonus_at:
        cooldown = timedelta(days=settings.review_bonus_cooldown_days)
        if _utcnow() - user.last_bonus_at < cooldown:
            return False
    return True


def is_smalltalk(text: str) -> bool:
    """Приветствия и «спасибо» не считаем вопросом и не списываем кредит."""
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return True
    compact = cleaned.replace("!", "").replace(".", "").replace(",", "").strip()
    small = {
        "привет",
        "здравствуйте",
        "здравстуйте",
        "добрый день",
        "добрый вечер",
        "доброе утро",
        "старт",
        "начать",
        "старт бота",
        "меню",
        "помощь",
        "help",
        "start",
        "спасибо",
        "благодарю",
        "спс",
        "ок",
        "окей",
        "понятно",
        "хорошо",
        "ясно",
        "ага",
        "угу",
        "да",
        "нет",
        "👋",
        "привет!",
    }
    return compact in small or len(compact) < 8
