import asyncio, os, uuid, aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
DB = "bot.db"

# ================= STATES =================
class AutoPost(StatesGroup):
    title = State()
    cover = State()

class SetChannel(StatesGroup):
    ch = State()

class FSubCheck(StatesGroup):
    link = State()

class FSubList(StatesGroup):
    link = State()

# ================= DB =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS media
            (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings
            (key TEXT PRIMARY KEY, value TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS fsub_check (link TEXT PRIMARY KEY)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS fsub_list (link TEXT PRIMARY KEY)""")
        await db.commit()

async def set_setting(k,v):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(k,v))
        await db.commit()

async def get_setting(k,d=None):
    async with aiosqlite.connect(DB) as db:
        r = await (await db.execute(
            "SELECT value FROM settings WHERE key=?",(k,))
        ).fetchone()
        return r[0] if r else d

# ================= START =================
@dp.message(CommandStart())
async def start(m: Message):
    kb = [
        [InlineKeyboardButton(text="🎁 Donasi", callback_data="donasi")],
        [InlineKeyboardButton(text="💬 Ask Admin", callback_data="ask")]
    ]
    if m.from_user.id == ADMIN_ID:
        kb.append([InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="admin")])
    await m.answer("👋 Selamat datang", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# ================= MEMBER MSG =================
@dp.message(F.chat.type=="private", F.from_user.id != ADMIN_ID)
async def member_msg(m: Message):
    await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
    await m.answer("✅ Pesan kamu sudah terkirim ke admin")

# ================= ADMIN PANEL =================
@dp.callback_query(F.data=="admin")
async def admin_panel(cb: CallbackQuery):
    af = await get_setting("antifwd","0")
    kb = [
        [InlineKeyboardButton(
            text=f"🛡 Anti Forward: {'ON' if af=='1' else 'OFF'}",
            callback_data="toggle_af")],
        [InlineKeyboardButton(text="📢 Set Channel Post", callback_data="set_ch")],
        [InlineKeyboardButton(text="➕ Add FSub Check", callback_data="add_fc")],
        [InlineKeyboardButton(text="➕ Add FSub List", callback_data="add_fl")]
    ]
    await cb.message.edit_text("⚙️ PANEL ADMIN",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data=="toggle_af")
async def toggle_af(cb: CallbackQuery):
    cur = await get_setting("antifwd","0")
    await set_setting("antifwd","0" if cur=="1" else "1")
    await admin_panel(cb)

# ================= SET CHANNEL =================
@dp.callback_query(F.data=="set_ch")
async def set_ch(cb: CallbackQuery, state:FSMContext):
    await cb.message.edit_text("📢 Kirim @channel tujuan post")
    await state.set_state(SetChannel.ch)

@dp.message(SetChannel.ch, F.from_user.id==ADMIN_ID)
async def save_ch(m: Message, state:FSMContext):
    await set_setting("post_channel", m.text.strip())
    await m.answer("✅ Channel berhasil disimpan")
    await state.clear()

# ================= FSUB =================
@dp.callback_query(F.data=="add_fc")
async def add_fc(cb: CallbackQuery, state:FSMContext):
    await cb.message.edit_text("➕ Kirim link channel (wajib join)")
    await state.set_state(FSubCheck.link)

@dp.message(FSubCheck.link, F.from_user.id==ADMIN_ID)
async def save_fc(m: Message, state:FSMContext):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO fsub_check VALUES (?)",(m.text,))
        await db.commit()
    await m.answer("✅ FSub Check ditambahkan")
    await state.clear()

@dp.callback_query(F.data=="add_fl")
async def add_fl(cb: CallbackQuery, state:FSMContext):
    await cb.message.edit_text("➕ Kirim link (tombol join saja)")
    await state.set_state(FSubList.link)

@dp.message(FSubList.link, F.from_user.id==ADMIN_ID)
async def save_fl(m: Message, state:FSMContext):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO fsub_list VALUES (?)",(m.text,))
        await db.commit()
    await m.answer("✅ FSub List ditambahkan")
    await state.clear()

# ================= AUTO POST =================
@dp.message(F.from_user.id==ADMIN_ID, (F.photo | F.video))
async def admin_media(m: Message, state:FSMContext):
    await state.update_data(
        file_id=m.photo[-1].file_id if m.photo else m.video.file_id,
        type="photo" if m.photo else "video"
    )
    await state.set_state(AutoPost.title)
    await m.answer("📝 Masukkan judul")

@dp.message(AutoPost.title, F.from_user.id==ADMIN_ID)
async def get_title(m: Message, state:FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AutoPost.cover)
    await m.answer("🖼 Kirim cover (photo)")

@dp.message(AutoPost.cover, F.from_user.id==ADMIN_ID, F.photo)
async def do_post(m: Message, state:FSMContext):
    d = await state.get_data()
    code = uuid.uuid4().hex[:8]

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO media VALUES (?,?,?,?)",
            (code, d["file_id"], d["type"], d["title"])
        )
        await db.commit()

    ch = await get_setting("post_channel")
    protect = (await get_setting("antifwd","0"))=="1"

    botname = (await bot.me()).username
    link = f"https://t.me/{botname}?start={code}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 NONTON", url=link)]
    ])

    await bot.send_photo(
        ch,
        m.photo[-1].file_id,
        caption=d["title"],
        reply_markup=kb,
        protect_content=protect
    )

    await m.answer("✅ Auto post berhasil")
    await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

asyncio.run(main())
