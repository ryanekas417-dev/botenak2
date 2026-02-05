import asyncio, os, uuid, datetime, re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
DB = "media.db"

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def set_setting(k,v):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(k,v))
        await db.commit()

async def get_setting(k, default=None):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?",(k,))
        r = await cur.fetchone()
        return r[0] if r else default

def is_admin(uid): return uid in ADMIN_IDS

# ================= START =================
@dp.message(CommandStart())
async def start(m: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)",(m.from_user.id,))
        await db.commit()

    text = await get_setting("start_text","👋 Selamat datang")
    kb = None
    if is_admin(m.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("⚙️ PANEL ADMIN", callback_data="admin_panel")]
        ])
    await m.answer(text, reply_markup=kb)

# ================= PANEL =================
@dp.callback_query(F.data=="admin_panel")
async def panel(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔐 Security", callback_data="sec")],
        [InlineKeyboardButton("📢 Force Join", callback_data="fsub")],
        [InlineKeyboardButton("📝 Start Text", callback_data="starttxt")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("💾 Backup DB", callback_data="backup")]
    ])
    await cb.message.edit_text("⚙️ ADMIN DASHBOARD", reply_markup=kb)

# ================= FILTER =================
@dp.message(F.chat.type.in_(["group","supergroup"]))
async def filter_words(m: types.Message):
    if is_admin(m.from_user.id): return
    if await get_setting("filter_on","0")!="1": return

    bad = (await get_setting("bad_words","")).split(",")
    txt = (m.text or "").lower()
    if any(w and w in txt for w in bad):
        await m.delete()
        until = datetime.datetime.now()+datetime.timedelta(hours=24)
        await bot.restrict_chat_member(
            m.chat.id, m.from_user.id,
            types.ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await m.answer(f"⚠️ <a href='tg://user?id={m.from_user.id}'>Filter aktif</a>")

# ================= SENDDB =================
@dp.message(F.content_type.in_({"photo","video","document","animation"}))
async def senddb(m: types.Message):
    if not is_admin(m.from_user.id): return
    file = m.photo[-1].file_id if m.photo else m.video.file_id if m.video else m.document.file_id
    code = uuid.uuid4().hex[:30]
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)",(code,file,m.content_type,m.caption or ""))
        await db.commit()
    await m.answer(f"✅ MEDIA DISIMPAN\nCODE: <code>{code}</code>")

# ================= STATS =================
@dp.callback_query(F.data=="stats")
async def stats(cb):
    async with aiosqlite.connect(DB) as db:
        u = await db.execute("SELECT COUNT(*) FROM users")
        m = await db.execute("SELECT COUNT(*) FROM media")
        users = (await u.fetchone())[0]
        media = (await m.fetchone())[0]
    await cb.message.edit_text(f"📊 USERS: {users}\n📁 MEDIA: {media}")

# ================= BACKUP =================
@dp.callback_query(F.data=="backup")
async def backup(cb):
    await cb.message.answer_document(types.FSInputFile(DB))

# ================= RUN =================
async def main():
    await init_db()
    await dp.start_polling(bot)

asyncio.run(main())
