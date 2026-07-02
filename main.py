"""
╔══════════════════════════════════════════════════════╗
║         УМНЫЙ ТГ АССИСТЕНТ + LM Studio               ║
╚══════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import sys
from pathlib import Path

from telethon import TelegramClient, events

from config.settings import Settings
from core.lm_client import LMStudioClient
from core.template_manager import TemplateManager
from core.message_handler import MessageHandler
from core.sender import MessageSender

# ─── Логирование ───────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/assistant.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("Assistant")


async def main():
    log.info("🚀 Запуск L. I. M. I. N. A....")

    settings = Settings.load()
    lm_client = LMStudioClient(settings)
    template_manager = TemplateManager(settings.templates_file)
    sender = MessageSender(None, settings)

    client = TelegramClient(settings.session_file, settings.api_id, settings.api_hash)
    sender.client = client

    handler = MessageHandler(settings, lm_client, template_manager, sender)

    await client.start(phone=settings.phone_number)
    me = await client.get_me()
    log.info(f"✅ Авторизован как: {me.first_name} (@{me.username})")

    # ── Сообщения от ВЛАДЕЛЬЦА (тебя) ──────────────────
    @client.on(events.NewMessage(incoming=True, from_users=settings.owner_id))
    async def on_owner_message(event):
        text = event.raw_text.strip()
        if not text:
            return
        log.info(f"📨 От владельца: {text[:80]}")
        async with client.action(event.chat_id, "typing"):
            response = await handler.process(text, event)
        if response:
            await event.respond(response)

    # ── Сообщения от ВСЕХ ОСТАЛЬНЫХ ────────────────────
    # Это получатели которые отвечают через аккаунт ассистента
    @client.on(events.NewMessage(incoming=True))
    async def on_recipient_message(event):
        sender_id = event.sender_id
        # Пропускаем сообщения от владельца (они обрабатываются выше)
        if sender_id == settings.owner_id:
            return
        # Пропускаем свои исходящие
        if event.out:
            return

        text = event.raw_text.strip()
        if not text:
            return

        try:
            sender_entity = await event.get_sender()
            sender_username = f"@{sender_entity.username}" if sender_entity.username else str(sender_id)
        except Exception:
            sender_username = str(sender_id)

        log.info(f"📨 От получателя {sender_username}: {text[:60]}")

        # Проверяем — это ответ через reply-систему?
        forwarded = await handler.process_incoming_from_recipient(
            sender_id=sender_id,
            sender_username=sender_username,
            text=text,
        )

        if forwarded:
            # Пересылаем тебе (владельцу)
            try:
                await client.send_message(settings.owner_id, forwarded)
                log.info(f"✅ Ответ от {sender_username} переслан владельцу")
                # Подтверждаем получателю
                await event.respond("✅ Ваш ответ отправлен.")
            except Exception as e:
                log.error(f"Не удалось переслать ответ владельцу: {e}")

    log.info("👂 Ассистент слушает... (Ctrl+C для остановки)")
    log.info(f"📋 Шаблонов: {len(template_manager.templates)}")
    log.info(f"🤖 LM Studio: {settings.lm_studio_url}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
