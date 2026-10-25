"""Пользователь ВК и активная тема разговора."""

from sqlalchemy.orm import Session

from app.db.models import Topic, User


def get_or_create_user(session: Session, vk_id: int) -> User:
    user = session.query(User).filter_by(vk_id=vk_id).one_or_none()
    if user is None:
        user = User(
            vk_id=vk_id,
            free_questions=1,
            free_clarifications=1,
            bonus_questions=0,
            paid_questions=0,
            paid_continues=0,
            status="idle",
            welcomed=False,
        )
        session.add(user)
        session.flush()
    return user


def active_topic(session: Session, user: User) -> Topic | None:
    return (
        session.query(Topic)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(Topic.id.desc())
        .first()
    )


def close_active_topic(session: Session, user: User) -> None:
    topic = active_topic(session, user)
    if topic:
        topic.is_active = False


def start_topic(session: Session, user: User) -> Topic:
    """Новый вопрос закрывает предыдущую тему, чтобы контекст не смешивался."""
    close_active_topic(session, user)
    topic = Topic(user_id=user.id, is_active=True)
    session.add(topic)
    session.flush()
    return topic
