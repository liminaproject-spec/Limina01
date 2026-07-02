"""
База данных — SQLite.
Хранит все сообщения, ожидающие ответа, и историю диалогов.
"""

import sqlite3
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("Database")

DB_PATH = "data/assistant.db"


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        """Создаёт таблицы если не существуют."""
        with self._conn() as conn:
            conn.executescript("""
                -- Все отправленные сообщения
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    direction   TEXT    NOT NULL,  -- 'out' (отправлено) / 'in' (получено)
                    from_user   TEXT,
                    to_user     TEXT,
                    text        TEXT    NOT NULL,
                    template    TEXT,              -- кодовое слово шаблона если был
                    status      TEXT    DEFAULT 'sent',  -- sent/delivered/replied/failed
                    reply_to_id INTEGER,           -- ID сообщения на которое это ответ
                    tg_msg_id   INTEGER            -- ID сообщения в Telegram
                );

                -- Ожидающие ответа (reply-сессии)
                CREATE TABLE IF NOT EXISTS reply_sessions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    message_id      INTEGER NOT NULL,   -- ID в таблице messages
                    recipient_id    INTEGER NOT NULL,   -- TG ID получателя
                    recipient_user  TEXT    NOT NULL,   -- @username получателя
                    original_text   TEXT    NOT NULL,   -- текст отправленного сообщения
                    reply_token     TEXT    UNIQUE,     -- уникальный токен для идентификации
                    is_active       INTEGER DEFAULT 1,  -- 1 = ждём ответа
                    replied_at      TEXT,
                    FOREIGN KEY (message_id) REFERENCES messages(id)
                );

                -- История диалога с нейронкой (персистентная)
                CREATE TABLE IF NOT EXISTS lm_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    role        TEXT    NOT NULL,   -- user/assistant
                    content     TEXT    NOT NULL
                );

                -- Резервные копии сообщений (до отправки)
                CREATE TABLE IF NOT EXISTS message_queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    recipient   TEXT    NOT NULL,
                    text        TEXT    NOT NULL,
                    status      TEXT    DEFAULT 'pending',  -- pending/sent/failed
                    attempts    INTEGER DEFAULT 0,
                    last_error  TEXT
                );
            """)
        log.info(f"✅ База данных инициализирована: {self.db_path}")

    # ─────────────────────────────────────────────────────
    # СООБЩЕНИЯ
    # ─────────────────────────────────────────────────────

    def log_message(
        self,
        direction: str,
        text: str,
        from_user: str = None,
        to_user: str = None,
        template: str = None,
        status: str = "sent",
        reply_to_id: int = None,
        tg_msg_id: int = None,
    ) -> int:
        """Записывает сообщение в БД. Возвращает ID записи."""
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO messages
                   (direction, from_user, to_user, text, template, status, reply_to_id, tg_msg_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (direction, from_user, to_user, text, template, status, reply_to_id, tg_msg_id),
            )
            msg_id = cur.lastrowid
        log.debug(f"💾 Сообщение записано: id={msg_id} dir={direction} to={to_user}")
        return msg_id

    def update_message_status(self, msg_id: int, status: str):
        with self._conn() as conn:
            conn.execute("UPDATE messages SET status=? WHERE id=?", (status, msg_id))

    def get_message(self, msg_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
            return dict(row) if row else None

    def get_recent_messages(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────
    # REPLY СЕССИИ
    # ─────────────────────────────────────────────────────

    def create_reply_session(
        self,
        message_id: int,
        recipient_id: int,
        recipient_user: str,
        original_text: str,
        reply_token: str,
    ) -> int:
        """Создаёт сессию ожидания ответа."""
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO reply_sessions
                   (message_id, recipient_id, recipient_user, original_text, reply_token)
                   VALUES (?, ?, ?, ?, ?)""",
                (message_id, recipient_id, recipient_user, original_text, reply_token),
            )
            return cur.lastrowid

    def get_active_session_by_user(self, recipient_id: int) -> Optional[dict]:
        """Ищет активную reply-сессию для пользователя по его TG ID."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM reply_sessions
                   WHERE recipient_id=? AND is_active=1
                   ORDER BY created_at DESC LIMIT 1""",
                (recipient_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_active_session_by_token(self, token: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM reply_sessions WHERE reply_token=? AND is_active=1",
                (token,),
            ).fetchone()
            return dict(row) if row else None

    def close_reply_session(self, session_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE reply_sessions SET is_active=0, replied_at=datetime('now') WHERE id=?",
                (session_id,),
            )

    def get_all_active_sessions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reply_sessions WHERE is_active=1 ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────
    # ОЧЕРЕДЬ (резервирование)
    # ─────────────────────────────────────────────────────

    def queue_message(self, recipient: str, text: str) -> int:
        """Добавляет сообщение в очередь ДО отправки (резерв)."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO message_queue (recipient, text) VALUES (?, ?)",
                (recipient, text),
            )
            return cur.lastrowid

    def mark_queue_sent(self, queue_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE message_queue SET status='sent' WHERE id=?", (queue_id,)
            )

    def mark_queue_failed(self, queue_id: int, error: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE message_queue SET status='failed', attempts=attempts+1, last_error=? WHERE id=?",
                (error, queue_id),
            )

    def get_pending_queue(self) -> list[dict]:
        """Возвращает неотправленные сообщения (для повторной отправки)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM message_queue WHERE status='pending' AND attempts < 3"
            ).fetchall()
            return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────
    # ИСТОРИЯ LM (персистентная)
    # ─────────────────────────────────────────────────────

    def save_lm_turn(self, role: str, content: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO lm_history (role, content) VALUES (?, ?)", (role, content)
            )

    def get_lm_history(self, last_n: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM lm_history ORDER BY id DESC LIMIT ?", (last_n,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_lm_history(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM lm_history")

    # ─────────────────────────────────────────────────────
    # СТАТИСТИКА
    # ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sent = conn.execute("SELECT COUNT(*) FROM messages WHERE direction='out'").fetchone()[0]
            received = conn.execute("SELECT COUNT(*) FROM messages WHERE direction='in'").fetchone()[0]
            active_sessions = conn.execute(
                "SELECT COUNT(*) FROM reply_sessions WHERE is_active=1"
            ).fetchone()[0]
            pending_queue = conn.execute(
                "SELECT COUNT(*) FROM message_queue WHERE status='pending'"
            ).fetchone()[0]
        return {
            "total_messages": total,
            "sent": sent,
            "received": received,
            "active_reply_sessions": active_sessions,
            "pending_queue": pending_queue,
        }
