"""
Клиент для LM Studio.
Поддерживает переключение моделей на лету через /model команду.
"""

import asyncio
import logging
import aiohttp
from typing import Optional

log = logging.getLogger("LMStudio")

# ── Псевдонимы моделей ─────────────────────────────────────────────────────
# Ключ = то что пишет пользователь (любой регистр)
# Значение = точное название модели в LM Studio (или часть названия)
MODEL_ALIASES: dict[str, dict] = {
    "default": {
        "name": "qwen2.5-coder-3b-instruct",  # None = авто-выбор первой загруженной
        "description": "Автовыбор — первая загруженная модель",
        "emoji": "🤖",
    },
    "math": {
        "name": "gemma-4-12b-qat",          # ищем по вхождению строки
        "description": "Мощная модель для математики и логики",
        "emoji": "🧮",
    },
    "code": {
        "name": "gemma-4-12B-it-QAT-GGUF",
        "description": "Модель для написания и анализа кода",
        "emoji": "💻",
    },
    "fast": {
        "name": "qwen2.5-coder-3b-instruct",            # маленькие модели — быстрые
        "description": "Быстрая лёгкая модель для простых задач",
        "emoji": "⚡",
    },
    "smart": {
        "name": "7b",
        "description": "Умная модель для сложных вопросов",
        "emoji": "🧠",
    },
}


class LMStudioClient:
    def __init__(self, settings):
        self.base_url = settings.lm_studio_url.rstrip("/")
        self.max_tokens = settings.lm_max_tokens
        self.temperature = settings.lm_temperature
        self.timeout = settings.lm_timeout
        self.system_prompt = settings.system_prompt

        # Текущая модель — None = авто
        self._current_model: Optional[str] = settings.lm_model or None
        self._current_alias: str = "default"
        self._available_models: list[str] = []  # кэш списка моделей

    # ─────────────────────────────────────────────────────
    # СМЕНА МОДЕЛИ
    # ─────────────────────────────────────────────────────

    async def switch_model(self, alias: str) -> str:
        """
        Переключает модель по псевдониму.
        Возвращает текстовый ответ для пользователя.
        """
        alias = alias.strip().lower()

        # Обновляем список доступных моделей
        await self._refresh_models()

        if alias not in MODEL_ALIASES:
            available = ", ".join(f"`{k}`" for k in MODEL_ALIASES)
            return (
                f"❓ Неизвестный псевдоним `{alias}`.\n\n"
                f"Доступные: {available}\n\n"
                f"Или укажи точное название: `/model название_модели`"
            )

        alias_data = MODEL_ALIASES[alias]
        search = alias_data["name"]

        if search is None:
            # Авто-режим
            self._current_model = None
            self._current_alias = alias
            return f"{alias_data['emoji']} Режим авто — будет выбрана первая загруженная модель."

        # Ищем модель по вхождению строки
        matched = [m for m in self._available_models if search.lower() in m.lower()]

        if not matched:
            models_list = "\n".join(f"  • {m}" for m in self._available_models) or "  (список пуст)"
            return (
                f"⚠️ Не найдена модель содержащая `{search}` для псевдонима `{alias}`.\n\n"
                f"Загруженные модели в LM Studio:\n{models_list}\n\n"
                f"Загрузи нужную модель в LM Studio и попробуй снова.\n"
                f"Или укажи точное название: `/model точное_название`"
            )

        # Берём первое совпадение
        self._current_model = matched[0]
        self._current_alias = alias
        log.info(f"🔄 Модель переключена на: {self._current_model}")

        return (
            f"{alias_data['emoji']} Модель переключена!\n\n"
            f"Псевдоним: {alias}\n"
            f"Модель: `{self._current_model}`\n"
            f"Описание: {alias_data['description']}"
        )

    async def switch_model_by_exact_name(self, name: str) -> str:
        """Переключает на точное название модели."""
        await self._refresh_models()
        matched = [m for m in self._available_models if name.lower() in m.lower()]
        if not matched:
            return f"⚠️ Модель `{name}` не найдена в LM Studio."
        self._current_model = matched[0]
        self._current_alias = "custom"
        log.info(f"🔄 Модель переключена на: {self._current_model}")
        return f"✅ Модель переключена на: `{self._current_model}`"

    async def list_models(self) -> str:
        """Возвращает список доступных моделей."""
        await self._refresh_models()

        current = self._current_model or "(авто)"
        lines = [f"🤖 Текущая модель: `{current}` (режим: {self._current_alias})\n"]

        if self._available_models:
            lines.append("📋 Загружены в LM Studio:")
            for m in self._available_models:
                mark = "✅ " if m == self._current_model else "  "
                lines.append(f"{mark}• {m}")
        else:
            lines.append("⚠️ Нет загруженных моделей в LM Studio")

        lines.append("\n🏷️ Псевдонимы для быстрого переключения:")
        for alias, data in MODEL_ALIASES.items():
            lines.append(f"{data['emoji']} `/model {alias}` — {data['description']}")

        return "\n".join(lines)

    async def _refresh_models(self):
        """Обновляет кэш списка моделей из LM Studio."""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.base_url}/models") as r:
                    if r.status == 200:
                        data = await r.json()
                        self._available_models = [m["id"] for m in data.get("data", [])]
                        log.debug(f"Моделей найдено: {len(self._available_models)}")
        except Exception as e:
            log.warning(f"Не удалось обновить список моделей: {e}")

    async def _get_model(self, session: aiohttp.ClientSession) -> str:
        """Возвращает текущую модель или первую доступную."""
        if self._current_model:
            return self._current_model
        try:
            async with session.get(f"{self.base_url}/models", timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                models = data.get("data", [])
                if models:
                    model_id = models[0]["id"]
                    log.info(f"🤖 Авто-выбрана модель: {model_id}")
                    return model_id
        except Exception as e:
            log.warning(f"Не удалось получить список моделей: {e}")
        return "local-model"

    # ─────────────────────────────────────────────────────
    # ЗАПРОС К НЕЙРОНКЕ
    # ─────────────────────────────────────────────────────

    async def chat(
        self,
        user_message: str,
        history: Optional[list] = None,
        extra_system: str = "",
    ) -> str:
        system = self.system_prompt
        if extra_system:
            system = extra_system + "\n\n" + system

        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            model = await self._get_model(session)

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
            }

            log.debug(f"📤 [{model}] {user_message[:80]}...")

            try:
                async with session.post(f"{self.base_url}/chat/completions", json=payload) as response:
                    if response.status != 200:
                        body = await response.text()
                        log.error(f"LM Studio {response.status}: {body[:200]}")
                        return f"⚠️ Ошибка LM Studio (код {response.status}). Проверь что модель загружена."
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    log.debug(f"📥 Ответ: {content[:80]}...")
                    return content

            except aiohttp.ClientConnectorError:
                return (
                    "⚠️ LM Studio недоступен.\n"
                    "1. Запусти LM Studio\n"
                    "2. Включи Local Server (порт 1234)\n"
                    "3. Загрузи модель"
                )
            except asyncio.TimeoutError:
                return "⚠️ Таймаут. Модель думает слишком долго — увеличь LM_TIMEOUT в .env"
            except Exception as e:
                log.error(f"Ошибка LM Studio: {e}", exc_info=True)
                return f"⚠️ Внутренняя ошибка: {e}"
