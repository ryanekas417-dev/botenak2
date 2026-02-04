import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeChat, FSInputFile, 
    CallbackQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_cms.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class AdminState(StatesGroup):
    waiting_input = State()      # Untuk setting dashboard
    waiting_ask_reply = State()  # Untuk member tanya admin
    waiting_post_title = State() # Untuk judul postingan
    waiting_post_cover = State() # Untuk cover postingan

# ================= DATABASE ENGINE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, title TEXT, backup_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        # Default Settings
        defs = [('db_channel', '0'), ('fsub_ids', ''), ('addlist_url', ''), ('start_text', 'Halo {name}!'), ('is_protected', 'OFF')]
        for k, v in defs:
            await db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
        await db.commit()

async def set_setting(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
        await db.commit()

async def get_setting(key):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

# ================= UI ADMIN (DASHBOARD) =================
def admin_kb(prot):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆔 Multi-FSUB", callback_data="conf_fsub"), InlineKeyboardButton(text="🔗 Addlist", callback_data="conf_addlist")],
        [InlineKeyboardButton(text="📝 Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="🗄 DB Channel", callback_data="conf_db_ch")],
        [InlineKeyboardButton(text=f"🛡 Proteksi: {prot}", callback_data="conf_toggle_prot"), InlineKeyboardButton(text="📊 Stats", callback_data="conf_stats")],
        [InlineKeyboardButton(text="❌ Tutup", callback_data="conf_close")]
    ])

# ================= HANDLERS ADMIN =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def open_settings(m: Message):
    prot = await get_setting('is_protected') or "OFF"
    await m.answer("🛠 **DASHBOARD SETTINGS**", reply_markup=admin_kb(prot))

@dp.callback_query(F.data.startswith("conf_"), F.from_user.id == ADMIN_ID)
async def admin_callback(c: CallbackQuery, state: FSMContext):
    action = c.data.replace("conf_", "")
    if action == "close": return await c.message.delete()
    if action == "stats":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c1: u = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM media") as c2: m = (await c2.fetchone())[0]
        return await c.answer(f"User: {u} | Media: {m}", show_alert=True)
    
    if action == "toggle_prot":
        curr = await get_setting('is_protected')
        new_v = "ON" if curr == "OFF" else "OFF"
        await set_setting('is_protected', new_v)
        return await c.message.edit_reply_markup(reply_markup=admin_kb(new_v))

    # Input Settings
    targets = {"fsub": "fsub_ids", "addlist": "addlist_url", "start_txt": "start_text", "db_ch": "db_channel"}
    if action in targets:
        await state.update_data(target=targets[action], msg_id=c.message.message_id)
        await c.message.edit_text(f"📥 Silakan kirim data baru untuk **{action.upper()}**:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali", callback_data="conf_back")]]))
        await state.set_state(AdminState.waiting_input)
    
    if action == "back":
        await state.clear()
        prot = await get_setting('is_protected')
        await c.message.edit_text("🛠 **DASHBOARD SETTINGS**", reply_markup=admin_kb(prot))

@dp.message(AdminState.waiting_input, F.from_user.id == ADMIN_ID)
async def process_input(m: Message, state: FSMContext):
    data = await state.get_data()
    await set_setting(data['target'], m.text)
    await m.delete()
    prot = await get_setting('is_protected')
    try: await bot.edit_message_text("✅ Data diperbarui!\n🛠 **DASHBOARD SETTINGS**", m.chat.id, data['msg_id'], reply_markup=admin_kb(prot))
    except: await m.answer("✅ Data diperbarui! Ketik /settings lagi.")
    await state.clear()

# ================= AUTO POST SYSTEM (BACKUP -> DB -> POST) =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), F.from_user.id == ADMIN_ID)
async def admin_upload(m: Message, state: FSMContext):
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, ftype="photo" if m.photo else "video")
    await m.reply("📝 Masukkan **JUDUL** konten:")
    await state.set_state(AdminState.waiting_post_title)

@dp.message(AdminState.waiting_post_title)
async def post_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await m.reply("📸 Kirim **FOTO COVER** untuk Channel:")
    await state.set_state(AdminState.waiting_post_cover)

@dp.message(AdminState.waiting_post_cover, F.photo)
async def post_final(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    db_ch = await get_setting('db_channel')
    
    # 1. Backup ke Channel DB
    try:
        backup = await bot.send_photo(db_ch, data['fid'], caption=f"#DB_{code}\n{data['title']}")
        bid = backup.message_id
    except: return await m.reply("❌ Gagal backup! Cek ID DB Channel.")

    # 2. Simpan SQLite
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['ftype'], data['title'], bid))
        await db.commit()

    # 3. Post ke Channel Fsub Utama
    fsubs = await get_setting('fsub_ids')
    if fsubs:
        target = fsubs.split(",")[0].strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 LIHAT KONTEN", url=f"https://t.me/{BOT_USERNAME}?start={code}")]])
        try: await bot.send_photo(target, m.photo[-1].file_id, caption=f"🔥 **NEW UPDATE**\n\n📌 {data['title']}", reply_markup=kb)
        except: pass

    await m.answer(f"✅ Sukses!\nLink: `https://t.me/{BOT_USERNAME}?start={code}`")
    await state.clear()

# ================= MEMBER HANDLERS =================
@dp.message(CommandStart())
async def start(m: Message):
    uid = m.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        await db.commit()

    code = m.text.split()[1] if len(m.text.split()) > 1 else None
    
    # Check Fsub
    fsubs = await get_setting('fsub_ids')
    addlist = await get_setting('addlist_url')
    not_j = []
    if fsubs:
        for cid in fsubs.split(","):
            try:
                mem = await bot.get_chat_member(cid.strip(), uid)
                if mem.status not in ["member", "administrator", "creator"]: not_j.append(cid)
            except: continue

    if not_j:
        kb = [[InlineKeyboardButton(text="➕ Bergabung Sekarang", url=addlist)]] if addlist else [[InlineKeyboardButton(text="Join Channel", url="https://t.me/")]]
        kb.append([InlineKeyboardButton(text="🔄 Coba Lagi", url=f"https://t.me/{BOT_USERNAME}?start={code or ''}")])
        return await m.answer("Gabung ke channel kami dulu ya.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    if not code:
        txt = (await get_setting('start_text')).format(name=m.from_user.first_name)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 Kirim Konten", callback_data="m_donasi"), InlineKeyboardButton(text="💬 Tanya Admin", callback_data="m_ask")]])
        return await m.answer(txt, reply_markup=kb)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, title FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    if row:
        if row[1] == "photo": await bot.send_photo(m.chat.id, row[0], caption=f"✅ {row[2]}")
        else: await bot.send_video(m.chat.id, row[0], caption=f"✅ {row[2]}")

# Callback Donasi & Ask (FIXED)
@dp.callback_query(F.data == "m_donasi")
async def m_donasi(c: CallbackQuery):
    await c.message.answer("🙏 Silakan kirimkan Foto/Video donasi kamu ke sini.")
    await c.answer()

@dp.callback_query(F.data == "m_ask")
async def m_ask(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📝 Tulis pesan kamu untuk Admin:")
    await state.set_state(AdminState.waiting_ask_reply)
    await c.answer()

@dp.message(AdminState.waiting_ask_reply)
async def member_reply(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📩 **ASK**: {m.text}\nDari: {m.from_user.full_name} (`{m.from_user.id}`)")
    await m.reply("✅ Terkirim.")
    await state.clear()

async def main():
    await init_db()
    await bot.set_my_commands([BotCommand(command="start", description="Mulai Bot")])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
