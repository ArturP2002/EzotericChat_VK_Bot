"""Веб-сервер: Long Poll / Callback API ВК и уведомления ЮKassa."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from sqlalchemy.orm import selectinload
from vkbottle import API

from app.billing.yookassa import apply_succeeded_payment, fetch_status, parse_notification
from app.config import get_settings
from app.db.models import Payment, User
from app.db.session import create_session, init_db
from app.logging_setup import ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ, nastroit_zhurnal, zhurnal_zapuska
from app.services.dialog import DialogService
from app.vk.handlers import handle_vk_event
from app.vk.polling import run_vk_longpoll
from app.vk.sender import VkSender

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    nastroit_zhurnal()
    init_db()
    logger.info("База данных готова")
    settings = get_settings()
    app.state.vk_api = API(settings.vk_token) if settings.vk_token else None
    if app.state.vk_api is None:
        logger.warning("Токен ВК пустой: входящие события не смогут отправить ответ")
    zhurnal_zapuska()

    poll_task: asyncio.Task | None = None
    if settings.uses_vk_longpoll:
        if app.state.vk_api is None:
            logger.error("VK_EVENT_MODE=longpoll, но VK_TOKEN пустой — опрос не запущен")
        else:
            poll_task = asyncio.create_task(
                run_vk_longpoll(app.state.vk_api),
                name="vk-longpoll",
            )
    else:
        logger.info("=== Ожидаю события ВК на POST /vk/callback ===")

    try:
        yield
    finally:
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Бот останавливается")


app = FastAPI(title="Новая Игра", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/vk/callback")
async def vk_callback(request: Request) -> Response:
    """Callback API (режим VK_EVENT_MODE=callback). При Long Poll события сюда не нужны."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        logger.warning("ВК прислал не-JSON в /vk/callback")
        return Response(content="ok", media_type="text/plain")

    event_type = payload.get("type")
    logger.info("ВК событие: %s", event_type or "без типа")

    if event_type == "confirmation":
        logger.info("ВК запросил подтверждение Callback API")
        return Response(content=settings.vk_confirmation, media_type="text/plain")

    if not settings.uses_vk_callback:
        # Long Poll основной режим: не обрабатываем дубликаты с Callback-сервера.
        logger.debug("Callback-событие %s проигнорировано (VK_EVENT_MODE=longpoll)", event_type)
        return Response(content="ok", media_type="text/plain")

    if settings.vk_secret and payload.get("secret") != settings.vk_secret:
        logger.warning("Отклонён запрос ВК: неверный секрет Callback API")
        return Response(content="ok", media_type="text/plain")

    api: API | None = request.app.state.vk_api
    if api is None:
        logger.error("Нет токена ВК, событие %s пропущено", event_type)
        return Response(content="ok", media_type="text/plain")

    session = create_session()
    try:
        await handle_vk_event(session, api, payload)
        session.commit()
        logger.debug("Событие ВК %s обработано и записано в базу", event_type)
    except Exception:
        session.rollback()
        logger.exception("Ошибка при обработке события ВК типа %s", event_type)
    finally:
        session.close()
    return Response(content="ok", media_type="text/plain")


@app.post("/yookassa/webhook")
async def yookassa_webhook(request: Request) -> dict[str, str]:
    """ЮKassa сообщает сюда, что платёж прошёл или изменился."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        logger.warning("ЮKassa прислала не-JSON в /yookassa/webhook")
        return {"status": "ignored"}

    parsed = parse_notification(body)
    if parsed is None:
        logger.info("Уведомление ЮKassa без id платежа — пропускаю")
        return {"status": "ignored"}
    payment_id, _status = parsed
    logger.info("ЮKassa уведомление: платёж %s, статус в теле %s", payment_id, _status)

    try:
        remote_status = await asyncio.to_thread(fetch_status, payment_id)
        logger.info("ЮKassa подтвердила статус платежа %s: %s", payment_id, remote_status)
    except Exception:
        logger.exception("Не удалось запросить платёж %s у ЮKassa, беру статус из уведомления", payment_id)
        remote_status = _status

    if remote_status != "succeeded":
        logger.info("Платёж %s ещё не успешен (%s) — жду", payment_id, remote_status)
        return {"status": "ok"}

    session = create_session()
    try:
        record = session.query(Payment).filter_by(yookassa_id=payment_id).one_or_none()
        if record is None:
            logger.warning("Платёж %s успешен в ЮKassa, но в нашей базе его нет", payment_id)
            return {"status": "ok"}
        if record.status == "succeeded":
            logger.info("Платёж %s уже был засчитан ранее", payment_id)
            return {"status": "ok"}

        user = (
            session.query(User)
            .options(selectinload(User.reviews), selectinload(User.topics))
            .filter_by(vk_id=record.vk_user_id)
            .one_or_none()
        )
        if user is None:
            logger.warning("Платёж %s: пользователь vk_id=%s не найден", payment_id, record.vk_user_id)
            return {"status": "ok"}

        apply_succeeded_payment(user, record)
        session.commit()
        logger.info(
            "Оплата засчитана: пользователь %s, действие «%s», платёж %s",
            user.vk_id,
            ИМЕНА_ДЕЙСТВИЙ_ОПЛАТЫ.get(record.action, record.action),
            payment_id,
        )

        api: API | None = request.app.state.vk_api
        if api is not None:
            dialog = DialogService(session, VkSender(api))
            await dialog.on_payment_succeeded(user.vk_id, record.action)
            session.commit()
        else:
            logger.error("Оплата прошла, но токена ВК нет — пользователю %s не написать", user.vk_id)
    except Exception:
        session.rollback()
        logger.exception("Ошибка обработки вебхука ЮKassa для платежа %s", payment_id)
    finally:
        session.close()
    return {"status": "ok"}
