import asyncio
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
# Pastikan Variable BOT_TOKEN dan ADMIN_ID sudah ada di Railway Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Jika ADMIN_ID error/kosong, set ke 0 agar bot tetap jalan (tapi fitur admin mati)
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    ADMIN_ID = 0

# ================= INISIALISASI BOT =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= STATES (STATUS) =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_fsub_1 = State()
    waiting_for_fsub_2 = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE MANAGER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
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

# ================= HELPERS (ALAT BANTU) =================
async def check_membership(user_id: int):
    ch1_data = await get_config("fsub_1") 
    ch2_data = await get_config("fsub_2") 
    
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
            status_list.append(True)
            final_links.append(None)
            continue
            
        try:
            m = await bot.get_chat_member(target, user_id)
            is_member = m.status in ("member", "administrator", "creator")
            status_list.append(is_member)
            final_links.append(links[i])
        except Exception as e:
            # Jika bot bukan admin atau error, anggap user sudah join biar ga stuck
            print(f"Error check membership {target}: {e}")
            status_list.append(True) 
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
                    await asyncio.sleep(0.05)
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
    
    final_fid = data.get('temp_fid', m.photo[-1].file_id) 
    final_type = data.get('temp_type', "photo")
    title = data['title']
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, final_fid, final_type, title))
        await db.commit()
    
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"
    
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    
    if len(args) == 1:
        return await message.answer(f"👋 Halo {message.from_user.first_name}! Gunakan bot ini untuk mengakses konten eksklusif.")

    code = args[1]
    
    is_joined, links = await check_membership(message.from_user.id)
    bot_info = await bot.get_me()

    if not is_joined:
        btns = []
        for i, link in enumerate(links):
            if link: 
                btns.append([InlineKeyboardButton(text=f"JOIN CHANNEL {i+1}", url=link)])
        
        # Tombol Coba Lagi yang dinamis
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", url=f"https://t.me/{bot_info.username}?start={code}")])
        
        return await message.answer(
            "🚫 **AKSES DITOLAK**\n\nKamu belum bergabung ke channel kami. Silahkan join tombol di bawah lalu klik **COBA LAGI**.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
            parse_mode="Markdown"
        )

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
    # Hapus webhook agar tidak konflik saat polling
    await bot.delete_webhook(drop_pending_updates=True)
    print(f"Bot Berjalan dengan Admin ID: {ADMIN_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot Berhenti")
