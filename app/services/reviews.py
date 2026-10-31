"""Отзывы о внутренней работе: форма в боте и модерация администратором."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db.models import Review, User
from app.logging_setup import kratko
from app.services.entitlements import can_submit_review, grant_question_credit, pending_review
from app.services.users import active_topic
from app.vk import texts
from app.vk.keyboards import admin_review_keyboard, idle_keyboard
from app.vk.sender import VkSender

logger = logging.getLogger(__name__)


def begin_review(user: User) -> str:
    if pending_review(user):
        logger.info("У пользователя %s уже есть отзыв на проверке", user.vk_id)
        return texts.REVIEW_ALREADY_PENDING
    if not can_submit_review(user):
        logger.info("Пользователь %s недавно получал бонус за отзыв — рано", user.vk_id)
        return texts.REVIEW_COOLDOWN
    user.status = "awaiting_review"
    return texts.REVIEW_PROMPT


def save_review(session: Session, user: User, text: str) -> Review:
    topic = active_topic(session, user)
    review = Review(
        user_id=user.id,
        topic_id=topic.id if topic else None,
        text=text.strip(),
        status="pending",
    )
    session.add(review)
    session.flush()
    user.reviews.append(review)
    user.status = "active" if topic else "idle"
    logger.info("Сохранён отзыв #%s от %s: «%s»", review.id, user.vk_id, kratko(text))
    return review


async def notify_admin(sender: VkSender, user: User, review: Review) -> None:
    admin_id = get_settings().admin_vk_id
    if not admin_id:
        logger.warning(
            "Отзыв #%s некому отправить: ADMIN_VK_ID не задан. "
            "Пользователь %s всё равно ждёт решения.",
            review.id,
            user.vk_id,
        )
        return
    snippet = review.text if len(review.text) < 1500 else review.text[:1500] + "…"
    body = f"Отзыв #{review.id} от vk.com/id{user.vk_id}\n\n{snippet}"
    logger.info("Отправляю отзыв #%s администратору %s", review.id, admin_id)
    await sender.send(admin_id, body, keyboard=admin_review_keyboard(review.id))


def moderate(session: Session, review_id: int, approve: bool) -> tuple[User, Review] | None:
    review = (
        session.query(Review)
        .options(selectinload(Review.user))
        .filter_by(id=review_id)
        .one_or_none()
    )
    if review is None or review.status != "pending":
        logger.warning("Отзыв #%s не найден или уже разобран", review_id)
        return None
    review.status = "approved" if approve else "rejected"
    review.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user = review.user
    if approve:
        grant_question_credit(user, "bonus")
        logger.info("Отзыв #%s одобрен, пользователю %s начислен бонусный вопрос", review_id, user.vk_id)
    else:
        logger.info("Отзыв #%s отклонён, пользователь %s без бонуса", review_id, user.vk_id)
    return user, review


async def publish_review_to_chat(sender: VkSender, review: Review) -> bool:
    """Анонимно публикует одобренный отзыв в общий чат. Без имени и ссылки на профиль."""
    peer_id = get_settings().community_chat_peer_id
    if not peer_id:
        logger.info(
            "Публикация отзыва #%s пропущена: COMMUNITY_CHAT_PEER_ID не задан",
            review.id,
        )
        return False
    body = f"{texts.REVIEW_CHAT_POST}\n\n{review.text.strip()}"
    try:
        await sender.send_to_peer(peer_id, body)
        logger.info("Отзыв #%s опубликован в общем чате peer_id=%s", review.id, peer_id)
        return True
    except Exception:
        logger.exception(
            "Не удалось опубликовать отзыв #%s в общий чат peer_id=%s",
            review.id,
            peer_id,
        )
        return False


async def handle_admin_decision(
    session: Session,
    sender: VkSender,
    review_id: int,
    approve: bool,
    admin_id: int,
) -> None:
    result = moderate(session, review_id, approve)
    if result is None:
        await sender.send(admin_id, f"Отзыв #{review_id} уже разобран или не найден.")
        return
    user, review = result
    session.commit()
    if approve:
        published = await publish_review_to_chat(sender, review)
        await sender.send(user.vk_id, texts.REVIEW_APPROVED, keyboard=idle_keyboard(user))
        if published:
            extra = " Опубликован в общем чате."
        elif get_settings().community_chat_peer_id:
            extra = " В общий чат не отправился — проверьте COMMUNITY_CHAT_PEER_ID и что бот в беседе."
        else:
            extra = " В общий чат не отправился: COMMUNITY_CHAT_PEER_ID не задан."
        await sender.send(admin_id, f"Отзыв #{review.id} одобрен. Начислен вопрос.{extra}")
    else:
        await sender.send(user.vk_id, texts.REVIEW_REJECTED)
        await sender.send(admin_id, f"Отзыв #{review.id} отклонён.")
