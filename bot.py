import os, asyncio, logging, sqlite3, random, string
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, FSInputFile
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))

# ================== INIT ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())

# ================== DATABASE ==================
db = sqlite3.connect("bot.db")
c = db.cursor()
c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
c.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
db.commit()

def get_setting(key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default

def set_setting(key, val):
    c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(val)))
    db.commit()

def gen_code():
    return ''.join(random.choices(string.ascii_letters+string.digits, k=8))

# ================== ADMIN PANEL ==================
@dp.message(Command("settings"))
async def settings_panel(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Set Channel Post", callback_data="set:post")],
        [InlineKeyboardButton(text="📦 Set Channel DB", callback_data="set:db")],
        [InlineKeyboardButton(text="📝 Set Log Channel", callback_data="set:log")],
        [InlineKeyboardButton(text="🔒 Set Force Sub", callback_data="set:fsub")],
    ])
    await msg.answer("⚙️ PANEL ADMIN", reply_markup=kb)

class SetState(StatesGroup):
    waiting = State()

@dp.callback_query(F.data.startswith("set:"))
async def set_menu(cb: CallbackQuery, state:FSMContext):
    await state.set_state(SetState.waiting)
    await state.update_data(key=cb.data.split(":")[1])
    await cb.message.edit_text("Kirim ID / teks sekarang")

@dp.message(SetState.waiting)
async def save_setting(msg: Message, state:FSMContext):
    data = await state.get_data()
    set_setting(data['key'], msg.text)
    await msg.answer("✅ Disimpan")
    await state.clear()

# ================== START ==================
@dp.message(CommandStart())
async def start(msg: Message):
    c.execute("INSERT OR IGNORE INTO users VALUES (?)",(msg.from_user.id,))
    db.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Tanya Admin", callback_data="ask:start")],
        [InlineKeyboardButton(text="🎁 Donasi Konten", callback_data="donasi:start")]
    ])
    await msg.answer("Selamat datang 👋", reply_markup=kb)

# ================== FORCE SUB ==================
async def check_force(user_id):
    fsub = get_setting("fsub")
    if not fsub: return True
    for cid in fsub.split(","):
        try:
            member = await bot.get_chat_member(int(cid.strip()), user_id)
            if member.status not in ("member","administrator","creator"):
                return False
        except: return False
    return True

@dp.callback_query(F.data=="retry")
async def retry(cb: CallbackQuery):
    if await check_force(cb.from_user.id):
        await cb.message.edit_text("✅ Kamu sudah join")
    else:
        await cb.answer("Belum join semua!")

# ================== MEDIA AUTO POST ==================
@dp.message(F.content_type.in_({"photo","video","document"}))
async def save_media(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    code = gen_code()
    if msg.photo: file_id, mtype = msg.photo[-1].file_id, "photo"
    elif msg.video: file_id, mtype = msg.video.file_id, "video"
    elif msg.document: file_id, mtype = msg.document.file_id, "document"
    else: return
    c.execute("INSERT INTO media VALUES (?,?,?,?)",(code,file_id,mtype,msg.caption or ""))
    db.commit()
    dbch = get_setting("db")
    if dbch: await bot.copy_message(int(dbch), msg.chat.id, msg.message_id)
    postch = get_setting("post")
    if postch:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 NONTON", url=f"https://t.me/{(await bot.get_me()).username}?start={code}")]
        ])
        await bot.send_message(int(postch), msg.caption or "Konten baru", reply_markup=kb)

# ================== DONASI ==================
class DonasiState(StatesGroup):
    waiting = State()

@dp.callback_query(F.data=="donasi:start")
async def donasi_start(cb: CallbackQuery, state:FSMContext):
    await state.set_state(DonasiState.waiting)
    await cb.message.edit_text("Kirim foto/video donasi sekarang")

@dp.message(DonasiState.waiting, F.content_type.in_({"photo","video"}))
async def donasi_receive(msg: Message, state:FSMContext):
    for admin in ADMIN_IDS:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{msg.chat.id}:{msg.message_id}")]
        ])
        await bot.send_message(admin, f"Donasi dari @{msg.from_user.username or msg.from_user.id}", reply_markup=kb)
    await state.clear()

@dp.callback_query(F.data.startswith("approve:"))
async def approve(cb: CallbackQuery):
    _, chat_id, mid = cb.data.split(":")
    postch = get_setting("post")
    if postch:
        await bot.copy_message(int(postch), int(chat_id), int(mid))
    await cb.message.edit_text("✅ Donasi dipost")

# ================== ASK ADMIN ==================
class AskState(StatesGroup):
    waiting = State()

@dp.callback_query(F.data=="ask:start")
async def ask_start(cb: CallbackQuery, state:FSMContext):
    await state.set_state(AskState.waiting)
    await cb.message.edit_text("Kirim pertanyaanmu")

@dp.message(AskState.waiting)
async def ask_receive(msg: Message, state:FSMContext):
    for admin in ADMIN_IDS:
        await bot.send_message(admin, f"Pertanyaan dari @{msg.from_user.username or msg.from_user.id}:\n{msg.text}")
    await msg.answer("✅ Pertanyaan dikirim")
    await state.clear()

# ================== BROADCAST ==================
class BcState(StatesGroup):
    waiting = State()

@dp.message(Command("broadcast"))
async def bc_start(msg: Message, state:FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    await state.set_state(BcState.waiting)
    await msg.answer("Kirim teks broadcast")

@dp.message(BcState.waiting)
async def bc_send(msg: Message, state:FSMContext):
    users = c.execute("SELECT id FROM users").fetchall()
    for u in users:
        try: await bot.send_message(u[0], msg.text)
        except: pass
    await msg.answer("✅ Broadcast terkirim")
    await state.clear()

# ================== RUN ==================
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

