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
            m = await bot.get_chat_member(target, user_id)
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
    kb.append([InlineKeyboardButton(text="➕ TAMBAH JUDUL", callback_data="add_title_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def member_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 DONASI", callback_data="menu_donasi"), InlineKeyboardButton(text="❓ ASK", callback_data="menu_ask")],
        [InlineKeyboardButton(text="💎 ORDER VIP", callback_data="menu_vip"), InlineKeyboardButton(text="👀 PREVIEW VIP", callback_data="vip_preview")]
    ])

# ================= MEMBER & FSUB (FIXED) =================
@dp.message(CommandStart())
async def start_handler(m: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (m.from_user.id,))
        await db.commit()

    args = m.text.split()
    target_code = args[1] if len(args) > 1 else None

    # CEK JOIN DULU SEBELUM NGASIH APA-APA
    if not await check_membership(m.from_user.id):
        link = await get_config("addlist_link") or "https://t.me"
        # Biar pas diklik "Coba Lagi" dia balik ke link filmnya
        retry_url = f"https://t.me/{(await bot.get_me()).username}?start={target_code}" if target_code else f"https://t.me/{(await bot.get_me()).username}?start"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=link)],
            [InlineKeyboardButton(text="🔄 COBA LAGI", url=retry_url)]
        ])
        return await m.answer("⚠️ **AKSES DIKUNCI**\nSilahkan join dulu untuk menggunakan bot atau melihat konten.", reply_markup=kb)

    # JIKA SUDAH JOIN, BARU KASIH MEDIA ATAU MENU
    if target_code:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (target_code,)) as cur:
                row = await cur.fetchone()
                if row:
                    if row[1] == "photo": await bot.send_photo(m.chat.id, row[0], caption=row[2], protect_content=True)
                    else: await bot.send_video(m.chat.id, row[0], caption=row[2], protect_content=True)
                    return

    await m.answer(f"👋 Halo {m.from_user.first_name}!", reply_markup=member_main_kb())

# ================= LOGIKA AUTO POST (FIXED NO CAPTION QUESTION) =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    # LANGSUNG AMBIL CAPTION DARI PESAN YANG DIKIRIM
    current_caption = m.caption if m.caption else ""
    
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=current_caption)
    await state.set_state(PostMedia.waiting_for_post_title)
    await m.reply("📝 **PILIH JUDUL UNTUK CHANNEL:**", reply_markup=await get_titles_kb())

@dp.callback_query(PostMedia.waiting_for_post_title, F.data.startswith("t_sel:"))
async def select_title_handler(c: CallbackQuery, state: FSMContext):
    title = c.data.split(":")[1]
    await finish_posting(c.message, state, title)

@dp.callback_query(PostMedia.waiting_for_post_title, F.data == "add_title_btn")
async def add_new_title_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Ketik judul baru untuk channel:")
    await state.set_state(AdminStates.waiting_for_add_title)

@dp.message(AdminStates.waiting_for_add_title)
async def process_save_title(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO titles (title) VALUES (?)", (m.text,))
        await db.commit()
    await finish_posting(m, state, m.text)

async def finish_posting(msg, state, p_title):
    data = await state.get_data()
    code = uuid.uuid4().hex[:15]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['temp_fid'], data['temp_type'], data['temp_caption']))
        await db.commit()

    link = f"https://t.me/{(await bot.get_me()).username}?start={code}"
    ch = await get_config("channel_post")
    cover = await get_config("cover_file_id")

    if ch and cover:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
        await bot.send_photo(ch, cover, caption=f"🔥 **{p_title}**", reply_markup=kb)
    
    await msg.answer(f"✅ Berhasil!\nLink: `{link}`")
    await state.clear()

# ================= HANDLERS ADMIN (REMAINING) =================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id): return
    buttons = [
        [InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="open_settings")],
        [InlineKeyboardButton(text="🖼 SET COVER", callback_data="set_cover"), InlineKeyboardButton(text="🖼 SET QRIS", callback_data="set_qris")],
        [InlineKeyboardButton(text="📺 SET PREVIEW", callback_data="set_preview")],
        [InlineKeyboardButton(text="📡 BROADCAST", callback_data="menu_broadcast"), InlineKeyboardButton(text="📦 BACKUP DB", callback_data="menu_db")]
    ]
    if message.from_user.id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="👤 TAMBAH ADMIN", callback_data="add_admin")])
    buttons.append([InlineKeyboardButton(text="❌ TUTUP", callback_data="close_panel")])
    await message.reply("🛠 **PANEL ADMIN**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "open_settings")
async def settings_cb(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    ch_post = await get_config("channel_post", "Belum diset")
    fsub = await get_config("fsub_channels", "Belum diset")
    addlist = "Sudah diset" if await get_config("addlist_link") else "Belum diset"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 SET POST CH", callback_data="set_post")],
        [InlineKeyboardButton(text="👥 SET FSUB", callback_data="set_fsub_list")],
        [InlineKeyboardButton(text="🔗 SET ADDLIST", callback_data="set_addlist")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="close_panel")]
    ])
    await c.message.edit_text(f"⚙️ **CONFIG**\nPost: `{ch_post}`\nFsub: `{fsub}`\nAddlist: `{addlist}`", reply_markup=kb)

@dp.message(Command("update"))
async def update_database(m: Message):
    if not await is_admin(m.from_user.id): return
    if not m.reply_to_message or not m.reply_to_message.document:
        return await m.reply("❌ Reply file `.db`, lalu ketik `/update`.")
    try:
        file = await bot.get_file(m.reply_to_message.document.file_id)
        await bot.download_file(file.file_path, DB_NAME)
        await init_db()
        await m.reply("✅ **DATABASE UPDATED!**")
    except Exception as e:
        await m.reply(f"❌ Error: {e}")

# ================= OTHER CALLBACKS =================
@dp.callback_query(F.data == "menu_ask")
async def ask_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Silahkan kirim pesan/pertanyaanmu:"); await state.set_state(MemberStates.waiting_for_ask)

@dp.message(MemberStates.waiting_for_ask)
async def process_ask(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")]])
    await bot.send_message(OWNER_ID, f"📩 **PESAN BARU**\nDari: `{m.from_user.id}`\n\n{m.text}", reply_markup=kb)
    await m.reply("✅ Terkirim ke admin."); await state.clear()

@dp.callback_query(F.data == "menu_donasi")
async def donasi_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim file/pesan donasi Anda:"); await state.set_state(MemberStates.waiting_for_donation)

@dp.message(MemberStates.waiting_for_donation)
async def process_donation(m: Message, state: FSMContext):
    await m.copy_to(OWNER_ID, caption=f"🎁 **DONASI BARU**\nDari: `{m.from_user.id}`")
    await m.reply("✅ Terkirim ke admin."); await state.clear()

@dp.callback_query(F.data == "menu_vip")
async def order_vip(c: CallbackQuery, state: FSMContext):
    qris = await get_config("qris_file_id")
    if not qris: return await c.answer("QRIS belum diset.", show_alert=True)
    await bot.send_photo(c.message.chat.id, qris, caption="Scan & kirim SS bukti bayar:"); await state.set_state(MemberStates.waiting_for_vip_ss)

@dp.message(MemberStates.waiting_for_vip_ss, F.photo)
async def process_vip_ss(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 REPLY", callback_data=f"reply:{m.from_user.id}")]])
    await m.copy_to(OWNER_ID, caption=f"💎 **SS VIP**\nDari: `{m.from_user.id}`", reply_markup=kb)
    await m.reply("✅ Bukti SS terkirim."); await state.clear()

@dp.callback_query(F.data == "vip_preview")
async def preview_vip(c: CallbackQuery):
    prev = await get_config("preview_msg_id")
    if not prev: return await c.answer("Preview belum diset.")
    await bot.copy_message(c.message.chat.id, OWNER_ID, int(prev))

@dp.callback_query(F.data == "add_admin", F.from_user.id == OWNER_ID)
async def add_admin_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim User ID Admin baru:"); await state.set_state(AdminStates.waiting_for_new_admin)

@dp.message(AdminStates.waiting_for_new_admin, F.from_user.id == OWNER_ID)
async def save_new_admin(m: Message, state: FSMContext):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (int(m.text),))
            await db.commit()
        await m.reply("✅ Admin ditambahkan.")
    except: await m.reply("❌ ID salah.")
    await state.clear()

@dp.callback_query(F.data == "menu_db", F.from_user.id == OWNER_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME): await c.message.reply_document(FSInputFile(DB_NAME))
    await c.answer()

@dp.callback_query(F.data == "set_post")
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Username Channel:"); await state.set_state(AdminStates.waiting_for_channel_post)

@dp.message(AdminStates.waiting_for_channel_post)
async def process_set_post(m: Message, state: FSMContext):
    await set_config("channel_post", m.text.strip()); await m.reply("✅ Set."); await state.clear()

@dp.callback_query(F.data == "set_fsub_list")
async def set_fsub_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Username Fsub (spasi jika banyak):"); await state.set_state(AdminStates.waiting_for_fsub_list)

@dp.message(AdminStates.waiting_for_fsub_list)
async def process_fsub(m: Message, state: FSMContext):
    await set_config("fsub_channels", m.text.strip()); await m.reply("✅ Fsub Set."); await state.clear()

@dp.callback_query(F.data == "set_addlist")
async def set_addlist_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Link Addlist:"); await state.set_state(AdminStates.waiting_for_addlist)

@dp.message(AdminStates.waiting_for_addlist)
async def process_addlist(m: Message, state: FSMContext):
    await set_config("addlist_link", m.text.strip()); await m.reply("✅ Link Set."); await state.clear()

@dp.callback_query(F.data == "set_cover")
async def btn_set_cover(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto Cover:"); await state.set_state(AdminStates.waiting_for_cover)

@dp.message(AdminStates.waiting_for_cover, F.photo)
async def save_cover(m: Message, state: FSMContext):
    await set_config("cover_file_id", m.photo[-1].file_id); await m.reply("✅ Cover Set."); await state.clear()

@dp.callback_query(F.data == "set_qris")
async def btn_set_qris(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto QRIS:"); await state.set_state(AdminStates.waiting_for_qris)

@dp.message(AdminStates.waiting_for_qris, F.photo)
async def save_qris(m: Message, state: FSMContext):
    await set_config("qris_file_id", m.photo[-1].file_id); await m.reply("✅ QRIS Set."); await state.clear()

@dp.callback_query(F.data == "set_preview")
async def btn_set_prev(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim media preview:"); await state.set_state(AdminStates.waiting_for_preview)

@dp.message(AdminStates.waiting_for_preview)
async def save_preview(m: Message, state: FSMContext):
    await set_config("preview_msg_id", str(m.message_id)); await m.reply("✅ Preview Set."); await state.clear()

@dp.callback_query(F.data.startswith("reply:"))
async def reply_cb(c: CallbackQuery, state: FSMContext):
    uid = c.data.split(":")[1]; await state.update_data(target=uid)
    await c.message.answer(f"Balasan untuk `{uid}`:"); await state.set_state(AdminStates.waiting_for_reply)

@dp.message(AdminStates.waiting_for_reply)
async def process_reply_send(m: Message, state: FSMContext):
    d = await state.get_data()
    try: await m.copy_to(d['target']); await m.reply("✅ Terkirim.")
    except: await m.reply("❌ Gagal.")
    await state.clear()

@dp.callback_query(F.data == "menu_broadcast", F.from_user.id == OWNER_ID)
async def broadcast_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim pesan BC:"); await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast, F.from_user.id == OWNER_ID)
async def process_broadcast(m: Message, state: FSMContext):
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            async for row in cur:
                try: await m.copy_to(row[0]); count += 1; await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Terkirim ke {count} user."); await state.clear()

@dp.callback_query(F.data == "close_panel")
async def close_panel(c: CallbackQuery): await c.message.delete()

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
