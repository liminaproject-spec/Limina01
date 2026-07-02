"""
Система ответов.

Когда ты отправляешь сообщение с флагом [ОТВЕТ] или [REPLY]:
- Создаётся reply-сессия
- Получателю приходит сообщение + инструкция как ответить через бота
- Когда получатель пишет боту — его ответ пересылается тебе
"""

import logging
import secrets
from typing import Optional

from core.database import Database

log = logging.getLogger("ReplySystem")

# Бот для приёма ответов (отдельный аккаунт ассистента)
REPLY_INSTRUCTION = (
    "\n\n──────────────────\n"
    "💬 Чтобы ответить — напишите в этот чат: ОТВЕТ [ваш текст]\n"
    "Например: ОТВЕТ Хорошо, договорились!"
)


class ReplySystem:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings

    def needs_reply(self, text: str) -> bool:
        """Проверяет есть ли в тексте флаг запроса ответа."""
        markers = ["[ответ]", "[reply]", "[жди ответа]", "[ответить]", "ответ:да", "reply:yes"]
        low = text.lower()
        return any(m in low for m in markers)

    def strip_reply_marker(self, text: str) -> str:
        """Убирает маркер из текста сообщения."""
        import re
        cleaned = re.sub(
            r"\[ответ\]|\[reply\]|\[жди ответа\]|\[ответить\]|ответ:да|reply:yes",
            "", text, flags=re.IGNORECASE
        ).strip()
        return cleaned

    def create_session(
        self,
        message_id: int,
        recipient_id: int,
        recipient_user: str,
        original_text: str,
    ) -> str:
        """Создаёт reply-сессию и возвращает токен."""
        token = secrets.token_hex(4).upper()  # например A3F9
        self.db.create_reply_session(
            message_id=message_id,
            recipient_id=recipient_id,
            recipient_user=recipient_user,
            original_text=original_text,
            reply_token=token,
        )
        log.info(f"✅ Reply-сессия создана: {recipient_user} token={token}")
        return token

    def add_reply_footer(self, text: str) -> str:
        """Добавляет инструкцию по ответу к тексту сообщения."""
        return text + REPLY_INSTRUCTION

    async def handle_incoming_reply(
        self,
        sender_id: int,
        sender_username: str,
        text: str,
    ) -> Optional[str]:
        """
        Обрабатывает входящее сообщение от получателя.
        Если это ответ — возвращает текст для пересылки владельцу.
        Если нет — возвращает None.
        """
        low = text.strip().lower()

        # Проверяем формат "ОТВЕТ текст"
        if not (low.startswith("ответ ") or low.startswith("reply ")):
            # Также проверяем активную сессию для этого пользователя
            session = self.db.get_active_session_by_user(sender_id)
            if not session:
                return None
            # Любое сообщение от пользователя с активной сессией = ответ
            reply_text = text.strip()
        else:
            # Извлекаем текст после "ОТВЕТ "
            reply_text = text.strip()[6:].strip() if low.startswith("ответ ") else text.strip()[6:].strip()
            session = self.db.get_active_session_by_user(sender_id)
            if not session:
                return None

        if not reply_text:
            return None

        # Закрываем сессию
        self.db.close_reply_session(session["id"])

        # Логируем входящее сообщение
        original_msg_id = self.db.log_message(
            direction="in",
            text=reply_text,
            from_user=sender_username or str(sender_id),
            to_user="owner",
            reply_to_id=session["message_id"],
            status="received",
        )

        # Обновляем статус исходного сообщения
        self.db.update_message_status(session["message_id"], "replied")

        log.info(f"📨 Получен ответ от {sender_username}: {reply_text[:60]}")

        # Формируем текст для владельца
        forwarded = (
            f"📩 Ответ от {sender_username or sender_id}:\n\n"
            f"{reply_text}\n\n"
            f"── На сообщение: {session['original_text'][:80]}..."
            if len(session['original_text']) > 80
            else f"── На сообщение: {session['original_text']}"
        )
        return forwarded

    def get_active_sessions_text(self) -> str:
        """Текстовый список активных reply-сессий."""
        sessions = self.db.get_all_active_sessions()
        if not sessions:
            return "📭 Нет активных сессий ожидания ответа."
        lines = [f"📬 Активных сессий: {len(sessions)}\n"]
        for s in sessions:
            lines.append(
                f"• {s['recipient_user']} — {s['created_at'][:16]}\n"
                f"  Сообщение: {s['original_text'][:60]}..."
            )
        return "\n".join(lines)
