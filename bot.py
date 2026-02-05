import asyncio, os, aiosqlite, traceback, random, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, CallbackQuery, ChatMemberUpdated, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ISI_TOKEN_DISINI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 
BOT_USN = os.getenv("BOT_USERNAME", "UsernameBot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    wait_ask = State()
    wait_broadcast = State()
    set_val = State()

def gen_code():
    char = ''.join(random.choices(string.ascii_letters + string.digits, k=30))
    return f"get_{char}"

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT, bk_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, name TEXT)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, 
            btn_nonton TEXT, btn_donasi TEXT, btn_ask TEXT,
            fsub_list TEXT, fsub_link TEXT, db_ch_id TEXT, post_ch_id TEXT, 
            log_id TEXT, exempt_usn TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_nonton, btn_donasi, btn_ask, fsub_list, fsub_link, db_ch_id, post_ch_id, log_id, exempt_usn) 
            VALUES (1, 'Halo Selamat datang', 'Wajib Join Channel Kami!', '🎬 NONTON', '🎁 DONASI', '💬 TANYA ADMIN', '', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= HELPER: TOMBOL BATAL =================
def kb_batal():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="exit_state")]])

@dp.callback_query(F.data == "exit_state")
async def exit_state_handler(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.delete()
    await c.answer("Aksi dibatalkan.")

# ================= 1. ADMIN DASHBOARD =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def cmd_settings(m: Message):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="Teks FSub", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="Link FSub", callback_data="conf_fsub_link"), InlineKeyboardButton(text="List User FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="ID CH DB", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="ID CH Post", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="ID Log", callback_data="conf_log_id"), InlineKeyboardButton(text="Exempt Admin", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="adm_stats"), InlineKeyboardButton(text="💾 Backup", callback_data="adm_dbfile")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="exit_state")]
    ])
    await m.answer("⚙️ **ADMIN PANEL**\nSilakan pilih menu yang ingin diubah:", reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def config_edit(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("conf_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    await c.message.edit_text(f"Kirim nilai baru untuk `{field}`:", reply_markup=kb_batal())

@dp.message(BotState.set_val)
async def config_save(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ Berhasil simpan `{data['field']}`.")
    await state.clear()

# ================= 2. AUTO POST & DONASI =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def upload_manager(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}"),
             InlineKeyboardButton(text="❌ REJECT", callback_data="exit_state")]
        ])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"🎁 Donasi: {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("✅ Donasi terkirim ke admin.")

    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else ("video" if m.video else "doc")
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(BotState.wait_title)
    await m.answer("🏷️ Masukkan JUDUL konten:", reply_markup=kb_batal())

@dp.callback_query(F.data.startswith("don_app_"))
async def donasi_approve(c: CallbackQuery, state: FSMContext):
    parts = c.data.split("_")
    uid, mid = parts[2], parts[3]
    msg = await bot.forward_message(ADMIN_ID, uid, int(mid))
    fid = msg.photo[-1].file_id if msg.photo else (msg.video.file_id if msg.video else msg.document.file_id)
    mtype = "photo" if msg.photo else ("video" if msg.video else "doc")
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(BotState.wait_title)
    await c.message.answer("Donasi diterima. Masukkan JUDUL:", reply_markup=kb_batal())

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("📸 Kirim FOTO COVER:", reply_markup=kb_batal())

@dp.message(BotState.wait_cover, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code = gen_code()
        
        bk_id = ""
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, caption=f"KODE: `{code}`\nTITLE: {data['title']}")
            bk_id = str(bk.message_id)
        
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['mtype'], data['title'], bk_id))
            await db.commit()

        if s['post_ch_id']:
            link = f"https://t.me/{emsamasamaenak_bot}?start={code}"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
        
        await m.answer(f"✅ BERHASIL!\nLink: `https://t.me/{emsamasamaenak_bot}?start={code}")
    finally: await state.clear()

# ================= 3. MEMBER INTERACTION =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_don"), 
             InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Force Join Check
    must_join = False
    if s['fsub_list']:
        for ch in s['fsub_list'].replace("@","").split(","):
            if not ch.strip(): continue
            try:
                mem = await bot.get_chat_member(f"@{ch.strip()}", m.from_user.id)
                if mem.status not in ["member", "administrator", "creator"]:
                    must_join = True; break
            except: pass

    if must_join:
        kb = []
        if s['fsub_link']: kb.append([InlineKeyboardButton(text="🔗 JOIN CHANNEL", url=s['fsub_link'])])
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
        else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])

@dp.callback_query(F.data == "mem_don")
async def mem_don_cb(c: CallbackQuery):
    await c.message.answer("🎁 Silakan kirim media donasi kamu langsung ke chat ini.")
    await c.answer()

@dp.callback_query(F.data.startswith("retry_"))
async def retry_cb(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    await c.message.delete()
    await start_handler(c.message, code_override=code)

# ================= RUN =================
async def main():
    await init_db()
    
    # Menu Member (Tanpa /settings)
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin")
    ], scope=BotCommandScopeDefault())
    
    # Menu Admin (Ada /settings)
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="settings", description="Panel Admin"),
        BotCommand(command="stats", description="Cek Statistik")
    ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
