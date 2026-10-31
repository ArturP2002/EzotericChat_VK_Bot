"""Настройки бота из файла .env и переменных окружения."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все секреты и параметры запуска. Пустые ключи оплаты = бесплатный режим."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vk_token: str = ""
    # longpoll (по умолчанию) — бот сам опрашивает ВК, туннель не нужен.
    # callback — старый Callback API: нужны VK_SECRET, VK_CONFIRMATION и HTTPS-туннель.
    vk_event_mode: str = "longpoll"
    vk_secret: str = ""
    vk_confirmation: str = ""
    vk_group_id: int = 0

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_stub: bool = False

    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = "https://vk.com/im"
    # Куда ведёт кнопка «Оплатить», пока нет боевых ключей / для stub-платежа.
    yookassa_payment_url: str = "https://yookassa.ru"
    # false — полностью скрыть оплату; без ключей ЮKassa при true работает stub.
    payments_enabled: bool = True

    admin_vk_id: int = 0
    community_chat_url: str = ""
    # peer_id беседы «Общий чат», например 2000000001. Нужен, чтобы публиковать одобренные отзывы.
    community_chat_peer_id: int = 0

    price_rub: int = 100
    database_url: str = "postgresql+psycopg2://novaigra:novaigra@localhost:5432/novaigra"
    host: str = "0.0.0.0"
    port: int = 8080

    review_bonus_cooldown_days: int = 7

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_to_file: bool = True

    @property
    def uses_vk_longpoll(self) -> bool:
        return (self.vk_event_mode or "longpoll").strip().lower() != "callback"

    @property
    def uses_vk_callback(self) -> bool:
        return not self.uses_vk_longpoll

    @property
    def payments_live(self) -> bool:
        """Боевая ЮKassa: оба ключа заданы."""
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    @property
    def price_value(self) -> str:
        """Сумма в формате ЮKassa, например 100.00."""
        return f"{self.price_rub:.2f}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
