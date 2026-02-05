import asyncio, os, uuid
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
DB = "media.db"

# ===== FSM =====
class AskState(StatesGroup):
    text = State()

class DonasiState(StatesGroup):
    media = State()

# ===== DB =====
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT, file_id TEXT, type TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

def is_admin(uid): return uid in ADMIN_IDS

# ===== START NORMAL =====
@dp.message(CommandStart())
async def start(m: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)",(m.from_user.id,))
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("💬 Ask Admin", callback_data="ask")],
        [InlineKeyboardButton("❤️ Donasi", callback_data="donasi")]
    ])
    if is_admin(m.from_user.id):
        kb.inline_keyboard.append([InlineKeyboardButton("⚙️ Admin", callback_data="admin")])

    await m.answer("👋 Selamat datang", reply_markup=kb)

# ===== START CODE =====
@dp.message(CommandStart(deep_link=True))
async def start_code(m: types.Message):
    code = m.text.split()[1]
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT file_id,type FROM media WHERE code=?",(code,))
        r = await cur.fetchone()

    if not r:
        await m.answer("❌ Konten tidak ditemukan")
        return

    fid,tp = r
    await getattr(bot,f"send_{tp}")(
        m.chat.id,
        fid,
        protect_content=True
    )

# ===== ASK ADMIN =====
@dp.callback_query(F.data=="ask")
async def ask(cb, state:FSMContext):
    await state.set_state(AskState.text)
    await cb.message.answer("Ketik pesan untuk admin")

@dp.message(AskState.text)
async def send_ask(m, state:FSMContext):
    await bot.send_message(
        ADMIN_IDS[0],
        f"❓ ASK\nID:{m.from_user.id}\n{m.text}"
    )
    await m.answer("✅ Terkirim")
    await state.clear()

# ===== DONASI =====
@dp.callback_query(F.data=="donasi")
async def donasi(cb, state:FSMContext):
    await state.set_state(DonasiState.media)
    await cb.message.answer("Kirim foto / video donasi")

@dp.message(DonasiState.media, F.content_type.in_({"photo","video"}))
async def donasi_media(m, state:FSMContext):
    await bot.copy_message(
        ADMIN_IDS[0],
        m.chat.id,
        m.message_id,
        protect_content=True
    )
    await m.answer("🙏 Donasi terkirim")
    await state.clear()

# ===== ADMIN AUTO SAVE =====
@dp.message(F.content_type.in_({"photo","video"}))
async def admin_media(m: types.Message):
    if not is_admin(m.from_user.id): return
    fid = m.photo[-1].file_id if m.photo else m.video.file_id
    code = uuid.uuid4().hex[:20]

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO media VALUES (?,?,?)",
            (code,fid,m.content_type)
        )
        await db.commit()

    link = f"https://t.me/{(await bot.get_me()).username}?start={code}"
    await m.answer(f"✅ DISIMPAN\n{link}")

# ===== RUN =====
async def main():
    await init_db()
    await dp.start_polling(bot)

asyncio.run(main())
