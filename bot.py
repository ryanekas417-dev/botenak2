import asyncio, os, uuid, datetime, re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
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

# ================= SECURITY PANEL =================
@dp.callback_query(F.data=="sec")
async def sec_panel(cb):
    status = await get_setting("filter_on","0")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(f"Filter Kata: {'ON' if status=='1' else 'OFF'}", callback_data="toggle_filter")],
        [InlineKeyboardButton("✏️ Edit Kata Terlarang", callback_data="edit_badword")],
        [InlineKeyboardButton("🛡 Exempt Username", callback_data="edit_exempt")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="admin_panel")]
    ])
    await cb.message.edit_text("🔐 SECURITY SETTINGS", reply_markup=kb)

@dp.callback_query(F.data=="toggle_filter")
async def toggle_filter(cb):
    cur = await get_setting("filter_on","0")
    await set_setting("filter_on","0" if cur=="1" else "1")
    await sec_panel(cb)

# ================= EXEMPT =================
@dp.callback_query(F.data=="edit_exempt")
async def ask_exempt(cb):
    await cb.message.edit_text("Kirim username exempt (tanpa @, pisahkan koma)")
    dp.message.register(save_exempt, F.text)

async def save_exempt(m: types.Message):
    await set_setting("exempt_users", m.text.lower())
    await m.answer("✅ Exempt disimpan")
    dp.message.handlers.clear()

# ================= FILTER UPDATE =================
@dp.callback_query(F.data=="edit_badword")
async def ask_badword(cb):
    await cb.message.edit_text("Kirim kata terlarang (pisahkan koma)")
    dp.message.register(save_badword, F.text)

async def save_badword(m: types.Message):
    await set_setting("bad_words", m.text.lower())
    await m.answer("✅ Kata terlarang diperbarui")
    dp.message.handlers.clear()

# ================= FORCE JOIN =================
@dp.callback_query(F.data=="fsub")
async def fsub_panel(cb):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("➕ Set Channel/Group", callback_data="set_fsub")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="admin_panel")]
    ])
    await cb.message.edit_text("📢 FORCE SUBSCRIBE", reply_markup=kb)

@dp.callback_query(F.data=="set_fsub")
async def ask_fsub(cb):
    await cb.message.edit_text("Kirim ID channel/grup WAJIB JOIN (pisahkan koma)")
    dp.message.register(save_fsub, F.text)

async def save_fsub(m: types.Message):
    await set_setting("fsub_ids", m.text)
    await m.answer("✅ Force join disimpan")
    dp.message.handlers.clear()

async def check_fsub(user_id):
    ids = (await get_setting("fsub_ids","")).split(",")
    for cid in ids:
        if not cid.strip(): continue
        try:
            member = await bot.get_chat_member(int(cid), user_id)
            if member.status not in ["member","administrator","creator"]:
                return False
        except:
            return False
    return True

# ================= FORCE JOIN GATE =================
@dp.message()
async def gate(m: types.Message):
    if m.chat.type != "private": return
    if await get_setting("fsub_ids"):
        if not await check_fsub(m.from_user.id):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("🔄 COBA LAGI", callback_data="retry_fsub")]
            ])
            await m.answer("🚫 Kamu belum join semua channel", reply_markup=kb)
            return

@dp.callback_query(F.data=="retry_fsub")
async def retry(cb):
    if await check_fsub(cb.from_user.id):
        await cb.message.edit_text("✅ Akses dibuka")
    else:
        await cb.answer("❌ Masih belum join", show_alert=True)

# ================= ASK ADMIN =================
@dp.message(Command("ask"))
async def ask_admin(m):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✉️ Kirim ke Admin", callback_data="send_ask")]
    ])
    await m.answer("Klik tombol untuk kirim pesan ke admin", reply_markup=kb)

@dp.callback_query(F.data=="send_ask")
async def send_ask(cb):
    await bot.send_message(
        ADMIN_IDS[0],
        f"❓ ASK\nID:{cb.from_user.id}\nNAME:{cb.from_user.full_name}\n@{cb.from_user.username}"
    )
    await cb.answer("Terkirim")

# ================= DONASI =================
@dp.message(Command("donasi"))
async def donasi(m):
    await m.answer("Kirim foto/video untuk donasi")
    dp.message.register(donasi_media, F.content_type.in_({"photo","video"}))

async def donasi_media(m):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ Approve", callback_data="approve_donasi"),
         InlineKeyboardButton("❌ Reject", callback_data="reject_donasi")]
    ])
    await bot.send_message(
        ADMIN_IDS[0],
        "📥 DONASI BARU",
        reply_markup=kb
    )
    await bot.copy_message(
        ADMIN_IDS[0],
        m.chat.id,
        m.message_id,
        protect_content=True
    )
    dp.message.handlers.clear()

@dp.callback_query(F.data.in_(["approve_donasi","reject_donasi"]))
async def handle_donasi(cb):
    await cb.message.edit_text(
        "✅ Donasi di-approve" if cb.data=="approve_donasi" else "❌ Donasi ditolak"
    )

# ================= LOG START =================
@dp.message(CommandStart())
async def log_start(m):
    await bot.send_message(
        ADMIN_IDS[0],
        f"🆕 START\nID:{m.from_user.id}\nNAME:{m.from_user.full_name}\n@{m.from_user.username}"
    )


