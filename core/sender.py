"""
Отправщик сообщений.
Отправляет сообщения другим пользователям от имени аккаунта-ассистента.
"""

import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import (
    UsernameNotOccupiedError,
    UsernameInvalidError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    FloodWaitError,
)
from telethon.tl.functions.contacts import ResolveUsernameRequest

log = logging.getLogger("Sender")


class MessageSender:
    def __init__(self, client: Optional[TelegramClient], settings):
        self.client = client
        self.settings = settings

    async def send_to(self, recipient: str, text: str) -> tuple[bool, str]:
        """
        Отправляет сообщение получателю.

        Args:
            recipient: @username, числовой ID или имя из контактов
            text: текст сообщения

        Returns:
            (успех, описание)
        """
        if not self.client:
            return False, "Telegram клиент не инициализирован"

        recipient = recipient.strip()
        log.info(f"📤 Отправка сообщения для: {recipient}")

        try:
            # Пробуем разрешить получателя
            entity = await self._resolve_recipient(recipient)
            if entity is None:
                return False, f"Пользователь '{recipient}' не найден"

            await self.client.send_message(entity, text)
            log.info(f"✅ Сообщение отправлено: {recipient}")
            return True, "ok"

        except UsernameNotOccupiedError:
            return False, f"Username '{recipient}' не существует"

        except UsernameInvalidError:
            return False, f"Некорректный username: '{recipient}'"

        except UserPrivacyRestrictedError:
            return False, f"Пользователь {recipient} ограничил входящие сообщения"

        except PeerFloodError:
            log.warning("PeerFloodError — слишком много запросов")
            return False, "Telegram ограничил отправку. Подожди немного."

        except FloodWaitError as e:
            return False, f"Flood wait: подожди {e.seconds} секунд"

        except Exception as e:
            log.error(f"Ошибка отправки {recipient}: {e}", exc_info=True)
            return False, str(e)

    async def _resolve_recipient(self, recipient: str):
        """Пытается найти пользователя по username, ID или имени."""
        # @username
        if recipient.startswith("@"):
            try:
                return await self.client.get_entity(recipient)
            except Exception:
                username = recipient[1:]
                try:
                    result = await self.client(ResolveUsernameRequest(username))
                    return result.peer
                except Exception as e:
                    log.warning(f"Не удалось разрешить {recipient}: {e}")
                    return None

        # Числовой ID
        if recipient.lstrip("-").isdigit():
            try:
                return await self.client.get_entity(int(recipient))
            except Exception as e:
                log.warning(f"Не удалось получить entity по ID {recipient}: {e}")
                return None

        # Имя контакта (ищем среди диалогов)
        try:
            async for dialog in self.client.iter_dialogs():
                if dialog.name and recipient.lower() in dialog.name.lower():
                    log.info(f"Найден контакт: '{dialog.name}' → {dialog.entity}")
                    return dialog.entity
        except Exception as e:
            log.warning(f"Ошибка поиска по имени '{recipient}': {e}")

        log.warning(f"Не удалось найти получателя: '{recipient}'")
        return None
