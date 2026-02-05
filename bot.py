import asyncio, os, uuid, aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    FSInputFile, CallbackQuery, ChatMemberUpdated
)
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI RAILWAY =================
# Hanya Token dan Admin ID yang dari ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0

# Inisialisasi Bot
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_fsub_1 = State()
    waiting_for_fsub_2 = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State() # Untuk reply pesan user

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE MANAGER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Tabel Media (File)
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        # Tabel Users (Untuk Broadcast)
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        # Tabel Config (Pengaturan Admin)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY, 
                value TEXT
            )
        """)
        await db.commit()

async def get_config(key, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def set_config(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ================= LOG & HELPERS =================
async def send_log(text):
    # Log dikirim ke Admin ID (bisa diubah jika punya channel log khusus di setting)
    try:
        await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
    except:
        pass

async def check_membership(user_id: int):
    # Ambil settingan FSub dari DB
    ch1_data = await get_config("fsub_1") # Format: @username|link
    ch2_data = await get_config("fsub_2") # Format: @username|link
    
    targets = []
    links = []
    
    for data in [ch1_data, ch2_data]:
        if data:
            parts = data.split("|")
            username = parts[0].strip()
            link = parts[1].strip() if len(parts) > 1 else f"https://t.me/{username.replace('@','')}"
            targets.append(username)
            links.append(link)
        else:
            targets.append(None)
            links.append(None)

    status_list = []
    final_links = []

    for i, target in enumerate(targets):
        if not target:
            status_list.append(True) # Skip jika tidak diset
            final_links.append(None)
            continue
            
        try:
            m = await bot.get_chat_member(target, user_id)
            is_member = m.status in ("member", "administrator", "creator")
            status_list.append(is_member)
            final_links.append(links[i])
        except Exception as e:
            # Jika bot bukan admin di channel fsub atau error lain
            print(f"Error check membership {target}: {e}")
            status_list.append(True) # Anggap sudah join biar ga error
            final_links.append(links[i])

    return all(status_list), final_links

# ================= HANDLERS ADMIN PANEL (UI) =================
@dp.message(Command("panel"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Set Channel Post", callback_data="set_post")],
        [InlineKeyboardButton(text="🔗 Set FSub 1", callback_data="set_fsub1"),
         InlineKeyboardButton(text="🔗 Set FSub 2", callback_data="set_fsub2")],
        [InlineKeyboardButton(text="📡 Broadcast", callback_data="menu_broadcast"),
         InlineKeyboardButton(text="💾 Backup DB", callback_data="menu_db")],
        [InlineKeyboardButton(text="❌ Tutup", callback_data="close_panel")]
    ])
    await message.reply("🛠 **PANEL ADMIN**\nSilahkan pilih pengaturan:", reply_markup=kb)

@dp.callback_query(F.data == "close_panel", F.from_user.id == ADMIN_ID)
async def close_panel(c: CallbackQuery):
    await c.message.delete()

# --- HANDLER SETTINGS ---
@dp.callback_query(F.data == "set_post", F.from_user.id == ADMIN_ID)
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("kirim **Username Channel** untuk Auto-Post (contoh: `@channelku`).")
    await state.set_state(AdminStates.waiting_for_channel_post)
    await c.answer()

@dp.message(AdminStates.waiting_for_channel_post)
async def process_set_post(m: Message, state: FSMContext):
    await set_config("channel_post", m.text.strip())
    await m.reply(f"✅ Channel Auto-Post diatur ke: {m.text}")
    await state.clear()

@dp.callback_query(F.data.in_({"set_fsub1", "set_fsub2"}), F.from_user.id == ADMIN_ID)
async def set_fsub_cb(c: CallbackQuery, state: FSMContext):
    target = "1" if "fsub1" in c.data else "2"
    await state.update_data(target_fsub=target)
    await c.message.answer(
        f"Kirim **Username Channel** dan **Link Join** dipisah tanda pipa `|`.\n\n"
        f"Contoh: `@channelku | https://t.me/+AbCdEfGhIjK`\n"
        f"Atau kirim `DELETE` untuk menghapus.", parse_mode="Markdown"
    )
    if target == "1":
        await state.set_state(AdminStates.waiting_for_fsub_1)
    else:
        await state.set_state(AdminStates.waiting_for_fsub_2)
    await c.answer()

@dp.message(AdminStates.waiting_for_fsub_1)
async def process_fsub_1(m: Message, state: FSMContext):
    if m.text.upper() == "DELETE":
        await set_config("fsub_1", "")
        await m.reply("✅ FSub 1 dihapus.")
    else:
        if "|" not in m.text:
            await m.reply("⚠️ Format salah. Gunakan: `@username | link`")
            return
        await set_config("fsub_1", m.text.strip())
        await m.reply(f"✅ FSub 1 disimpan.")
    await state.clear()

@dp.message(AdminStates.waiting_for_fsub_2)
async def process_fsub_2(m: Message, state: FSMContext):
    if m.text.upper() == "DELETE":
        await set_config("fsub_2", "")
        await m.reply("✅ FSub 2 dihapus.")
    else:
        if "|" not in m.text:
            await m.reply("⚠️ Format salah. Gunakan: `@username | link`")
            return
        await set_config("fsub_2", m.text.strip())
        await m.reply(f"✅ FSub 2 disimpan.")
    await state.clear()

# --- BROADCAST & DB ---
@dp.callback_query(F.data == "menu_db", F.from_user.id == ADMIN_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME):
        await c.message.reply_document(FSInputFile(DB_NAME), caption="📦 Backup Database")
    else:
        await c.message.reply("⚠️ Database belum dibuat.")
    await c.answer()

@dp.callback_query(F.data == "menu_broadcast", F.from_user.id == ADMIN_ID)
async def broadcast_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📢 Kirim pesan yang akan dibroadcast (Text/Foto/Video):")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await c.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(m: Message, state: FSMContext):
    await m.reply("⏳ Memulai broadcast...")
    success = 0
    blocked = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            for row in users:
                uid = row[0]
                try:
                    await m.copy_to(uid)
                    success += 1
                    await asyncio.sleep(0.05) # Anti flood
                except:
                    blocked += 1
    await m.reply(f"✅ **Broadcast Selesai**\nSukses: {success}\nGagal: {blocked}")
    await state.clear()

# ================= HANDLERS REPLY (ADMIN MEMBALAS) =================
@dp.callback_query(F.data.startswith("reply:"))
async def reply_button_cb(c: CallbackQuery, state: FSMContext):
    user_id = c.data.split(":")[1]
    await state.update_data(reply_to_user=user_id)
    await state.set_state(AdminStates.waiting_for_reply)
    await c.message.answer(f"✍️ Tulis balasan untuk ID `{user_id}`:", parse_mode="Markdown")
    await c.answer()

@dp.message(AdminStates.waiting_for_reply)
async def process_admin_reply(m: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get('reply_to_user')
    try:
        await bot.send_message(target_id, f"📩 **Balasan Admin:**\n\n{m.text}")
        await m.reply("✅ Pesan terkirim.")
    except Exception as e:
        await m.reply(f"❌ Gagal mengirim: {e}")
    await state.clear()

# ================= HANDLERS MEDIA & DONASI =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def handle_media(message: Message, state: FSMContext):
    # Jika Admin yang kirim -> Mode Upload
    if message.from_user.id == ADMIN_ID:
        fid = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else message.document.file_id)
        mtype = "photo" if message.photo else "video"
        await state.update_data(temp_fid=fid, temp_type=mtype)
        await state.set_state(PostMedia.waiting_for_title)
        await message.reply("📝 **MODE POSTING**\nMasukkan **JUDUL** konten:")
        return

    # Jika Member yang kirim -> Mode Donasi
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ POST", callback_data=f"app_donasi"),
        InlineKeyboardButton(text="❌ REJECT", callback_data="reject"),
        InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{message.from_user.id}")
    ]])
    
    await bot.send_message(ADMIN_ID, f"🎁 **DONASI MASUK**\nDari: {message.from_user.full_name} (ID: `{message.from_user.id}`)", reply_markup=kb, parse_mode="Markdown")
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await message.reply("✅ Konten donasi terkirim ke admin.")

@dp.callback_query(F.data == "reject")
async def reject_cb(c: CallbackQuery):
    await c.message.delete()
    await c.answer("Ditolak.")

@dp.callback_query(F.data == "app_donasi")
async def approve_cb(c: CallbackQuery, state: FSMContext):
    await state.set_state(PostMedia.waiting_for_title)
    await c.message.answer("📝 Admin, masukkan **JUDUL** postingan:")
    await c.answer()

@dp.message(PostMedia.waiting_for_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER** untuk postingan di Channel:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_and_post_ch(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    
    # Ambil file asli dari state (bisa dari donasi user atau upload admin)
    final_fid = data.get('temp_fid', m.photo[-1].file_id) 
    final_type = data.get('temp_type', "photo")
    title = data['title']
    
    # Simpan ke DB
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, final_fid, final_type, title))
        await db.commit()
    
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"
    
    # Ambil Channel Target dari DB
    ch_target = await get_config("channel_post")
    
    post_status = "⚠️ Channel Post belum diset di /panel"
    if ch_target:
        caption_ch = f"🔥 **{title}**\n\n👇 **KLIK TOMBOL DIBAWAH** 👇"
        kb_ch = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
        try:
            await bot.send_photo(ch_target, m.photo[-1].file_id, caption=caption_ch, reply_markup=kb_ch, parse_mode="Markdown")
            post_status = f"✅ Berhasil di-post ke {ch_target}"
        except Exception as e:
            post_status = f"❌ Gagal post ke CH: {str(e)}"
    
    await m.answer(f"✅ **SELESAI**\n\n{post_status}\nLink: `{link}`", parse_mode="Markdown")
    await state.clear()

# ================= HANDLER MEMBER: ASK & START =================
@dp.message(Command("ask"))
async def ask_handler(message: Message):
    cmd = message.text.split(maxsplit=1)
    if len(cmd) < 2:
        return await message.reply("⚠️ Format: `/ask pesan`")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ REPLY USER", callback_data=f"reply:{message.from_user.id}")
    ]])
    
    await bot.send_message(
        ADMIN_ID, 
        f"📩 **ASK MASUK**\nDari: {message.from_user.full_name} (ID: `{message.from_user.id}`)\n\nPesan:\n{cmd[1]}", 
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await message.reply("✅ Pesan terkirim ke admin.")

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    # Simpan user ke DB untuk broadcast
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    
    # Jika tidak ada kode (cuma /start biasa)
    if len(args) == 1:
        return await message.answer(f"👋 Halo {message.from_user.first_name}! Gunakan bot ini untuk mengakses konten eksklusif.")

    code = args[1]
    
    # --- LOGIKA FSUB ---
    is_joined, links = await check_membership(message.from_user.id)
    
    if not is_joined:
        btns = []
        for i, link in enumerate(links):
            if link: # Jika link ada (channel diset)
                btns.append([InlineKeyboardButton(text=f"JOIN CHANNEL {i+1}", url=link)])
        
        # Tombol Coba Lagi
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", url=f"https://t.me/{(await bot.get_me()).username}?start={code}")])
        
        return await message.answer(
            "🚫 **AKSES DITOLAK**\n\nKamu belum bergabung ke channel kami. Silahkan join tombol di bawah lalu klik **COBA LAGI**.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
            parse_mode="Markdown"
        )

    # --- JIKA SUDAH JOIN / KODE VALID ---
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
            if row:
                caption = row[2] or ""
                if row[1] == "photo":
                    await bot.send_photo(message.chat.id, row[0], caption=caption)
                else:
                    await bot.send_video(message.chat.id, row[0], caption=caption)
            else:
                await message.answer("❌ Media tidak ditemukan.")

# ================= BOOTING =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot Berjalan...")
    print(f"Admin ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot Stopped")
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

# ================= MEMBER BUTTON =================
@dp.callback_query(F.data=="ask")
async def ask_btn(cb: CallbackQuery):
    await cb.message.answer("💬 Kirim pesan kamu, admin akan menerima")
    await cb.answer()

@dp.callback_query(F.data=="donasi")
async def donasi_btn(cb: CallbackQuery):
    await cb.message.answer("🎁 Kirim media / pesan donasi kamu")
    await cb.answer()

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
    await m.answer("✅ Channel disimpan")
    await state.clear()

# ================= AUTO POST (FIX FSM) =================
@dp.message(
    F.from_user.id==ADMIN_ID,
    (F.photo | F.video),
    StateFilter(None)
)
async def admin_media_start(m: Message, state:FSMContext):
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

