import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeChat, FSInputFile, 
    CallbackQuery, ChatMemberUpdated, ChatPermissions
)
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI AWAL =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "bot_cms.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= STATE MANAGEMENT =================
class AdminState(StatesGroup):
    waiting_for_db_ch = State()
    waiting_for_fsub = State()
    waiting_for_start_msg = State()
    waiting_for_broadcast = State()
    waiting_for_ask_reply = State()

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE SYSTEM =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Tabel Data Utama
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, title TEXT, backup_msg_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'active')")
        # Tabel Settings (Agar dinamis kayak di foto)
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        # Isi default settings
        default_settings = [
            ('db_channel', '0'),
            ('fsub_ids', ''), # Format: -100123,-100456
            ('start_text', '👋 Halo {name}! Selamat datang di bot.'),
            ('is_protected', 'OFF')
        ]
        for key, val in default_settings:
            await db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, val))
        await db.commit()

async def get_setting(key):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_setting(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
        await db.commit()

# ================= KEYBOARD GENERATORS =================
def get_admin_dashboard(is_protected):
    kb = [
        [InlineKeyboardButton(text="🆔 Set Multi-FSUB", callback_data="set_fsub"), 
         InlineKeyboardButton(text="🗄 Set DB Channel", callback_data="set_db_ch")],
        [InlineKeyboardButton(text="📝 Set Teks Start", callback_data="set_start_txt"),
         InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text=f"🛡 Proteksi: {is_protected}", callback_data="toggle_protect"),
         InlineKeyboardButton(text="📊 Statistik DB", callback_data="view_stats")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="close_admin")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= MIDDLEWARE / FILTERS =================
async def check_fsub(user_id):
    fsub_str = await get_setting('fsub_ids')
    if not fsub_str: return True, []
    
    ids = [i.strip() for i in fsub_str.split(",") if i.strip()]
    not_joined = []
    for ch_id in ids:
        try:
            member = await bot.get_chat_member(ch_id, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_joined.append(ch_id)
        except: continue
    return (len(not_joined) == 0), not_joined

# ================= HANDLERS ADMIN (DASHBOARD) =================

@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def open_dashboard(message: Message):
    protect = await get_setting('is_protected')
    await message.answer("🛠 **DASHBOARD SETTINGS**\nSilakan pilih menu di bawah:", reply_markup=get_admin_dashboard(protect))

@dp.callback_query(F.data == "set_db_ch", F.from_user.id == ADMIN_ID)
async def set_db_ch_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📥 Kirimkan **ID Channel Database** (Contoh: -100123456789):")
    await state.set_state(AdminState.waiting_for_db_ch)
    await c.answer()

@dp.message(AdminState.waiting_for_db_ch)
async def save_db_ch(m: Message, state: FSMContext):
    if m.text.replace("-", "").isdigit():
        await set_setting('db_channel', m.text)
        await m.reply(f"✅ DB Channel diatur ke: `{m.text}`")
        await state.clear()
    else:
        await m.reply("❌ ID tidak valid. Kirim angka ID Channel.")

@dp.callback_query(F.data == "toggle_protect", F.from_user.id == ADMIN_ID)
async def toggle_protect(c: CallbackQuery):
    current = await get_setting('is_protected')
    new_val = "ON" if current == "OFF" else "OFF"
    await set_setting('is_protected', new_val)
    await c.message.edit_reply_markup(reply_markup=get_admin_dashboard(new_val))
    await c.answer(f"Proteksi {new_val}")

# ================= SISTEM AUTO-POST (LEBIH CANGGIH) =================

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), F.from_user.id == ADMIN_ID)
async def start_upload(message: Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else message.document.file_id)
    ftype = "photo" if message.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=ftype)
    await state.set_state(PostMedia.waiting_for_title)
    await message.reply("📝 Masukkan **JUDUL** konten ini:")

@dp.message(PostMedia.waiting_for_title)
async def get_post_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER** untuk postingan di channel:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_cms_post(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    db_ch = await get_setting('db_channel')
    
    # 1. SIMPAN KE DB TELEGRAM DULU (BACKUP)
    try:
        backup = await bot.send_photo(
            chat_id=db_ch, 
            photo=data['temp_fid'] if data['temp_type']=="photo" else m.photo[-1].file_id,
            caption=f"#DB_{code}\nTitle: {data['title']}\nFid: `{data['temp_fid']}`"
        )
        backup_id = backup.message_id
    except:
        return await m.answer("❌ Gagal backup! Pastikan ID DB Channel benar dan Bot sudah jadi Admin di sana.")

    # 2. SIMPAN KE SQLITE
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['temp_fid'], data['temp_type'], data['title'], backup_id))
        await db.commit()
    
    # 3. AUTO POST KE CHANNEL (DENGAN TOMBOL)
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    kb_post = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 LIHAT KONTEN", url=link)]])
    
    # Kirim ke channel publik (FSub channel pertama biasanya)
    fsub_str = await get_setting('fsub_ids')
    if fsub_str:
        target_ch = fsub_str.split(",")[0]
        try:
            await bot.send_photo(target_ch, m.photo[-1].file_id, caption=f"🔥 **NEW UPDATE**\n\n📌 {data['title']}", reply_markup=kb_post)
        except: pass

    await m.answer(f"✅ **BERHASIL!**\n\nKode: `{code}`\nLink: `{link}`", parse_mode="HTML")
    await state.clear()

# ================= HANDLERS MEMBER (START & FSUB) =================

@dp.message(CommandStart())
async def start_handler(message: Message):
    uid = message.from_user.id
    # Simpan user ke DB
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        await db.commit()
        
    args = message.text.split()
    code = args[1] if len(args) > 1 else None
    
    # Cek Force Subscribe
    is_joined, missing_ids = await check_fsub(uid)
    if not is_joined:
        btns = []
        for i, ch_id in enumerate(missing_ids):
            try:
                chat_info = await bot.get_chat(ch_id)
                btns.append([InlineKeyboardButton(text=f"JOIN {chat_info.title}", url=f"https://t.me/{chat_info.username if chat_info.username else ''}")])
            except:
                btns.append([InlineKeyboardButton(text=f"Join Channel {i+1}", url="https://t.me/")])
        
        retry_link = f"https://t.me/{BOT_USERNAME}?start={code}" if code else f"https://t.me/{BOT_USERNAME}?start=welcome"
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", url=retry_link)])
        return await message.answer("⚠️ **AKSES DITOLAK**\n\nSilakan bergabung ke channel sponsor kami terlebih dahulu untuk menggunakan bot ini.", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    if not code:
        welcome_txt = await get_setting('start_text')
        # Tombol Donasi & Ask (Pesan Dede: Pake tombol jangan cmd)
        kb_member = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Kirim Konten (Donasi)", callback_data="member_donasi")],
            [InlineKeyboardButton(text="💬 Tanya Admin (Ask)", callback_data="member_ask")]
        ])
        return await message.answer(welcome_txt.format(name=message.from_user.first_name), reply_markup=kb_member)

    # Ambil konten dari DB
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, title FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    
    if row:
        if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=f"✅ **{row[2]}**")
        else: await bot.send_video(message.chat.id, row[0], caption=f"✅ **{row[2]}**")
    else:
        await message.answer("❌ Konten tidak ditemukan atau sudah dihapus.")

# ================= FITUR DONASI & ASK (VIA TOMBOL) =================

@dp.callback_query(F.data == "member_donasi")
async def member_donasi_btn(c: CallbackQuery):
    await c.message.answer("🙏 Terima kasih! Silakan **langsung kirim** foto/video yang ingin kamu donasikan ke sini.")
    await c.answer()

@dp.callback_query(F.data == "member_ask")
async def member_ask_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📝 Silakan tulis pesan/pertanyaan kamu untuk Admin:")
    await state.set_state(AdminState.waiting_for_ask_reply) # Pakai state yang sama untuk nangkep teks
    await c.answer()

@dp.message(AdminState.waiting_for_ask_reply)
async def handle_member_msg(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📩 **PESAN BARU (ASK)**\nDari: {m.from_user.full_name} (`{m.from_user.id}`)\n\nPesan: {m.text}")
    await m.reply("✅ Pesan kamu sudah terkirim ke Admin.")
    await state.clear()

# ================= STATS & BROADCAST =================

@dp.callback_query(F.data == "view_stats", F.from_user.id == ADMIN_ID)
async def view_stats(c: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    
    txt = f"📊 **STATISTIK BOT**\n\n👥 Total User: `{u[0]}`\n🎬 Total Media: `{m[0]}`\n🗄 DB Channel: `{await get_setting('db_channel')}`"
    await c.message.answer(txt)
    await c.answer()

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db_file(message: Message):
    if os.path.exists(DB_NAME):
        await message.reply_document(FSInputFile(DB_NAME), caption="📄 Backup SQLite Local")

# ================= BOOTING =================
async def main():
    await init_db()
    # Set Menu Command untuk Admin & Member (Pisah)
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="help", description="Bantuan")
    ])
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Mulai Bot"),
            BotCommand(command="settings", description="Dashboard CMS"),
            BotCommand(command="senddb", description="Backup DB")
        ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except: pass

    print("✅ Bot Berhasil Dijalankan!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
