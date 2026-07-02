"""
Настройки ассистента.
Все секреты хранятся в .env файле — никогда не коммить его в git!
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # ── Telegram ────────────────────────────────────────
    api_id: int = 0
    api_hash: str = ""
    phone_number: str = ""          # номер телефона аккаунта-ассистента
    owner_id: int = 0               # твой Telegram ID (от кого слушать команды)
    assistant_username: str = ""    # username аккаунта-ассистента (для логов)
    session_file: str = "sessions/assistant"

    # ── LM Studio ───────────────────────────────────────
    lm_studio_url: str = "http://localhost:1234/v1"
    lm_model: str = ""              # оставь пустым — возьмёт первую загруженную модель
    lm_max_tokens: int = 1024
    lm_temperature: float = 0.7
    lm_timeout: int = 120           # секунд ждать ответа от модели

    # ── Системный промпт для нейронки ───────────────────
    system_prompt: str = (
        "Ты — умный личный ассистент. Отвечай кратко и по делу на русском языке. "
        "Если тебя просят выполнить действие (отправить сообщение, использовать шаблон) — "
        "возвращай структурированный ответ в формате JSON внутри тегов <action>...</action>. "
        "Если это обычный вопрос — отвечай текстом."
    )

    # ── Файлы ───────────────────────────────────────────
    templates_file: str = "config/templates.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()

        # Telegram
        s.api_id = int(os.getenv("TG_API_ID", "0"))
        s.api_hash = os.getenv("TG_API_HASH", "")
        s.phone_number = os.getenv("TG_PHONE", "")
        s.owner_id = int(os.getenv("TG_OWNER_ID", "0"))
        s.assistant_username = os.getenv("TG_ASSISTANT_USERNAME", "unknown")

        # LM Studio
        s.lm_studio_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        s.lm_model = os.getenv("LM_MODEL", "")
        s.lm_max_tokens = int(os.getenv("LM_MAX_TOKENS", "1024"))
        s.lm_temperature = float(os.getenv("LM_TEMPERATURE", "0.7"))
        s.lm_timeout = int(os.getenv("LM_TIMEOUT", "120"))

        # Системный промпт (можно переопределить в .env)
        custom_prompt = os.getenv("SYSTEM_PROMPT", "")
        if custom_prompt:
            s.system_prompt = custom_prompt

        # Пути
        s.templates_file = os.getenv("TEMPLATES_FILE", "config/templates.json")
        s.session_file = os.getenv("SESSION_FILE", "sessions/assistant")

        # Создаём папки если нет
        Path("sessions").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
        Path("config").mkdir(exist_ok=True)

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
            raise ValueError(
                "❌ Ошибки конфигурации:\n" + "\n".join(f"  • {e}" for e in errors)
                + "\n\nПроверь файл .env"
            )
