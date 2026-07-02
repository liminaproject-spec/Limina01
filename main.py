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
from core.database import Database
from core.monitor import MessageMonitor

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
    log.info("🚀 Запуск Умного ТГ Ассистента...")

    settings = Settings.load()
    db = Database()
    lm_client = LMStudioClient(settings)
    template_manager = TemplateManager(settings.templates_file)
    sender = MessageSender(None, settings)

    client = TelegramClient(settings.session_file, settings.api_id, settings.api_hash)
    sender.client = client

    handler = MessageHandler(settings, lm_client, template_manager, sender)
    monitor = MessageMonitor(client, settings, db)

    await client.start(phone=settings.phone_number)
    me = await client.get_me()
    log.info(f"✅ Авторизован как: {me.first_name} (@{me.username})")

    # ── 1. Команды от ВЛАДЕЛЬЦА ─────────────────────────
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

    # ── 2. Все входящие → монитор ───────────────────────
    @client.on(events.NewMessage(incoming=True))
    async def on_any_incoming(event):
        # Сначала монитор — логируем всё
        await monitor.on_new_message(event)

        # Потом проверяем — ответ через reply-систему?
        if event.sender_id == settings.owner_id:
            return  # владелец обрабатывается выше
        if event.out:
            return

        try:
            sender_entity = await event.get_sender()
            sender_username = (
                f"@{sender_entity.username}"
                if getattr(sender_entity, "username", None)
                else str(event.sender_id)
            )
        except Exception:
            sender_username = str(event.sender_id)

        forwarded = await handler.process_incoming_from_recipient(
            sender_id=event.sender_id,
            sender_username=sender_username,
            text=event.raw_text or "",
        )
        if forwarded:
            await client.send_message(settings.owner_id, forwarded)
            await event.respond("✅ Ваш ответ отправлен.")

    # ── 3. Детект удалённых сообщений ───────────────────
    @client.on(events.MessageDeleted())
    async def on_message_deleted(event):
        await monitor.on_deleted_message(event)

    log.info("👂 Ассистент слушает...")
    if settings.log_channels:
        log.info(f"📡 Лог-каналов: {len(settings.log_channels)} → {settings.log_channels}")
    else:
        log.warning("⚠️ LOG_CHANNELS не заданы — мониторинг выключен")
    log.info(f"📋 Шаблонов: {len(template_manager.templates)}")
    log.info(f"🤖 LM Studio: {settings.lm_studio_url}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
