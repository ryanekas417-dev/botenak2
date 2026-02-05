# TELEGRAM BOT FULL FEATURE – FINAL BUILD
# AIROGRAM v3 | RAILWAY READY
# ======================================
# ALL SETTINGS VIA ADMIN PANEL (INLINE)
# BOT TOKEN & ADMIN IDS VIA ENV
# DB CHANNEL AS PERMANENT MEMORY CORE
# ======================================

import os
import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ChatPermissions, FSInputFile,
    ChatMemberUpdated
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# ================= LOG =================
logging.basicConfig(level=logging.INFO)

# ================= BOT =================
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================= DATABASE =================
conn = sqlite3.connect("media.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
DROP TABLE IF EXISTS users
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    joined_at TEXT
)
""")

conn.commit()
);

CREATE TABLE IF NOT EXISTS media (
  code TEXT PRIMARY KEY,
  file_id TEXT,
  file_type TEXT,
  created TEXT
);

CREATE TABLE IF NOT EXISTS fsub (
  channel_id INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
""")
conn.commit()

# ================= UTILS =================
def is_admin(uid:int):
    return uid in ADMIN_IDS


def get_setting(key, default=""):
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    r = cur.fetchone()
    return r[0] if r else default


def set_setting(key, val):
    cur.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, val))
    conn.commit()


async def check_fsub(user_id:int):
    cur.execute("SELECT channel_id FROM fsub")
    chans = [c[0] for c in cur.fetchall()]
    for ch in chans:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status not in ("member","administrator","creator"):
                return False
        except:
            return False
    return True


async def log_event(text:str):
    log_ch = get_setting("log_channel")
    if log_ch:
        try:
            await bot.send_message(int(log_ch), text)
        except:
            pass

# ================= FSM =================
class AskFSM(StatesGroup):
    text = State()

class DonateFSM(StatesGroup):
    media = State()

class PostFSM(StatesGroup):
    media = State()
    title = State()
    cover = State()

# ================= START =================
@dp.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    uname = message.from_user.username

    cur.execute(
        "INSERT OR IGNORE INTO users VALUES (?,?,?)",
        (uid, uname, datetime.utcnow().isoformat())
    )
    conn.commit()

    await log_event(
        f"▶️ START\nID: <code>{uid}</code>\n@{uname}"
    )

    args = message.text.split(maxsplit=1)

    if len(args) == 2:
        code = args[1]

        if not await check_fsub(uid):
            kb = []
            cur.execute("SELECT channel_id FROM fsub")
            for ch in cur.fetchall():
                kb.append([
                    InlineKeyboardButton(
                        text="Join",
                        url=f"https://t.me/c/{str(abs(ch[0]))[3:]}"
                    )
                ])
            kb.append([
                InlineKeyboardButton(
                    text="🔄 COBA LAGI",
                    callback_data=f"retry_{code}"
                )
            ])
            await message.answer(
                get_setting("fsub_text", "Wajib join dulu"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
            return

        cur.execute("SELECT file_id,file_type FROM media WHERE code=?", (code,))
        r = cur.fetchone()
        if not r:
            await message.answer("Konten tidak ditemukan")
            return

        fid, ftype = r
        if ftype == "photo": await message.answer_photo(fid)
        elif ftype == "video": await message.answer_video(fid)
        elif ftype == "document": await message.answer_document(fid)
        elif ftype == "animation": await message.answer_animation(fid)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ask Admin", callback_data="ask")],
        [InlineKeyboardButton(text="🎁 Donasi", callback_data="donate")]
    ])

    await message.answer(
        get_setting("start_text", "Welcome"),
        reply_markup=kb
    )

# ================= JOIN / LEAVE LOG =================
@dp.chat_member()
async def member_update(event: ChatMemberUpdated):
    user = event.from_user
    chat = event.chat

    if event.old_chat_member.status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED
    ) and event.new_chat_member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR
    ):
        await log_event(
            f"➕ JOIN\nChat: {chat.title}\nID: <code>{user.id}</code>\n@{user.username}"
        )

    if event.new_chat_member.status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED
    ):
        await log_event(
            f"➖ LEAVE\nChat: {chat.title}\nID: <code>{user.id}</code>\n@{user.username}"
        )

# ================= CALLBACK =================
@dp.callback_query(F.data.startswith("retry_"))
async def retry(cb:CallbackQuery):
    code = cb.data.split("_",1)[1]
    if await check_fsub(cb.from_user.id):
        await cb.message.edit_text("✅ Akses dibuka")
        await start(Message(**cb.message.model_dump(), text=f"/start {code}"))
    else:
        await cb.answer("Masih belum join", show_alert=True)

@dp.callback_query(F.data=="ask")
async def ask(cb:CallbackQuery, state:FSMContext):
    await cb.message.edit_text("Tulis pertanyaanmu")
    await state.set_state(AskFSM.text)

@dp.message(AskFSM.text)
async def ask_send(message:Message, state:FSMContext):
    for a in ADMIN_IDS:
        await bot.send_message(
            a,
            f"❓ ASK\nID: <code>{message.from_user.id}</code>\n@{message.from_user.username}\n\n{message.text}"
        )
    await message.answer("Terkirim ke admin")
    await state.clear()

@dp.callback_query(F.data=="donate")
async def donate(cb:CallbackQuery, state:FSMContext):
    await cb.message.edit_text("Kirim media donasi")
    await state.set_state(DonateFSM.media)

# ================= DONASI AUTO POST =================
@dp.message(DonateFSM.media)
async def donate_recv(message:Message, state:FSMContext):
    for a in ADMIN_IDS:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE", callback_data=f"approve_{message.message_id}")]])
        await message.copy_to(a, reply_markup=kb)
    await message.answer("Donasi dikirim ke admin")
    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def approve_donation(cb:CallbackQuery):
    msg = cb.message.reply_to_message
    if not msg:
        return

    code = uuid.uuid4().hex[:8]
    if msg.video:
        fid = msg.video.file_id; ftype="video"
    else:
        fid = msg.photo[-1].file_id; ftype="photo"

    cur.execute(
        "INSERT INTO media VALUES (?,?,?,?)",
        (code,fid,ftype,datetime.utcnow().isoformat())
    )
    conn.commit()

    post_ch = get_setting("post_channel")
    btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 NONTON", url=f"https://t.me/{(await bot.me()).username}?start={code}")]])

    if post_ch:
        await bot.send_message(int(post_ch), "🎁 Donasi Baru", reply_markup=btn)

    await cb.answer("Donasi dipost")

# ================= AUTO POST ADMIN =================
@dp.message(F.content_type.in_({"photo","video"}))
async def admin_autopost(message:Message, state:FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(media=message)
    await message.answer("Judul post?")
    await state.set_state(PostFSM.title)

@dp.message(PostFSM.title)
async def post_title(message:Message, state:FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Kirim cover/poster")
    await state.set_state(PostFSM.cover)

@dp.message(PostFSM.cover)
async def post_finish(message:Message, state:FSMContext):
    data = await state.get_data()
    media_msg = data["media"]
    title = data["title"]

    code = uuid.uuid4().hex[:8]

    if media_msg.video:
        fid = media_msg.video.file_id; ftype="video"
    else:
        fid = media_msg.photo[-1].file_id; ftype="photo"

    cur.execute(
        "INSERT INTO media VALUES (?,?,?,?)",
        (code,fid,ftype,datetime.utcnow().isoformat())
    )
    conn.commit()

    post_ch = get_setting("post_channel")
    btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 NONTON", url=f"https://t.me/{(await bot.me()).username}?start={code}")]])

    if post_ch:
        await bot.send_photo(int(post_ch), message.photo[-1].file_id, caption=title, reply_markup=btn)

    await message.answer("✅ Auto post sukses")
    await state.clear()

# ================= ADMIN PANEL =================
@dp.message(Command("settings"))
async def settings_panel(message:Message):
    if not is_admin(message.from_user.id): return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add FSUB", callback_data="add_fsub")],
        [InlineKeyboardButton(text="📝 Set Start Text", callback_data="set_start")],
        [InlineKeyboardButton(text="📝 Set FSUB Text", callback_data="set_fsub")],
        [InlineKeyboardButton(text="📢 Set Post Channel", callback_data="set_post")],
        [InlineKeyboardButton(text="📜 Set Log Channel", callback_data="set_log")]
    ])

    await message.answer("⚙️ PANEL ADMIN", reply_markup=kb)

# ================= PANEL HANDLERS =================
@dp.callback_query(F.data=="add_fsub")
async def p_add_fsub(cb:CallbackQuery):
    await cb.message.edit_text("Kirim ID channel FSUB")

@dp.message(F.text.regexp(r"^-100\d+"))
async def save_channel_ids(message:Message):
    if not is_admin(message.from_user.id): return

    text = message.text
    cur.execute("INSERT OR IGNORE INTO fsub VALUES (?)", (int(text),))
    conn.commit()
    await message.answer("Channel disimpan")

@dp.callback_query(F.data=="set_start")
async def p_set_start(cb:CallbackQuery):
    await cb.message.edit_text("Kirim teks start baru")
    set_setting("_mode","start")

@dp.callback_query(F.data=="set_fsub")
async def p_set_fsub(cb:CallbackQuery):
    await cb.message.edit_text("Kirim teks FSUB")
    set_setting("_mode","fsub")

@dp.callback_query(F.data=="set_post")
async def p_set_post(cb:CallbackQuery):
    await cb.message.edit_text("Kirim ID channel post")
    set_setting("_mode","post")

@dp.callback_query(F.data=="set_log")
async def p_set_log(cb:CallbackQuery):
    await cb.message.edit_text("Kirim ID channel log")
    set_setting("_mode","log")

@dp.message(F.text)
async def save_settings_text(message:Message):
    if not is_admin(message.from_user.id): return

    mode = get_setting("_mode")
    if mode == "start": set_setting("start_text", message.text)
    if mode == "fsub": set_setting("fsub_text", message.text)
    if mode == "post": set_setting("post_channel", message.text)
    if mode == "log": set_setting("log_channel", message.text)

    if mode:
        set_setting("_mode", "")
        await message.answer("✅ Disimpan")

# ================= BACKUP DB CHANNEL =================
@dp.message(Command("senddb"))
async def send_db(message:Message):
    if not is_admin(message.from_user.id): return
    await message.answer_document(FSInputFile("media.db"))

# ================= STATS =================
@dp.message(Command("stats"))
async def stats(message:Message):
    if not is_admin(message.from_user.id): return
    u = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    m = cur.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    await message.answer(f"👤 Users: {u}\n🎞 Media: {m}")

# ================= MAIN =================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


