import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    FSInputFile, CallbackQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    OWNER_ID = 0

# ================= INISIALISASI =================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
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
    waiting_for_qris = State()
    waiting_for_preview = State()
    waiting_for_cover = State()
    waiting_for_add_title = State()

class MemberStates(StatesGroup):
    waiting_for_ask = State()
    waiting_for_donation = State()
    waiting_for_vip_ss = State()

class PostMedia(StatesGroup):
    waiting_for_post_title = State()

# ================= DATABASE HELPER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS titles (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
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

async def delete_config(key):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM config WHERE key=?", (key,))
        await db.commit()

async def is_admin(user_id: int):
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def check_membership(user_id: int):
    raw_targets = await get_config("fsub_channels")
    if not raw_targets: return True
    targets = raw_targets.split()
    for target in targets:
        try:
            m = await bot.get_chat_member(chat_id=target, user_id=user_id)
            if m.status in ("left", "kicked"): return False
        except: continue
    return True

# ================= KEYBOARDS =================
async def get_titles_kb():
    kb = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM titles ORDER BY id DESC LIMIT 10") as cur:
            async for row in cur:
                kb.append([InlineKeyboardButton(text=row[0], callback_data=f"t_sel:{row[0][:20]}")])
    kb.append([InlineKeyboardButton(text="➕ TAMBAH JUDUL BARU", callback_data="add_title_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def member_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 DONASI", callback_data="menu_donasi"), InlineKeyboardButton(text="❓ ASK", callback_data="menu_ask")],
        [InlineKeyboardButton(text="💎 ORDER VIP", callback_data="menu_vip"), InlineKeyboardButton(text="👀 PREVIEW VIP", callback_data="vip_preview")]
    ])

# ================= START HANDLER (STRICT FSUB) =================
@dp.message(CommandStart())
async def start_handler(m: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (m.from_user.id,))
        await db.commit()

    args = m.text.split()
    code = args[1] if len(args) > 1 else None

    # CEK FSUB DULU (Wajib Join)
    if not await check_membership(m.from_user.id):
        link = await get_config("addlist_link") or "https://t.me"
        # Tombol coba lagi harus mengarah ke link start awal biar user ga bingung
        retry_url = f"https://t.me/{(await bot.get_me()).username}?start={code}" if code else f"https://t.me/{(await bot.get_me()).username}?start"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL DULU", url=link)],
            [InlineKeyboardButton(text="🔄 SAYA SUDAH JOIN (COBA LAGI)", url=retry_url)]
        ])
        return await m.answer("⚠️ **AKSES DIKUNCI**\n\nSilahkan bergabung dengan channel kami terlebih dahulu untuk melihat konten atau menggunakan menu bot.", reply_markup=kb)

    # JIKA SUDAH JOIN & ADA CODE (NONTON)
    if code:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
                row = await cur.fetchone()
                if row:
                    if row[1] == "photo": await bot.send_photo(m.chat.id, row[0], caption=row[2], protect_content=True)
                    else: await bot.send_video(m.chat.id, row[0], caption=row[2], protect_content=True)
                    return
                else:
                    await m.answer("❌ Media tidak ditemukan atau telah dihapus.")

    # JIKA SUDAH JOIN & TIDAK ADA CODE (MENU UTAMA)
    await m.answer(f"👋 Halo {m.from_user.first_name}!\nSelamat datang di bot kami.", reply_markup=member_main_kb())

# ================= LOGIKA AUTO POST (NO CAPTION QUESTION) =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    # Langsung ambil caption dari media yang dikirim (bisa None/kosong)
    m_caption = m.caption if m.caption else ""
    
    await state.update_data(temp_fid=fid, temp_type=mtype, m_cap=m_caption)
    await state.set_state(PostMedia.waiting_for_post_title)
    await m.reply("📝 **PILIH JUDUL UNTUK POSTINGAN CHANNEL:**", reply_markup=await get_titles_kb())

@dp.callback_query(PostMedia.waiting_for_post_title, F.data.startswith("t_sel:"))
async def select_title_handler(c: CallbackQuery, state: FSMContext):
    title = c.data.split(":")[1]
    await finalize_logic(c.message, state, title)

@dp.callback_query(PostMedia.waiting_for_post_title, F.data == "add_title_btn")
async def add_new_title_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Ketik judul baru untuk channel:")
    await state.set_state(AdminStates.waiting_for_add_title)

@dp.message(AdminStates.waiting_for_add_title)
async def process_save_title(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO titles (title) VALUES (?)", (m.text,))
        await db.commit()
    await finalize_logic(m, state, m.text)

async def finalize_logic(msg, state, post_title):
    data = await state.get_data()
    code = uuid.uuid4().hex[:15]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['temp_fid'], data['temp_type'], data['m_cap']))
        await db.commit()

    link = f"https://t.me/{(await bot.get_me()).username}?start={code}"
    ch = await get_config("channel_post")
    cover = await get_config("cover_file_id")

    if ch and cover:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
            await bot.send_photo(ch, cover, caption=f"🔥 **{post_title}**", reply_markup=kb)
        except: pass
    
    await msg.answer(f"✅ **BERHASIL DIPOSTING!**\n\nJudul Post: `{post_title}`\nCaption Media: `{data['m_cap'] if data['m_cap'] else '-'}`\nLink: `{link}`")
    await state.clear()

# ================= ADMIN PANEL & UPDATE (LENGKAP) =================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id): return
    buttons = [
        [InlineKeyboardButton(text="⚙️ CONFIG", callback_data="open_settings")],
        [InlineKeyboardButton(text="🖼 SET COVER", callback_data="set_cover"), InlineKeyboardButton(text="🖼 SET QRIS", callback_data="set_qris")],
        [InlineKeyboardButton(text="📺 SET PREVIEW VIP", callback_data="set_preview")],
        [InlineKeyboardButton(text="📡 BROADCAST", callback_data="menu_broadcast"), InlineKeyboardButton(text="📦 BACKUP DB", callback_data="menu_db")]
    ]
    if message.from_user.id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="👤 TAMBAH ADMIN", callback_data="add_admin")])
    buttons.append([InlineKeyboardButton(text="❌ TUTUP", callback_data="close_panel")])
    await message.reply("🛠 **PANEL ADMIN**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(Command("update"))
async def update_database(m: Message):
    if not await is_admin(m.from_user.id): return
    if not m.reply_to_message or not m.reply_to_message.document:
        return await m.reply("❌ Reply file `.db`-nya, bre!")
    
    try:
        file = await bot.get_file(m.reply_to_message.document.file_id)
        await bot.download_file(file.file_path, DB_NAME)
        await init_db()
        await m.reply("✅ **DATABASE UPDATED!** Data terbaru sudah aktif.")
    except Exception as e:
        await m.reply(f"❌ Gagal: {e}")

# ================= FITUR LAINNYA (TIDAK DIHAPUS) =================
@dp.callback_query(F.data == "open_settings")
async def settings_cb(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    ch = await get_config("channel_post", "Kosong")
    fs = await get_config("fsub_channels", "Kosong")
    al = "Set" if await get_config("addlist_link") else "Kosong"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 SET POST CH", callback_data="set_post"), InlineKeyboardButton(text="🗑️", callback_data="del_channel_post")],
        [InlineKeyboardButton(text="👥 SET FSUB", callback_data="set_fsub_list"), InlineKeyboardButton(text="🗑️", callback_data="del_fsub_channels")],
        [InlineKeyboardButton(text="🔗 SET ADDLIST", callback_data="set_addlist"), InlineKeyboardButton(text="🗑️", callback_data="del_addlist_link")],
        [InlineKeyboardButton(text="🔙 BACK", callback_data="close_panel")]
    ])
    await c.message.edit_text(f"⚙️ **CONFIG**\nPost: `{ch}`\nFsub: `{fs}`\nAddlist: `{al}`", reply_markup=kb)

@dp.callback_query(F.data == "menu_ask")
async def ask_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim pertanyaanmu:")
    await state.set_state(MemberStates.waiting_for_ask)

@dp.message(MemberStates.waiting_for_ask)
async def process_ask(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")]])
    await bot.send_message(OWNER_ID, f"📩 **ASK** `{m.from_user.id}`:\n{m.text}", reply_markup=kb)
    await m.reply("✅ Terkirim.")
    await state.clear()

@dp.callback_query(F.data == "menu_donasi")
async def donasi_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim file/pesan donasi:")
    await state.set_state(MemberStates.waiting_for_donation)

@dp.message(MemberStates.waiting_for_donation)
async def process_donation(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ OK", callback_data="close_panel")]])
    await m.copy_to(OWNER_ID, caption=f"🎁 **DONASI** dari `{m.from_user.id}`", reply_markup=kb)
    await m.reply("✅ Terkirim.")
    await state.clear()

@dp.callback_query(F.data == "menu_vip")
async def order_vip(c: CallbackQuery, state: FSMContext):
    qris = await get_config("qris_file_id")
    if not qris: return await c.answer("QRIS belum diset.")
    await bot.send_photo(c.message.chat.id, qris, caption="Scan & kirim SS bukti bayar:")
    await state.set_state(MemberStates.waiting_for_vip_ss)

@dp.message(MemberStates.waiting_for_vip_ss, F.photo)
async def process_vip_ss(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 REPLY/LINK", callback_data=f"reply:{m.from_user.id}")]])
    await m.copy_to(OWNER_ID, caption=f"💎 **VIP SS** dari `{m.from_user.id}`", reply_markup=kb)
    await m.reply("✅ Menunggu konfirmasi admin.")
    await state.clear()

@dp.callback_query(F.data == "vip_preview")
async def preview_vip(c: CallbackQuery):
    prev = await get_config("preview_msg_id")
    if not prev: return await c.answer("Preview belum diset.")
    await bot.copy_message(c.message.chat.id, OWNER_ID, int(prev))

# ================= SET CONFIG (OLD FEATURES) =================
@dp.callback_query(F.data == "add_admin", F.from_user.id == OWNER_ID)
async def add_admin_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim ID Admin:")
    await state.set_state(AdminStates.waiting_for_new_admin)

@dp.message(AdminStates.waiting_for_new_admin, F.from_user.id == OWNER_ID)
async def save_admin(m: Message, state: FSMContext):
    try:
        await aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (int(m.text),))
            await db.commit()
        await m.reply("✅ Admin ditambahkan.")
    except: pass
    await state.clear()

@dp.callback_query(F.data == "set_post")
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Username Channel (cth: @ch):")
    await state.set_state(AdminStates.waiting_for_channel_post)

@dp.message(AdminStates.waiting_for_channel_post)
async def save_post_ch(m: Message, state: FSMContext):
    await set_config("channel_post", m.text.strip())
    await m.reply("✅ Tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_fsub_list")
async def set_fsub_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Username channel fsub (spasi jika lebih dari 1):")
    await state.set_state(AdminStates.waiting_for_fsub_list)

@dp.message(AdminStates.waiting_for_fsub_list)
async def save_fsub(m: Message, state: FSMContext):
    await set_config("fsub_channels", m.text.strip())
    await m.reply("✅ Fsub list tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_addlist")
async def set_addlist_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Link Addlist:")
    await state.set_state(AdminStates.waiting_for_addlist)

@dp.message(AdminStates.waiting_for_addlist)
async def save_addlist(m: Message, state: FSMContext):
    await set_config("addlist_link", m.text.strip())
    await m.reply("✅ Link tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_cover")
async def set_cover_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto Cover Post:")
    await state.set_state(AdminStates.waiting_for_cover)

@dp.message(AdminStates.waiting_for_cover, F.photo)
async def save_cover(m: Message, state: FSMContext):
    await set_config("cover_file_id", m.photo[-1].file_id)
    await m.reply("✅ Cover tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_qris")
async def set_qris_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto QRIS:")
    await state.set_state(AdminStates.waiting_for_qris)

@dp.message(AdminStates.waiting_for_qris, F.photo)
async def save_qris(m: Message, state: FSMContext):
    await set_config("qris_file_id", m.photo[-1].file_id)
    await m.reply("✅ QRIS tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_preview")
async def set_preview_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim media preview (Bot catat ID pesan):")
    await state.set_state(AdminStates.waiting_for_preview)

@dp.message(AdminStates.waiting_for_preview)
async def save_prev(m: Message, state: FSMContext):
    await set_config("preview_msg_id", str(m.message_id))
    await m.reply("✅ Preview tersimpan.")
    await state.clear()

@dp.callback_query(F.data == "menu_db")
async def backup_db_btn(c: CallbackQuery):
    if c.from_user.id != OWNER_ID: return
    await c.message.reply_document(FSInputFile(DB_NAME))

@dp.callback_query(F.data == "menu_broadcast")
async def bc_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim pesan BC:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast)
async def do_bc(m: Message, state: FSMContext):
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            async for row in cur:
                try:
                    await m.copy_to(row[0])
                    count += 1
                    await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Terkirim ke {count} user.")
    await state.clear()

@dp.callback_query(F.data.startswith("reply:"))
async def reply_handler(c: CallbackQuery, state: FSMContext):
    uid = c.data.split(":")[1]
    await state.update_data(target=uid)
    await c.message.answer(f"Balasan untuk `{uid}`:")
    await state.set_state(AdminStates.waiting_for_reply)

@dp.message(AdminStates.waiting_for_reply)
async def send_reply(m: Message, state: FSMContext):
    d = await state.get_data()
    try: await m.copy_to(d['target'])
    except: pass
    await m.reply("✅ Balasan terkirim.")
    await state.clear()

@dp.callback_query(F.data == "close_panel")
async def close_cb(c: CallbackQuery): await c.message.delete()

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
