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
from core.account_monitor import AccountMonitor

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
    monitor = MessageMonitor(client, settings, db, notify_client=client)

    await client.start(phone=settings.phone_number)
    me = await client.get_me()
    log.info(f"✅ Ассистент: {me.first_name} (@{me.username})")

    # ID лог-каналов — чтобы не слушать свои же сообщения туда
    log_channel_ids = set()
    for ch in settings.log_channels:
        try:
            entity = await client.get_entity(ch)
            log_channel_ids.add(entity.id)
        except Exception as e:
            log.warning(f"Не удалось получить ID канала {ch}: {e}")

    log.info(f"🔕 Игнорируем чаты (лог-каналы): {log_channel_ids}")

    # ── 1. Команды от ВЛАДЕЛЬЦА ──────────────────────────
    # Только личные сообщения (не из каналов/групп)
    @client.on(events.NewMessage(incoming=True, from_users=settings.owner_id))
    async def on_owner_message(event):
        # Игнорируем если сообщение пришло из лог-канала
        chat = await event.get_chat()
        if getattr(chat, 'id', None) in log_channel_ids:
            return
        # Игнорируем групповые чаты — только личка
        if event.is_group or event.is_channel:
            return

        text = event.raw_text.strip()
        if not text:
            return

        log.info(f"📨 От владельца: {text[:80]}")
        async with client.action(event.chat_id, "typing"):
            response = await handler.process(text, event)
        if response:
            await event.respond(response)

    # ── 2. Все входящие на аккаунт АССИСТЕНТА → монитор ─
    @client.on(events.NewMessage(incoming=True))
    async def on_any_incoming(event):
        # Пропускаем исходящие
        if event.out:
            return
        # Пропускаем сообщения из лог-каналов (не мониторим их)
        chat = await event.get_chat()
        if getattr(chat, 'id', None) in log_channel_ids:
            return

        # Только реальные входящие → в лог-канал
        await monitor.on_new_message(
            event,
            account_label=f"{me.first_name} (@{me.username})"
        )

        # Проверяем reply-систему (не для владельца)
        if event.sender_id == settings.owner_id:
            return

        try:
            sender_e = await event.get_sender()
            uname = f"@{sender_e.username}" if getattr(sender_e, "username", None) else str(event.sender_id)
        except Exception:
            uname = str(event.sender_id)

        forwarded = await handler.process_incoming_from_recipient(
            sender_id=event.sender_id,
            sender_username=uname,
            text=event.raw_text or "",
        )
        if forwarded:
            await client.send_message(settings.owner_id, forwarded)
            await event.respond("✅ Ваш ответ отправлен.")

    # ── 3. Удалённые сообщения на аккаунте АССИСТЕНТА ───
    @client.on(events.MessageDeleted())
    async def on_deleted(event):
        await monitor.on_deleted_message(event)

    # ── 4. Мониторинг ДОПОЛНИТЕЛЬНЫХ аккаунтов ──────────
    acc_monitor = AccountMonitor(settings, db, settings.log_channels)
    # Передаём клиент Лимины — она будет писать владельцу об удалённых
    await acc_monitor.start_all(log_channel_ids, limina_client=client)

    log.info("👂 Ассистент слушает...")
    if settings.log_channels:
        log.info(f"📡 Лог-каналы: {settings.log_channels}")
    if settings.monitored_accounts:
        log.info(f"👁 Доп. аккаунты: {settings.monitored_accounts}")

    try:
        await client.run_until_disconnected()
    finally:
        await acc_monitor.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
