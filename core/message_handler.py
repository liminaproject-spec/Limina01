"""
Обработчик сообщений — главный мозг ассистента.
"""

import json
import logging
import re
from typing import Optional

from core.database import Database
from core.lm_client import LMStudioClient, MODEL_ALIASES
from core.template_manager import TemplateManager
from core.sender import MessageSender
from core.reply_system import ReplySystem

log = logging.getLogger("MessageHandler")

ANALYSIS_PROMPT = """Ты — умный личный ассистент. Анализируй запрос пользователя и возвращай ответ.

Если пользователь хочет ОТПРАВИТЬ сообщение кому-то — верни JSON в теге <send>:
<send>{"to": "@username_или_имя", "text": "текст сообщения", "needs_reply": true/false}</send>

needs_reply = true если в запросе есть слова: [ответ], жду ответа, пусть ответит, reply.

Если это обычный вопрос/задача — просто ответь текстом на русском, без JSON.

Примеры:
- "напиши @test привет" → <send>{"to": "@test", "text": "Привет!", "needs_reply": false}</send>
- "напиши @test добрый день [ответ]" → <send>{"to": "@test", "text": "Добрый день!", "needs_reply": true}</send>
- "какая погода в москве" → просто текстовый ответ
"""


class MessageHandler:
    def __init__(self, settings, lm_client: LMStudioClient, template_manager: TemplateManager, sender: MessageSender):
        self.settings = settings
        self.lm = lm_client
        self.tm = template_manager
        self.sender = sender
        self.db = Database()
        self.reply_sys = ReplySystem(self.db, settings)

    # ─────────────────────────────────────────────────────
    # ГЛАВНЫЙ РОУТЕР
    # ─────────────────────────────────────────────────────

    async def process(self, text: str, event) -> str:
        text = text.strip()
        low = text.lower()

        self.db.log_message(direction="in", text=text, from_user="owner", to_user="assistant")

        # ── Системные команды ─────────────────────────────
        if low in ("/info", "/help", "/помощь"):
            return self._info_text()

        if low in ("/шаблоны", "/templates"):
            return self.tm.list_all()

        if low in ("/модели", "/models"):
            return await self.lm.list_models()

        if low in ("/история", "/history"):
            return self._show_lm_history()

        if low in ("/очистить", "/clear"):
            self.db.clear_lm_history()
            return "🧹 История диалога очищена."

        if low == "/перезагрузить шаблоны":
            self.tm.reload()
            return f"🔄 Шаблоны перезагружены. Загружено: {len(self.tm.templates)}"

        if low in ("/статус", "/status"):
            return self._status_text()

        if low in ("/сессии", "/sessions"):
            return self.reply_sys.get_active_sessions_text()

        if low in ("/логи", "/logs"):
            return self._recent_logs()

        # ── /model команда ────────────────────────────────
        if low.startswith("/model"):
            return await self._handle_model_command(text)

        # ── Нейронка ──────────────────────────────────────
        lm_response = await self._ask_lm(text)

        send_data = self._parse_send_tag(lm_response)
        if send_data:
            return await self._handle_send(text, send_data)

        return lm_response

    # ─────────────────────────────────────────────────────
    # СМЕНА МОДЕЛИ
    # ─────────────────────────────────────────────────────

    async def _handle_model_command(self, text: str) -> str:
        """
        Обрабатывает /model [псевдоним или название].
        /model          → показать текущую модель и список
        /model math     → переключить на math-модель
        /model qwen2.5  → переключить по точному названию
        """
        parts = text.strip().split(maxsplit=1)

        # Просто /model без аргументов — показываем список
        if len(parts) == 1:
            return await self.lm.list_models()

        arg = parts[1].strip().lower()

        # Псевдоним из словаря
        if arg in MODEL_ALIASES:
            return await self.lm.switch_model(arg)

        # Не псевдоним — пробуем как точное название
        return await self.lm.switch_model_by_exact_name(arg)

    # ─────────────────────────────────────────────────────
    # ВХОДЯЩИЕ ОТ ПОЛУЧАТЕЛЕЙ
    # ─────────────────────────────────────────────────────

    async def process_incoming_from_recipient(self, sender_id: int, sender_username: str, text: str) -> Optional[str]:
        return await self.reply_sys.handle_incoming_reply(
            sender_id=sender_id,
            sender_username=sender_username,
            text=text,
        )

    # ─────────────────────────────────────────────────────
    # ОТПРАВКА
    # ─────────────────────────────────────────────────────

    async def _handle_send(self, original_text: str, send_data: dict) -> str:
        recipient = send_data.get("to", "").strip()
        message_text = send_data.get("text", "").strip()
        needs_reply = send_data.get("needs_reply", False)

        if not recipient or not message_text:
            return "❓ Не смог определить кому или что отправить. Уточни запрос."

        if not recipient.startswith("@") and not recipient.lstrip("-").isdigit():
            recipient = "@" + recipient

        template_match = self.tm.find_in_text(original_text)
        template_keyword = None
        if template_match:
            template, keyword = template_match
            template_keyword = keyword
            variables = self._parse_key_value(original_text)
            if template.variables and all(v in variables for v in template.variables):
                message_text = template.render(variables)

        send_text = message_text
        if needs_reply:
            send_text = self.reply_sys.add_reply_footer(message_text)

        queue_id = self.db.queue_message(recipient, send_text)
        success, info = await self.sender.send_to(recipient, send_text)

        if success:
            msg_id = self.db.log_message(
                direction="out", text=send_text,
                from_user="owner", to_user=recipient,
                template=template_keyword, status="sent",
            )
            self.db.mark_queue_sent(queue_id)

            reply_info = ""
            if needs_reply:
                recipient_id = await self._resolve_recipient_id(recipient)
                if recipient_id:
                    token = self.reply_sys.create_session(
                        message_id=msg_id, recipient_id=recipient_id,
                        recipient_user=recipient, original_text=message_text,
                    )
                    reply_info = f"\n📬 Ожидаю ответ от {recipient} (токен: {token})"

            preview = send_text[:120] + ("..." if len(send_text) > 120 else "")
            return f"✅ Отправлено {recipient}:\n\n{preview}{reply_info}"
        else:
            self.db.mark_queue_failed(queue_id, info)
            self.db.log_message(
                direction="out", text=send_text,
                from_user="owner", to_user=recipient,
                template=template_keyword, status="failed",
            )
            return f"❌ Не удалось отправить {recipient}: {info}\n💾 Сохранено в резерве #{queue_id}"

    async def _resolve_recipient_id(self, recipient: str) -> Optional[int]:
        try:
            entity = await self.sender.client.get_entity(recipient)
            return entity.id
        except Exception as e:
            log.warning(f"Не удалось получить ID для {recipient}: {e}")
            return None

    # ─────────────────────────────────────────────────────
    # LM STUDIO
    # ─────────────────────────────────────────────────────

    async def _ask_lm(self, text: str) -> str:
        history = self.db.get_lm_history(last_n=16)
        response = await self.lm.chat(
            user_message=text,
            history=history,
            extra_system=ANALYSIS_PROMPT,
        )
        self.db.save_lm_turn("user", text)
        self.db.save_lm_turn("assistant", response)
        return response

    # ─────────────────────────────────────────────────────
    # ПАРСИНГ
    # ─────────────────────────────────────────────────────

    def _parse_send_tag(self, response: str) -> Optional[dict]:
        match = re.search(r"<send>(.*?)</send>", response, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            return None

    def _parse_key_value(self, text: str) -> dict:
        result = {}
        for m in re.finditer(r"(\w+)=([\w\s\u0400-\u04FF]+?)(?=\s+\w+=|$)", text):
            result[m.group(1).strip()] = m.group(2).strip()
        return result

    # ─────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ
    # ─────────────────────────────────────────────────────

    def _info_text(self) -> str:
        # Динамически строим список псевдонимов моделей
        model_aliases_text = "\n".join(
            f"  {d['emoji']} /model {alias} — {d['description']}"
            for alias, d in MODEL_ALIASES.items()
            if alias != "default"
        )
        templates_text = "\n".join(
            f"  • {kw} — {t.name}" for kw, t in self.tm.templates.items()
        ) or "  (шаблоны не загружены)"

        return (
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 L. I. M. I. N. A\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "📨 ОТПРАВКА СООБЩЕНИЙ\n"
            "напиши @username текст\n"
            "отправь @username текст [ответ]\n"
            "  └ [ответ] — получатель сможет ответить через бота\n\n"

            "📋 ШАБЛОНЫ\n"
            "напиши @username КОДОВОЕ_СЛОВО ключ=значение\n"
            f"{templates_text}\n\n"

            "🧠 МОДЕЛИ\n"
            "/model              — текущая модель и список\n"
            "/модели             — все загруженные модели\n"
            f"{model_aliases_text}\n"
            "/model название     — переключить по точному названию\n\n"

            "🗂️ ШАБЛОНЫ\n"
            "/шаблоны            — список всех шаблонов\n"
            "/перезагрузить шаблоны — обновить без рестарта\n\n"

            "📊 МОНИТОРИНГ\n"
            "/статус             — статистика сообщений\n"
            "/сессии             — кто ещё не ответил\n"
            "/логи               — последние 10 сообщений\n"
            "/история            — история диалога с нейронкой\n"
            "/очистить           — сбросить историю диалога\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Или просто пиши — отвечу через нейронку 🧠"
        )

    def _status_text(self) -> str:
        stats = self.db.get_stats()
        current_model = self.lm._current_model or "(авто)"
        return (
            f"📊 Статус ассистента:\n\n"
            f"🤖 Модель: {current_model} (режим: {self.lm._current_alias})\n\n"
            f"📨 Сообщений всего: {stats['total_messages']}\n"
            f"  → Отправлено: {stats['sent']}\n"
            f"  ← Получено: {stats['received']}\n\n"
            f"📬 Активных reply-сессий: {stats['active_reply_sessions']}\n"
            f"💾 В очереди (резерв): {stats['pending_queue']}"
        )

    def _recent_logs(self) -> str:
        msgs = self.db.get_recent_messages(10)
        if not msgs:
            return "📭 Нет записей в логах."
        lines = ["📋 Последние 10 сообщений:\n"]
        for m in msgs:
            arrow = "→" if m["direction"] == "out" else "←"
            who = m["to_user"] if m["direction"] == "out" else m["from_user"]
            preview = m["text"][:60] + ("..." if len(m["text"]) > 60 else "")
            lines.append(f"{m['created_at'][:16]} {arrow} {who}: {preview}")
        return "\n".join(lines)

    def _show_lm_history(self) -> str:
        history = self.db.get_lm_history(10)
        if not history:
            return "📭 История пуста."
        lines = ["📜 История диалога:\n"]
        for h in history:
            role = "Ты" if h["role"] == "user" else "Ассистент"
            preview = h["content"][:80] + ("..." if len(h["content"]) > 80 else "")
            lines.append(f"{role}: {preview}")
        return "\n".join(lines)
