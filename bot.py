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

# ================= RAILWAY CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USN = os.getenv("BOT_USERNAME", "").replace("@", "")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

class AdminState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    set_start_txt = State()
    set_fsub_txt = State()
    set_btn_txt = State()
    set_fsub_list = State()
    set_db_ch_id = State()
    set_post_ch_id = State()
    set_log_id = State()
    set_exempt_usn = State()

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

async def get_s():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= SETTINGS DASHBOARD =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def dashboard(m: Message):
    s = await get_s()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Edit Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="📢 Edit FSub Teks", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="🔗 Set FSub List", callback_data="conf_fsub_list"), InlineKeyboardButton(text="🔘 Set Tombol", callback_data="conf_btn_txt")],
        [InlineKeyboardButton(text="📁 Set DB Backup", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="📣 Set Post CH", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="📜 Set Log ID", callback_data="conf_log_id"), InlineKeyboardButton(text="🛡️ Set Exempt", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="📊 Statistik", callback_data="conf_stats"), InlineKeyboardButton(text="💾 Ambil .db", callback_data="conf_dbfile")]
    ])
    text = (f"⚙️ **ADMIN DASHBOARD**\n\n"
            f"📍 **Post CH:** `{s['post_ch_id'] or 'Belum Set'}`\n"
            f"📂 **DB Backup:** `{s['db_ch_id'] or 'Belum Set'}`\n"
            f"📋 **FSub List:** `{s['fsub_list'] or 'Kosong'}`\n"
            f"🛡️ **Exempt:** `{s['exempt_usn'] or 'Kosong'}`")
    await m.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("conf_"))
async def handle_settings_cb(c: CallbackQuery, state: FSMContext):
    action = c.data.replace("conf_", "")
    
    if action == "stats":
        async with aiosqlite.connect("master.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
            async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
        return await c.answer(f"📊 Statistik:\nUser: {u[0]}\nMedia: {m[0]}", show_alert=True)
    
    if action == "dbfile":
        await c.message.answer_document(FSInputFile("master.db"))
        return await c.answer()

    # Memicu State berdasarkan action
    state_to_set = getattr(AdminState, f"set_{action}")
    await state.set_state(state_to_set)
    
    prompts = {
        "start_txt": "Kirim teks Start baru:",
        "fsub_txt": "Kirim teks peringatan FSub baru:",
        "btn_txt": "Kirim teks untuk tombol nonton:",
        "fsub_list": "Kirim Username CH (tanpa @, pisah koma jika banyak):",
        "db_ch_id": "Kirim ID Channel Backup (Contoh: -100123456):",
        "post_ch_id": "Kirim ID Channel Post (Contoh: -100987654):",
        "log_id": "Kirim ID Grup Log:",
        "exempt_usn": "Kirim Username yang kebal filter (pisah koma):"
    }
    await c.message.answer(f"📥 {prompts.get(action, 'Kirim data baru:')}")
    await c.answer()

@dp.message(StateFilter(AdminState))
async def save_settings_logic(m: Message, state: FSMContext):
    current_state = await state.get_state()
    # Mencocokkan nama kolom database dengan nama state
    column_name = current_state.split("set_")[-1]
    
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {column_name}=? WHERE id=1", (m.text,))
        await db.commit()
    
    await m.answer(f"✅ Data **{column_name}** berhasil disimpan!")
    await state.clear()

# ================= AUTO POST & DONASI =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def master_upload_handler(m: Message, state: FSMContext):
    s = await get_s()
    if m.from_user.id != ADMIN_ID:
        # LOG DONASI
        if s['log_id']: 
            try: await bot.send_message(s['log_id'], f"🎁 **DONASI BARU**\nUser: {m.from_user.full_name}\nID: `{m.from_user.id}`")
            except: pass
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE & POST", callback_data="admin_app_don")]])
        return await m.answer("✅ Konten donasi kamu sudah terkirim ke Admin!", reply_markup=None)

    # Admin Mode
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(AdminState.wait_title)
    await m.reply("🏷 **JUDUL:**\nApa judul untuk konten ini?")

@dp.callback_query(F.data == "admin_app_don")
async def start_approve(c: CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.wait_title)
    await c.message.answer("📝 Masukkan Judul untuk Donasi ini:")
    await c.answer()

@dp.message(AdminState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AdminState.wait_cover)
    await m.answer("📸 **COVER:**\nKirim Foto Cover/Poster untuk di Channel:")

@dp.message(AdminState.wait_cover, F.photo)
async def process_publish(m: Message, state: FSMContext):
    data = await state.get_data()
    s = await get_s()
    code = uuid.uuid4().hex[:8]
    
    # Backup ke Channel DB
    if s['db_ch_id']:
        try: await bot.copy_message(s['db_ch_id'], m.chat.id, m.message_id)
        except: pass
    
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['fid'], data['mtype'], data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USN}?start={code}"
    if s['post_ch_id']:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_txt'], url=link)]])
        try: await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=f"🔥 **{data['title']}**", reply_markup=kb)
        except Exception as e: await m.answer(f"❌ Gagal post ke CH: {e}")
    
    await m.answer(f"✅ **PUBLISHED!**\nLink: `{link}`")
    await state.clear()

# ================= MEMBER AREA =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    uid = m.from_user.id
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        await db.commit()
    
    s = await get_s()
    args = m.text.split()[1] if len(m.text.split()) > 1 else code_override
    
    if not args:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Donasi", callback_data="act_don"), InlineKeyboardButton(text="💬 Ask", callback_data="act_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Force Join Logic
    must_join = []
    if s['fsub_list']:
        for ch in s['fsub_list'].split(","):
            try:
                member = await bot.get_chat_member(f"@{ch.strip()}", uid)
                if member.status not in ("member", "administrator", "creator"): must_join.append(ch.strip())
            except: pass
    
    if must_join:
        btns = [[InlineKeyboardButton(text=f"JOIN {c}", url=f"https://t.me/{c}")] for c in must_join]
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{args}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (args,)) as cur: row = await cur.fetchone()
    
    if row:
        cap = f"🎬 **{row['title']}**"
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=cap)
        else: await bot.send_video(m.chat.id, row['fid'], caption=cap)

@dp.callback_query(F.data.startswith("retry_"))
async def retry_callback(c: CallbackQuery):
    code = c.data.split("_")[1]
    await c.message.delete()
    await start_handler(c.message, code_override=code)

@dp.callback_query(F.data.startswith("act_"))
async def member_actions(c: CallbackQuery):
    action = c.data.replace("act_", "")
    if action == "don": await c.message.answer("🙏 Silakan kirim media donasi kamu langsung ke sini!")
    if action == "ask": await c.message.answer("💬 Gunakan perintah `/ask pesan kamu` untuk bertanya.")
    await c.answer()

@dp.message(Command("ask"))
async def ask_cmd(m: Message):
    txt = m.text.split(maxsplit=1)
    if len(txt) < 2: return await m.reply("⚠️ `/ask isi pesan` ")
    await bot.send_message(ADMIN_ID, f"📩 **PESAN ASK**\nUser: {m.from_user.full_name}\nID: `{m.from_user.id}`\n\n{txt[1]}")
    await m.reply("✅ Terkirim ke Admin.")

# ================= RUN =================
async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai"),
        BotCommand(command="ask", description="Tanya Admin"),
        BotCommand(command="settings", description="Admin Only")
    ], scope=BotCommandScopeDefault())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
