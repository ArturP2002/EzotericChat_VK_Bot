"""Таблицы PostgreSQL: пользователь, тема, сообщения, платежи, отзывы."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Состояние человека в личке: кредиты, статус сценария, висящая оплата."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vk_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    free_questions: Mapped[int] = mapped_column(Integer, default=1)
    free_clarifications: Mapped[int] = mapped_column(Integer, default=1)
    bonus_questions: Mapped[int] = mapped_column(Integer, default=0)
    paid_questions: Mapped[int] = mapped_column(Integer, default=0)
    paid_continues: Mapped[int] = mapped_column(Integer, default=0)
    # Статус сценария: idle, awaiting_question, active, awaiting_clarification,
    # awaiting_payment, awaiting_review.
    status: Mapped[str] = mapped_column(String(32), default="idle")
    pending_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_payment_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pending_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcomed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_bonus_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    topics: Mapped[list["Topic"]] = relationship(back_populates="user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user", lazy="selectin")


class Topic(Base):
    """Одна жизненная ситуация. Новый вопрос открывает новую тему."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="topics")
    messages: Mapped[list["TopicMessage"]] = relationship(
        back_populates="topic",
        order_by="TopicMessage.id",
        lazy="selectin",
    )


class TopicMessage(Base):
    """Реплика пользователя или ответ модели внутри темы."""

    __tablename__ = "topic_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    topic: Mapped[Topic] = relationship(back_populates="messages")


class Payment(Base):
    """Счёт ЮKassa, привязанный к действию «новый вопрос» или «продолжить»."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("yookassa_id", name="uq_payments_yookassa_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    yookassa_id: Mapped[str] = mapped_column(String(64), index=True)
    vk_user_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    amount: Mapped[str] = mapped_column(String(16))
    confirmation_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Review(Base):
    """Отзыв о внутренней работе. Бонус начисляется только после одобрения."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="reviews")
