import asyncio
from telethon import TelegramClient

API_ID = 17349
API_HASH = "344583e45741c457fe1862106095a5eb"
PHONE = "+17532006034"  # номер аккаунта-ассистента

async def main():
    client = TelegramClient("assistant_session", API_ID, API_HASH)
    await client.start(phone=PHONE)

    me = await client.get_me()
    print(f"\n✅ Авторизован как: {me.first_name} (@{me.username})")
    print(f"📌 Твой Telegram ID: {me.id}")
    print(f"\n📋 Вставь в .env:")
    print(f"TG_API_ID=17349")
    print(f"TG_API_HASH=344583e45741c457fe1862106095a5eb")
    print(f"TG_PHONE={PHONE}")
    print(f"TG_OWNER_ID={me.id}")

    await client.disconnect()

asyncio.run(main())
