import asyncio
import uuid
import os
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

BOT_USERNAME = os.getenv("BOT_USERNAME")
CH_POST = os.getenv("CH_POST")  # channel auto post

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB = "media.db"

# ================= DB =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS media (
            code TEXT PRIMARY KEY,
            file_id TEXT,
            type TEXT,
            caption TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        await db.commit()

async def set_setting(k, v):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v)
        )
        await db.commit()

async def get_setting(k, default="0"):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE key=?", (k,)
        )
        r = await cur.fetchone()
        return r[0] if r else default

# ================= START =================
@dp.message(CommandStart())
async def start(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📂 Kirim Media", callback_data="send_media")]
    ])
    if m.from_user.id == ADMIN_ID:
        kb.inline_keyboard.append(
            [InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin_panel")]
        )
    await m.answer("👋 Selamat datang", reply_markup=kb)

# ================= ADMIN PANEL =================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(cb: CallbackQuery):
    anti = await get_setting("anti_forward")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            f"🛡 Anti Forward: {'ON' if anti=='1' else 'OFF'}",
            callback_data="toggle_antifwd"
        )],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="back_home")]
    ])
    await cb.message.edit_text("⚙️ PANEL ADMIN", reply_markup=kb)

@dp.callback_query(F.data == "toggle_antifwd")
async def toggle_antifwd(cb: CallbackQuery):
    cur = await get_setting("anti_forward")
    await set_setting("anti_forward", "0" if cur == "1" else "1")
    await admin_panel(cb)

# ================= BACK =================
@dp.callback_query(F.data == "back_home")
async def back_home(cb: CallbackQuery):
    await start(cb.message)

# ================= MEMBER SEND MEDIA =================
@dp.callback_query(F.data == "send_media")
async def send_media_info(cb: CallbackQuery):
    await cb.message.edit_text(
        "📤 Kirim foto / video\n\n"
        "• Admin → langsung post\n"
        "• Member → jadi donasi",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back_home")]
        ])
    )

@dp.message(F.photo | F.video)
async def handle_media(m: Message):
    fid = m.photo[-1].file_id if m.photo else m.video.file_id
    mtype = "photo" if m.photo else "video"

    if m.from_user.id == ADMIN_ID:
        code = uuid.uuid4().hex[:8]
        async with aiosqlite.connect(DB) as db:
            await db.execute(
                "INSERT INTO media VALUES (?,?,?,?)",
                (code, fid, mtype, "Konten")
            )
            await db.commit()

        link = f"https://t.me/{BOT_USERNAME}?start={code}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🎬 TONTON", url=link)]
        ])

        await bot.send_message(
            CH_POST,
            "🔥 Konten Baru",
            reply_markup=kb
        )
        return await m.answer("✅ Dipost")

    # MEMBER → DONASI
    await bot.send_message(
        ADMIN_ID,
        f"🎁 Donasi dari {m.from_user.full_name}"
    )
    await bot.forward_message(
        ADMIN_ID,
        m.chat.id,
        m.message_id,
        protect_content=True
    )
    await m.answer("✅ Donasi dikirim")

# ================= SEND MEDIA BY CODE =================
async def send_by_code(chat_id, code):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT file_id, type, caption FROM media WHERE code=?",
            (code,)
        )
        row = await cur.fetchone()

    if not row:
        return await bot.send_message(chat_id, "❌ Link tidak valid")

    protect = await get_setting("anti_forward") == "1"

    if row[1] == "photo":
        await bot.send_photo(
            chat_id, row[0], caption=row[2],
            protect_content=protect
        )
    else:
        await bot.send_video(
            chat_id, row[0], caption=row[2],
            protect_content=protect
        )

# ================= START WITH CODE =================
@dp.message(CommandStart())
async def start_code(m: Message):
    if len(m.text.split()) == 1:
        return
    code = m.text.split()[1]
    await send_by_code(m.chat.id, code)

# ================= RUN =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("BOT READY")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
