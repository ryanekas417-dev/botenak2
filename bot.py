import asyncio
import os
import uuid
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DB = "bot.db"

# ================= STATES =================
class ChannelPost(StatesGroup):
    waiting_title = State()
    waiting_media = State()

class AddFSubCheck(StatesGroup):
    waiting_link = State()

class AddFSubList(StatesGroup):
    waiting_link = State()

class SetChannel(StatesGroup):
    waiting_channel = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS media (
            code TEXT PRIMARY KEY,
            file_id TEXT,
            type TEXT,
            caption TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS fsub_check (
            link TEXT PRIMARY KEY
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS fsub_list (
            link TEXT PRIMARY KEY
        )""")

        await db.commit()

async def get_setting(key, default=None):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_setting(key, value):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)",
            (key, value)
        )
        await db.commit()

# ================= FORCE SUB =================
async def check_fsub(user_id: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT link FROM fsub_check")
        rows = await cur.fetchall()

    for (link,) in rows:
        try:
            username = link.replace("https://t.me/", "").replace("@", "")
            m = await bot.get_chat_member(f"@{username}", user_id)
            if m.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False
    return True

async def get_fsub_buttons():
    async with aiosqlite.connect(DB) as db:
        check = await db.execute("SELECT link FROM fsub_check")
        list_ = await db.execute("SELECT link FROM fsub_list")

        check_links = [r[0] for r in await check.fetchall()]
        list_links = [r[0] for r in await list_.fetchall()]

    return check_links + list_links

# ================= START =================
@dp.message(CommandStart())
async def start(m: Message):
    args = m.text.split(maxsplit=1)

    if len(args) == 2:
        code = args[1]
        if not await check_fsub(m.from_user.id):
            links = await get_fsub_buttons()
            kb = [
                [InlineKeyboardButton(text=f"🔔 Join {i+1}", url=l)]
                for i, l in enumerate(links)
            ]
            kb.append([
                InlineKeyboardButton(
                    text="🔄 Coba Lagi",
                    callback_data=f"retry:{code}"
                )
            ])
            return await m.answer(
                "🚫 Join dulu semua lalu klik **Coba Lagi**",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )

        await send_media(m.chat.id, code)
        return

    kb = [
        [InlineKeyboardButton(text="🎁 Donasi", callback_data="donasi")],
        [InlineKeyboardButton(text="💬 Ask Admin", callback_data="ask")]
    ]

    if m.from_user.id == ADMIN_ID:
        kb.append([
            InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="admin")
        ])

    await m.answer("👋 Selamat datang", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ================= RETRY =================
@dp.callback_query(F.data.startswith("retry:"))
async def retry(cb: CallbackQuery):
    code = cb.data.split(":", 1)[1]
    if not await check_fsub(cb.from_user.id):
        return await cb.answer("❌ Belum join semua", show_alert=True)

    await cb.message.delete()
    await send_media(cb.from_user.id, code)

# ================= SEND MEDIA =================
async def send_media(chat_id: int, code: str):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT file_id, type, caption FROM media WHERE code=?",
            (code,)
        )
        row = await cur.fetchone()

    if not row:
        return await bot.send_message(chat_id, "❌ Konten tidak ditemukan")

    protect = (await get_setting("antifwd", "0")) == "1"
    fid, mtype, cap = row

    if mtype == "photo":
        await bot.send_photo(chat_id, fid, caption=cap, protect_content=protect)
    else:
        await bot.send_video(chat_id, fid, caption=cap, protect_content=protect)

# ================= DONASI & ASK =================
@dp.callback_query(F.data == "donasi")
async def donasi(cb: CallbackQuery):
    await cb.message.answer("🎁 Kirim media atau pesan donasi")

@dp.message(F.chat.type == "private")
async def handle_private(m: Message):
    if m.from_user.id == ADMIN_ID:
        return

    await bot.forward_message(
        ADMIN_ID,
        m.chat.id,
        m.message_id
    )

@dp.callback_query(F.data == "ask")
async def ask(cb: CallbackQuery):
    await cb.message.answer("💬 Kirim pesan kamu, admin akan menerima")

# ================= ADMIN PANEL =================
@dp.callback_query(F.data == "admin")
async def admin(cb: CallbackQuery):
    antifwd = await get_setting("antifwd", "0")
    kb = [
        [InlineKeyboardButton(
            text=f"🛡 Anti Forward: {'ON' if antifwd=='1' else 'OFF'}",
            callback_data="toggle_antifwd"
        )],
        [InlineKeyboardButton(text="📢 Set Channel Post", callback_data="set_channel")],
        [InlineKeyboardButton(text="➕ Add FSub Check", callback_data="add_fsub_check")],
        [InlineKeyboardButton(text="➕ Add FSub List", callback_data="add_fsub_list")],
        [InlineKeyboardButton(text="📤 Channel Post", callback_data="channel_post")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="back")]
    ]
    await cb.message.edit_text("⚙️ PANEL ADMIN", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "toggle_antifwd")
async def toggle(cb: CallbackQuery):
    cur = await get_setting("antifwd", "0")
    await set_setting("antifwd", "0" if cur == "1" else "1")
    await admin(cb)

# ================= CHANNEL POST =================
@dp.callback_query(F.data == "set_channel")
async def set_ch(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📢 Kirim @username channel")
    await state.set_state(SetChannel.waiting_channel)

@dp.message(SetChannel.waiting_channel)
async def save_ch(m: Message, state: FSMContext):
    await set_setting("post_channel", m.text.strip())
    await state.clear()
    await m.answer("✅ Channel disimpan")

@dp.callback_query(F.data == "channel_post")
async def channel_post(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Kirim judul konten")
    await state.set_state(ChannelPost.waiting_title)

@dp.message(ChannelPost.waiting_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(ChannelPost.waiting_media)
    await m.answer("📸 Kirim media")

@dp.message(ChannelPost.waiting_media, F.photo | F.video)
async def post_channel(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]

    fid = m.photo[-1].file_id if m.photo else m.video.file_id
    mtype = "photo" if m.photo else "video"

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO media VALUES (?,?,?,?)",
            (code, fid, mtype, data["title"])
        )
        await db.commit()

    ch = await get_setting("post_channel")
    botname = (await bot.me()).username
    link = f"https://t.me/{botname}?start={code}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 NONTON", url=link)]
    ])

    await (bot.send_photo if mtype=="photo" else bot.send_video)(
        ch, fid, caption=data["title"], reply_markup=kb
    )

    await m.answer("✅ Berhasil dipost ke channel")
    await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
