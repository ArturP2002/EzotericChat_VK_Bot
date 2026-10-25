"""Вызов DeepSeek. При LLM_STUB=true возвращает заглушку без сети."""

import logging

import httpx

from app.config import get_settings
from app.llm.prompt import sanitize_answer, system_prompt
from app.logging_setup import kratko

logger = logging.getLogger(__name__)

STUB_ANSWER = (
    "Вы описываете место, где действие в мире и внутренний вектор пока не встречаются. "
    "Страх здесь не враг: он держит отдельность, без которой не было бы выбора. "
    "Полезно заметить, через какой фильтр — род, родители, личный опыт — ситуация "
    "кажется безвыходной, и какой маленький шаг был бы честным, а не «правильным». "
    "Завершён ли цикл: вы уже встретили опыт, поняли его — или он крутится, потому что "
    "ещё не отпущен?"
)


class DeepSeekError(Exception):
    """Сеть, ключ или неожиданный ответ модели."""


def _messages_for_api(history: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
    packed: list[dict[str, str]] = [{"role": "system", "content": system_prompt()}]
    packed.extend(history[-20:])
    packed.append({"role": "user", "content": user_text})
    return packed


async def complete(history: list[dict[str, str]], user_text: str) -> str:
    settings = get_settings()
    if settings.llm_stub:
        logger.info("ИИ-заглушка: живой DeepSeek не вызывается")
        return sanitize_answer(STUB_ANSWER)

    if not settings.deepseek_api_key:
        logger.error("Ключ DeepSeek пустой")
        raise DeepSeekError("Не задан ключ DeepSeek")

    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": _messages_for_api(history, user_text),
        "temperature": 0.7,
        "max_tokens": 2200,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    logger.info(
        "Запрос в DeepSeek, модель %s, сообщений %s, пользовательский текст «%s»",
        settings.deepseek_model,
        len(payload["messages"]),
        kratko(user_text),
    )
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            logger.info("DeepSeek ответил HTTP %s", response.status_code)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.exception("Запрос к DeepSeek не удался")
        raise DeepSeekError(str(exc)) from exc

    try:
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        if usage:
            logger.info(
                "DeepSeek токены: вход %s, выход %s, всего %s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("Неожиданный JSON DeepSeek: %s", kratko(str(data), 400))
        raise DeepSeekError("Неожиданный ответ DeepSeek") from exc
    return sanitize_answer(content)
