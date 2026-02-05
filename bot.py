import asyncio, os, uuid, datetime, re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
DB = "media.db"

# ================= FSM =================
class AdminState(StatesGroup):
    badword = State()
    exempt = State()
    fsub = State()
    post_channel = State()
    ask = State()
    donasi = State()
    title = State()
    cover = State()

# ================= DB =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("""CREATE TABLE IF NOT EXISTS media (
            code TEXT,
            file_id TEXT,
            type TEXT,
            caption TEXT
        )""")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def set_setting(k,v):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(k,v))
        await db.commit()

async def get_setting(k, d=None):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute("SELECT value FROM settings WHERE key=?",(k,))
        r = await c.fetchone()
        return r[0] if r else d

def is_admin(uid): return uid in ADMIN_IDS

# ================= START =================
@dp.message(CommandStart())
async def start(m: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)",(m.from_user.id,))
        await db.commit()

    if m.text and len(m.text.split()) == 2:
        code = m.text.split()[1]
        async with aiosqlite.connect(DB) as db:
            c = await db.execute("SELECT file_id,type,caption FROM media WHERE code=?",(code,))
            r = await c.fetchone()
            if r:
                fid, tp, cap = r
                await getattr(bot, f"send_{tp}")(
                    m.chat.id,
                    fid,
                    caption=cap,
                    protect_content=True
                )
                return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("💬 Ask Admin", callback_data="ask")],
        [InlineKeyboardButton("❤️ Donasi", callback_data="donasi")]
    ])
    if is_admin(m.from_user.id):
        kb.inline_keyboard.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="admin")])
    await m.answer("👋 Selamat datang", reply_markup=kb)

# ================= ADMIN PANEL =================
@dp.callback_query(F.data=="admin")
async def admin_panel(cb):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔐 Security", callback_data="sec")],
        [InlineKeyboardButton("📢 Force Join", callback_data="fsub")],
        [InlineKeyboardButton("📺 Set Post Channel", callback_data="setpost")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("💾 Backup DB", callback_data="backup")]
    ])
    await cb.message.edit_text("⚙️ ADMIN PANEL", reply_markup=kb)

# ================= AUTO POST =================
@dp.message(F.content_type.in_({"photo","video"}))
async def autopost(m: types.Message, state: FSMContext):
    fid = m.photo[-1].file_id if m.photo else m.video.file_id
    code = uuid.uuid4().hex[:30]

    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)",(code,fid,m.content_type,m.caption or ""))
        await db.commit()

    link = f"https://t.me/{(await bot.get_me()).username}?start={code}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ POST", callback_data=f"post:{code}")],
        [InlineKeyboardButton("❌ REJECT", callback_data="reject")]
    ])

    await bot.copy_message(
        ADMIN_IDS[0],
        m.chat.id,
        m.message_id,
        caption=f"LINK SIAP:\n{link}",
        reply_markup=kb,
        protect_content=True
    )

@dp.callback_query(F.data.startswith("post:"))
async def ask_title(cb, state: FSMContext):
    await state.update_data(code=cb.data.split(":")[1])
    await state.set_state(AdminState.title)
    await cb.message.answer("Kirim judul")

@dp.message(AdminState.title)
async def ask_cover(m, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AdminState.cover)
    await m.answer("Kirim cover")

@dp.message(AdminState.cover, F.photo)
async def do_post(m, state: FSMContext):
    data = await state.get_data()
    ch = int(await get_setting("post_channel"))
    code = data["code"]
    title = data["title"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🎬 NONTON", url=f"https://t.me/{(await bot.get_me()).username}?start={code}")]
    ])
    await bot.send_photo(
        ch,
        m.photo[-1].file_id,
        caption=f"<b>{title}</b>",
        reply_markup=kb
    )
    await m.answer("✅ Posted")
    await state.clear()

# ================= FORCE JOIN =================
@dp.callback_query(F.data=="fsub")
async def fsub(cb, state:FSMContext):
    await state.set_state(AdminState.fsub)
    await cb.message.edit_text("Kirim link channel/grup (pisah baris)")

@dp.message(AdminState.fsub)
async def save_fsub(m, state:FSMContext):
    links = m.text.splitlines()
    ids=[]
    for l in links:
        try:
            chat = await bot.get_chat(l)
            ids.append(str(chat.id))
        except: pass
    await set_setting("fsub_ids",",".join(ids))
    await m.answer("✅ FSUB disimpan")
    await state.clear()

# ================= STATS =================
@dp.callback_query(F.data=="stats")
async def stats(cb):
    async with aiosqlite.connect(DB) as db:
        u=(await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        m=(await (await db.execute("SELECT COUNT(*) FROM media")).fetchone())[0]
    await cb.message.edit_text(f"👤 Users: {u}\n📁 Media: {m}")

# ================= BACKUP =================
@dp.callback_query(F.data=="backup")
async def backup(cb):
    await cb.message.answer_document(types.FSInputFile(DB))

# ================= RUN =================
async def main():
    await init_db()
    await dp.start_polling(bot)

asyncio.run(main())
