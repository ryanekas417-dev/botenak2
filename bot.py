import asyncio, uuid, os, aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, 
    CallbackQuery, ChatMemberUpdated, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USN = os.getenv("BOT_USERNAME", "").replace("@", "")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

class BotState(StatesGroup):
    # Admin States
    wait_title = State()
    wait_cover = State()
    # Settings States
    set_start_txt = State()
    set_fsub_txt = State()
    set_btn_txt = State()
    set_fsub_list = State()
    set_db_ch_id = State()
    set_post_ch_id = State()
    set_log_id = State()
    set_exempt_usn = State()
    # Member States
    wait_ask = State()
    wait_donasi = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, 
            start_txt TEXT, fsub_txt TEXT, btn_txt TEXT, 
            fsub_list TEXT, db_ch_id TEXT, post_ch_id TEXT, 
            log_id TEXT, exempt_usn TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_txt, fsub_list, db_ch_id, post_ch_id, log_id, exempt_usn) 
            VALUES (1, 'Halo! Selamat datang.', 'Silakan Join Channel:', '🎬 NONTON', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur:
            return await cur.fetchone()

# ================= DASHBOARD ADMIN =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def dashboard(m: Message):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Edit Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="📢 Edit FSub Teks", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="🔗 Set FSub List", callback_data="conf_fsub_list"), InlineKeyboardButton(text="🔘 Set Tombol", callback_data="conf_btn_txt")],
        [InlineKeyboardButton(text="📁 Set DB Backup", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="📣 Set Post CH", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="📜 Set Log ID", callback_data="conf_log_id"), InlineKeyboardButton(text="🛡️ Set Exempt", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="📊 Statistik", callback_data="conf_stats"), InlineKeyboardButton(text="💾 Ambil .db", callback_data="conf_dbfile")]
    ])
    text = (f"⚙️ **ADMIN DASHBOARD**\n\n"
            f"📍 **Post CH ID:** `{s['post_ch_id'] or 'Not Set'}`\n"
            f"📂 **DB Backup ID:** `{s['db_ch_id'] or 'Not Set'}`\n"
            f"📋 **FSub List:** `{s['fsub_list'] or 'Empty'}`\n"
            f"🛡️ **Exempt:** `{s['exempt_usn'] or 'None'}`")
    await m.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def config_cb(c: CallbackQuery, state: FSMContext):
    action = c.data.replace("conf_", "")
    if action == "stats":
        async with aiosqlite.connect("master.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
            async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
        return await c.answer(f"User: {u[0]} | Media: {m[0]}", show_alert=True)
    if action == "dbfile":
        return await c.message.answer_document(FSInputFile("master.db"))

    await state.set_state(getattr(BotState, f"set_{action}"))
    await c.message.answer(f"📥 Kirim data baru untuk **{action}**:")
    await c.answer()

@dp.message(StateFilter(BotState.set_start_txt, BotState.set_fsub_txt, BotState.set_btn_txt, BotState.set_fsub_list, BotState.set_db_ch_id, BotState.set_post_ch_id, BotState.set_log_id, BotState.set_exempt_usn))
async def save_config(m: Message, state: FSMContext):
    st = await state.get_state()
    col = st.split("set_")[-1]
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {col}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ **{col}** diperbarui!")
    await state.clear()

# ================= AUTO POST & DONASI =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def upload_handler(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        # Langsung forward ke Admin
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE", callback_data="adm_approve")]])
        await bot.send_message(ADMIN_ID, f"🎁 **Donasi Baru** dari {m.from_user.full_name}:", reply_markup=kb)
        return await m.answer("✅ Konten donasi terkirim ke admin!")

    # Admin mode
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, mtype="photo" if m.photo else "video")
    await state.set_state(BotState.wait_title)
    await m.reply("🏷 **JUDUL:** Masukkan judul konten:")

@dp.callback_query(F.data == "adm_approve")
async def approve_don(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_title)
    await c.message.answer("📝 Masukkan Judul untuk Donasi ini:")
    await c.answer()

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("📸 **COVER:** Kirim Foto Cover untuk postingan channel:")

@dp.message(BotState.wait_cover, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    data = await state.get_data()
    s = await get_conf()
    code = uuid.uuid4().hex[:8]
    
    # Simpan DB & Backup
    if s['db_ch_id']:
        try: await bot.copy_message(s['db_ch_id'], m.chat.id, m.message_id)
        except: pass
    
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['fid'], data['mtype'], data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USN}?start={code}"
    # AUTO POST FIX
    if s['post_ch_id']:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_txt'], url=link)]])
        try: 
            # Menggunakan ID channel dari database
            await bot.send_photo(chat_id=s['post_ch_id'], photo=m.photo[-1].file_id, caption=f"🔥 **{data['title']}**", reply_markup=kb)
        except Exception as e: 
            await m.answer(f"❌ Gagal Post ke Channel! Cek apakah bot sudah jadi admin di `{s['post_ch_id']}`. Error: {e}")
    
    await m.answer(f"✅ **PUBLISHED!**\nLink: `{link}`")
    await state.clear()

# ================= MEMBER AREA (NO COMMAND) =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    arg = m.text.split()[1] if len(m.text.split()) > 1 else code_override
    
    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Donasi", callback_data="mem_don"), InlineKeyboardButton(text="💬 Ask Admin", callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Force Join
    must_join = []
    if s['fsub_list']:
        for ch in s['fsub_list'].split(","):
            try:
                member = await bot.get_chat_member(f"@{ch.strip()}", m.from_user.id)
                if member.status not in ("member", "administrator", "creator"): must_join.append(ch.strip())
            except: pass
    
    if must_join:
        btns = [[InlineKeyboardButton(text=f"JOIN {c}", url=f"https://t.me/{c}")] for c in must_join]
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        cap = f"🎬 **{row['title']}**"
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=cap)
        else: await bot.send_video(m.chat.id, row['fid'], caption=cap)

@dp.callback_query(F.data == "mem_don")
async def mem_don_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🙏 Silakan kirim **Foto atau Video** konten yang ingin kamu donasikan:")
    await c.answer()

@dp.callback_query(F.data == "mem_ask")
async def mem_ask_cb(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_ask)
    await c.message.answer("💬 Silakan ketik pesan/pertanyaan kamu untuk admin:")
    await c.answer()

@dp.message(BotState.wait_ask)
async def process_ask(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📩 **ASK** dari {m.from_user.full_name} (`{m.from_user.id}`):\n\n{m.text}")
    await m.answer("✅ Pesan terkirim ke admin!")
    await state.clear()

@dp.callback_query(F.data.startswith("retry_"))
async def retry_cb(c: CallbackQuery):
    code = c.data.split("_")[1]
    await c.message.delete()
    await start_handler(c.message, code_override=code)

# ================= RUN =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
