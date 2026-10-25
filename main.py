"""Точка входа: python main.py"""

import uvicorn

from app.config import get_settings
from app.logging_setup import nastroit_zhurnal


def main() -> None:
    nastroit_zhurnal()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
