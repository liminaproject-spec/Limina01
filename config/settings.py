"""
Настройки ассистента.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Telegram
    api_id: int = 0
    api_hash: str = ""
    phone_number: str = ""
    owner_id: int = 0
    assistant_username: str = ""
    session_file: str = "sessions/assistant"

    # Мониторинг — каналы для логов
    log_channels: list = field(default_factory=list)
    # Аккаунты которые мониторим (пусто = только аккаунт ассистента)
    monitored_accounts: list = field(default_factory=list)

    # LM Studio
    lm_studio_url: str = "http://localhost:1234/v1"
    lm_model: str = ""
    lm_max_tokens: int = 1024
    lm_temperature: float = 0.7
    lm_timeout: int = 120
    system_prompt: str = (
        "Ты — умный личный ассистент. Отвечай кратко и по делу на русском языке."
    )

    # Файлы
    templates_file: str = "config/templates.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()

        s.api_id = int(os.getenv("TG_API_ID", "0"))
        s.api_hash = os.getenv("TG_API_HASH", "")
        s.phone_number = os.getenv("TG_PHONE", "")
        s.owner_id = int(os.getenv("TG_OWNER_ID", "0"))
        s.assistant_username = os.getenv("TG_ASSISTANT_USERNAME", "unknown")

        # Лог-каналы: через запятую
        # Пример: LOG_CHANNELS=-1001234567890,@my_log_channel
        raw_channels = os.getenv("LOG_CHANNELS", "")
        s.log_channels = [
            c.strip() for c in raw_channels.split(",")
            if c.strip()
        ]
        # Числовые ID конвертируем в int
        s.log_channels = [
            int(c) if c.lstrip("-").isdigit() else c
            for c in s.log_channels
        ]

        # Аккаунты для мониторинга (номера телефонов через запятую)
        # Пример: MONITORED_ACCOUNTS=+79991234567,+79997654321
        raw_accounts = os.getenv("MONITORED_ACCOUNTS", "")
        s.monitored_accounts = [
            a.strip() for a in raw_accounts.split(",") if a.strip()
        ]

        s.lm_studio_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        s.lm_model = os.getenv("LM_MODEL", "")
        s.lm_max_tokens = int(os.getenv("LM_MAX_TOKENS", "1024"))
        s.lm_temperature = float(os.getenv("LM_TEMPERATURE", "0.7"))
        s.lm_timeout = int(os.getenv("LM_TIMEOUT", "120"))

        custom_prompt = os.getenv("SYSTEM_PROMPT", "")
        if custom_prompt:
            s.system_prompt = custom_prompt

        s.templates_file = os.getenv("TEMPLATES_FILE", "config/templates.json")
        s.session_file = os.getenv("SESSION_FILE", "sessions/assistant")

        for d in ["sessions", "logs", "config", "data"]:
            Path(d).mkdir(exist_ok=True)

        s._validate()
        return s

    def _validate(self):
        errors = []
        if not self.api_id:
            errors.append("TG_API_ID не задан")
        if not self.api_hash:
            errors.append("TG_API_HASH не задан")
        if not self.phone_number:
            errors.append("TG_PHONE не задан")
        if not self.owner_id:
            errors.append("TG_OWNER_ID не задан")
        if errors:
            raise ValueError("❌ Ошибки конфига:\n" + "\n".join(f"  • {e}" for e in errors))
