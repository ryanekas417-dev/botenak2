# =============================
# TELEGRAM BOT – FINAL VERSION
# Aiogram 3.7+
# Semua fitur sesuai request user
# =============================

import os
import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import *
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# =============================
# ENV (Railway)
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# =============================
# BOT INIT
# =============================
logging.basicConfig(level=logging.INFO)
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# =============================
# DATABASE INIT
# =============================
conn = sqlite3.connect("media.db")
cur = conn.cursor()

# USERS (AUTO RESET SAFE)
cur.execute("DROP TABLE IF EXISTS users")
cur.execute("""
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    joined_at TEXT
)
""")

# MEDIA DB
cur.execute("""
CREATE TABLE IF NOT EXISTS media (
    code TEXT PRIMARY KEY,
    file_id TEXT,
    file_type TEXT,
    created_at TEXT
)
""")

# SETTINGS
cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

conn.commit()

# =============================
# DEFAULT SETTINGS
# =============================
def set_default(key, value):
    cur.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, value))
    conn.commit()

set_default("start_text", "Selamat datang 👋")
set_default("forbidden_words", "biyo,promosi,bio,biyoh")
set_default("fsub_links", "")
set_default("fsub_join_link", "")=====
# RUN
# =============================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
if not await check_fsub(uid):
        cur.execute("SELECT value FROM settings WHERE key='fsub_join_link'")
        join_link = cur.fetchone()[0]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 JOIN SEKARANG", url=join_link)] if join_link else [],
            [InlineKeyboardButton(text="🔄 COBA LAGI", callback_data="retry_fsub")]
        ])
