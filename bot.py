import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    FSInputFile, CallbackQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID")) # ID Utama dari Railway tetap jadi Owner
except (TypeError, ValueError):
    OWNER_ID = 0

# ================= INISIALISASI =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_fsub_list = State()
    waiting_for_addlist = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()
    waiting_for_new_admin = State()

class MemberStates(StatesGroup):
    waiting_for_ask = State()
    waiting_for_donation = State()

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER PRIMARY KEY)") # Tabel Admin Baru
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

async def is_admin(user_id: int):
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

# ================= HELPERS (FSUB CHECK) =================
async def check_membership(user_id: int):
    raw_targets = await get_config("fsub_channels")
    if not raw_targets: return True
    targets = raw_targets.split()
    not_joined_count = 0
    for target in targets:
        try:
            chat = await bot.get_chat(target)
            m = await bot.get_chat_member(chat.id, user_id)
            if m.status not in ("member", "administrator", "creator"):
                not_joined_count += 1
        except: pass
    return not_joined_count == 0

# ================= HANDLERS ADMIN PANEL =================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id): return

    buttons = [
        [InlineKeyboardButton(text="📢 Set Auto-Post Channel", callback_data="set_post")],
        [InlineKeyboardButton(text="📋 Set List Channel Wajib", callback_data="set_fsub_list")],
        [InlineKeyboardButton(text="🔗 Set Link Addlist", callback_data="set_addlist")]
    ]
    
    # Fitur khusus OWNER (Broad/DB/Add Admin)
    if message.from_user.id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="📡 Broadcast", callback_data="menu_broadcast"),
                        InlineKeyboardButton(text="💾 Backup DB", callback_data="menu_db")])
        buttons.append([InlineKeyboardButton(text="👤 Tambah Admin", callback_data="add_admin")])
    
    buttons.append([InlineKeyboardButton(text="❌ Tutup", callback_data="close_panel")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("🛠 **PANEL KONTROL**", reply_markup=kb)

@dp.callback_query(F.data == "add_admin", F.from_user.id == OWNER_ID)
async def add_admin_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim **User ID** admin baru (bisa cek di @userinfobot):")
    await state.set_state(AdminStates.waiting_for_new_admin)
    await c.answer()

@dp.message(AdminStates.waiting_for_new_admin, F.from_user.id == OWNER_ID)
async def process_new_admin(m: Message, state: FSMContext):
    try:
        new_id = int(m.text.strip())
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (new_id,))
            await db.commit()
        await m.reply(f"✅ ID `{new_id}` berhasil diangkat jadi Admin.")
    except:
        await m.reply("❌ Masukkan ID berupa angka!")
    await state.clear()

@dp.callback_query(F.data == "close_panel")
async def close_panel(c: CallbackQuery):
    if await is_admin(c.from_user.id):
        await c.message.delete()

@dp.callback_query(F.data == "set_post")
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    if not await is_admin(c.from_user.id): return
    await c.message.answer("Kirim **Username Channel** untuk Auto-Post:")
    await state.set_state(AdminStates.waiting_for_channel_post)
    await c.answer()

@dp.message(AdminStates.waiting_for_channel_post)
async def process_set_post(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    await set_config("channel_post", m.text.strip())
    await m.reply(f"✅ Auto-Post set ke: {m.text}")
    await state.clear()

@dp.callback_query(F.data == "set_fsub_list")
async def set_fsub_list_cb(c: CallbackQuery, state: FSMContext):
    if not await is_admin(c.from_user.id): return
    await c.message.answer("Kirim **List Username** (@ch1 @ch2):")
    await state.set_state(AdminStates.waiting_for_fsub_list)
    await c.answer()

@dp.message(AdminStates.waiting_for_fsub_list)
async def process_fsub_list(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    await set_config("fsub_channels", m.text.strip())
    await m.reply(f"✅ List Channel Wajib disimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_addlist")
async def set_addlist_cb(c: CallbackQuery, state: FSMContext):
    if not await is_admin(c.from_user.id): return
    await c.message.answer("Kirim **Link Addlist / Folder**:")
    await state.set_state(AdminStates.waiting_for_addlist)
    await c.answer()

@dp.message(AdminStates.waiting_for_addlist)
async def process_addlist(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    await set_config("addlist_link", m.text.strip())
    await m.reply(f"✅ Link tombol Join diset.")
    await state.clear()

@dp.callback_query(F.data == "menu_db", F.from_user.id == OWNER_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME):
        await c.message.reply_document(FSInputFile(DB_NAME), caption="📦 Backup Database")
    await c.answer()

@dp.callback_query(F.data == "menu_broadcast", F.from_user.id == OWNER_ID)
async def broadcast_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📢 Kirim pesan broadcast:")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await c.answer()

@dp.message(AdminStates.waiting_for_broadcast, F.from_user.id == OWNER_ID)
async def process_broadcast(m: Message, state: FSMContext):
    await m.reply("⏳ Sending...")
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            async for row in cursor:
                try:
                    await m.copy_to(row[0])
                    count += 1
                    await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Terkirim ke {count} user.")
    await state.clear()


# ================= ADMIN DASHBOARD (DENGAN TOMBOL HAPUS) =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def admin_settings(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Start Teks", callback_data="set_start_txt"), InlineKeyboardButton(text="📢 Fsub Teks", callback_data="set_fsub_txt")],
        [InlineKeyboardButton(text="🔗 Set Addlist/Link", callback_data="set_fsub_link"), InlineKeyboardButton(text="🗑️ HAPUS LINK", callback_data="del_fsub_link")],
        [InlineKeyboardButton(text="👥 Set USN Fsub", callback_data="set_fsub_list"), InlineKeyboardButton(text="🗑️ HAPUS USN", callback_data="del_fsub_list")],
        [InlineKeyboardButton(text="📣 Set CH Post", callback_data="set_post_ch_id"), InlineKeyboardButton(text="🗑️ HAPUS CH POST", callback_data="del_post_ch_id")],
        [InlineKeyboardButton(text="📁 CH Database", callback_data="set_db_ch_id"), InlineKeyboardButton(text="📜 Log Channel", callback_data="set_log_id")],
        [InlineKeyboardButton(text="🛡️ Exempt", callback_data="set_exempt_usn"), InlineKeyboardButton(text="❌ TUTUP", callback_data="adm_exit")]
    ])
    await m.answer("⚙️ **ADMIN PANEL**\nKlik tombol kiri untuk **Ubah**, tombol kanan untuk **Hapus/Kosongkan**.", reply_markup=kb)

# ================= HANDLER HAPUS DATA (RESET KE KOSONG) =================
@dp.callback_query(F.data.startswith("del_"))
async def config_delete(c: CallbackQuery):
    field = c.data.replace("del_", "")
    
    async with aiosqlite.connect("master.db") as db:
        # Kita set nilainya jadi string kosong ('')
        await db.execute(f"UPDATE settings SET {field}='' WHERE id=1")
        await db.commit()
    
    await c.answer(f"✅ Berhasil menghapus {field}!", show_alert=True)
    # Refresh menu settings setelah dihapus
    await admin_settings(c.message) 
    await c.message.delete()
    
# ================= UPDATE DATABASE HANDLER =================
@dp.message(Command("update"))
async def update_database(m: Message):
    # Cek apakah dia OWNER atau Admin
    if not await is_admin(m.from_user.id): return

    # Cek apakah dia reply sebuah file
    if not m.reply_to_message or not m.reply_to_message.document:
        return await m.reply("❌ **Caranya:** Reply file database (.db), lalu ketik `/update`")

    doc = m.reply_to_message.document
    
    # Validasi biar nggak asal upload file
    if not doc.file_name.endswith(".db"):
        return await m.reply("❌ File harus berakhiran `.db`, su!")

    try:
        # Proses download dan menimpa file lama
        file_info = await bot.get_file(doc.file_id)
        
        # Sesuai variabel DB_NAME di kodingan lu
        await bot.download_file(file_info.file_path, DB_NAME)
        
        await m.reply("✅ **DATABASE UPDATED!**\nMedia.db berhasil diperbarui. Silakan cek `/panel` atau tes link lama.")
    except Exception as e:
        await m.reply(f"❌ Gagal update database: {e}")
        

# ================= MENU MEMBER (ASK & DONASI) =================
@dp.callback_query(F.data == "menu_ask")
async def member_ask_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📩 **TANYA ADMIN**\nSilahkan tulis pesanmu sekarang:")
    await state.set_state(MemberStates.waiting_for_ask)
    await c.answer()

@dp.message(MemberStates.waiting_for_ask)
async def process_member_ask(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")
    ]])
    # Notif dikirim ke OWNER (bisa diubah agar semua admin dapet notif)
    await bot.send_message(OWNER_ID, f"📩 **PESAN BARU**\nDari: {m.from_user.full_name}\nID: `{m.from_user.id}`\n\nIsi: {m.text}", reply_markup=kb)
    await m.reply("✅ Pesan terkirim ke admin.")
    await state.clear()

@dp.callback_query(F.data == "menu_donate")
async def member_donate_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🎁 **DONASI KONTEN**\nSilahkan kirim Foto/Video kamu sekarang:")
    await state.set_state(MemberStates.waiting_for_donation)
    await c.answer()

# ================= MEDIA HANDLING (ADMIN & MEMBER) =================
@dp.message(MemberStates.waiting_for_donation, (F.photo | F.video | F.document))
async def process_member_donation(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ ACC & POST", callback_data="app_donasi"),
        InlineKeyboardButton(text="❌ TOLAK", callback_data="reject"),
        InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")
    ]])
    await bot.send_message(OWNER_ID, f"🎁 **DONASI MASUK**\nDari: {m.from_user.full_name}", reply_markup=kb)
    await bot.forward_message(OWNER_ID, m.chat.id, m.message_id)
    await m.reply("✅ Terima kasih! Kontenmu dikirim ke admin.")
    await state.clear()

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype)
    await state.set_state(PostMedia.waiting_for_title)
    await m.reply("📝 **JUDUL KONTEN:**")

@dp.callback_query(F.data == "app_donasi")
async def approve_donation(c: CallbackQuery, state: FSMContext):
    if not await is_admin(c.from_user.id): return
    await state.set_state(PostMedia.waiting_for_title)
    await c.message.answer("📝 Masukkan **JUDUL** untuk postingan ini:")
    await c.answer()

@dp.callback_query(F.data == "reject")
async def reject_donation(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    await c.message.delete()
    await c.answer("Ditolak.")

@dp.message(PostMedia.waiting_for_title)
async def set_title_post(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER** (Thumbnail) untuk channel:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    data = await state.get_data()
    code = uuid.uuid4().hex[:30] 
    final_fid = data.get('temp_fid', m.photo[-1].file_id)
    final_type = data.get('temp_type', "photo")
    title = data['title']

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, final_fid, final_type, title))
        await db.commit()

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={code}"
    
    ch_target = await get_config("channel_post")
    if ch_target:
        caption = f"🔥 **{title}**\n\n👇 **KLIK TOMBOL DIBAWAH** 👇"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
        try:
            await bot.send_photo(ch_target, m.photo[-1].file_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
            msg = f"✅ Posted to {ch_target}"
        except Exception as e:
            msg = f"❌ Gagal post: {e}"
    else:
        msg = "⚠️ Channel belum diset."

    await m.answer(f"{msg}\nLink: `{link}`", parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data.startswith("reply:"))
async def reply_handler(c: CallbackQuery, state: FSMContext):
    if not await is_admin(c.from_user.id): return
    uid = c.data.split(":")[1]
    await state.update_data(reply_to=uid)
    await state.set_state(AdminStates.waiting_for_reply)
    await c.message.answer(f"✍️ Tulis balasan untuk ID `{uid}`:")
    await c.answer()

@dp.message(AdminStates.waiting_for_reply)
async def send_reply(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    data = await state.get_data()
    try:
        await bot.send_message(data['reply_to'], f"📩 **ADMIN MEMBALAS:**\n\n{m.text}", parse_mode="Markdown")
        await m.reply("✅ Terkirim.")
    except:
        await m.reply("❌ Gagal.")
    await state.clear()

# ================= START & DEEP LINK HANDLER =================
@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    code = args[1] if len(args) > 1 else None
    
    is_joined = await check_membership(message.from_user.id)
    if not is_joined:
        addlist_link = await get_config("addlist_link")
        final_link = addlist_link if addlist_link else f"https://t.me/{(await bot.get_me()).username}"
        callback_url = f"https://t.me/{(await bot.get_me()).username}?start={code}" if code else f"https://t.me/{(await bot.get_me()).username}?start"
        kb_fsub = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN ALL CHANNELS", url=final_link)],
            [InlineKeyboardButton(text="🔄 COBA LAGI", url=callback_url)]
        ])
        return await message.answer("⚠️ **AKSES DIKUNCI**\nSilahkan join dulu.", reply_markup=kb_fsub)

    if not code:
        kb_menu = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Tanya Admin", callback_data="menu_ask")],
            [InlineKeyboardButton(text="🎁 Donasi Konten", callback_data="menu_donate")]
        ])
        return await message.answer(f"👋 Halo {message.from_user.first_name}!", reply_markup=kb_menu)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
            if row:
                if row[1] == "photo":
                    await bot.send_photo(message.chat.id, row[0], caption=row[2], protect_content=True)
                else:
                    await bot.send_video(message.chat.id, row[0], caption=row[2], protect_content=True)
            else:
                await message.answer("❌ Media tidak ditemukan.")

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot Berjalan...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

