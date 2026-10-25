"""Нарезка длинного ответа: одно сообщение ВК не длиннее 4096 символов."""

VK_MESSAGE_LIMIT = 4096


def split_message(text: str, limit: int = VK_MESSAGE_LIMIT) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        window = rest[:limit]
        cut = max(
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind(" "),
        )
        if cut < limit // 4:
            cut = limit
        chunk = rest[:cut].rstrip()
        parts.append(chunk)
        rest = rest[cut:].lstrip()
    return parts
