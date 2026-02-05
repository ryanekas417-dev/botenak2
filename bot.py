import asyncio, os, aiosqlite, traceback, random, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatMemberUpdated, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ================= CONFIG (WAJIB ISI) =================
BOT_TOKEN = "TOKEN_BOT_KAMU"
ADMIN_ID = 123456789  # ID Telegram kamu
BOT_USN = "UsernameBotTanpaAt"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Kata terlarang untuk filter grup
KATA_TERLARANG = ["biyo", "promosi", "biyoh", "bio", "open bo"]

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    wait_ask = State()
    wait_broadcast = State()
    set_val = State()

def gen_code():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

# ================= DATABASE SYSTEM =================
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
            VALUES (1, 'Halo Selamat datang', 'Silakan Join Channel Kami', '🎬 NONTON', '🎁 DONASI', '💬 TANYA ADMIN', '', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= 1. KEAMANAN & FILTER GRUP =================
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_filter(m: Message):
    if not m.text: return
    s = await get_conf()
    exempt = [str(ADMIN_ID)] + (s['exempt_usn'].lower().replace("@","").split(",") if s['exempt_usn'] else [])
    user_ref = str(m.from_user.id) if not m.from_user.username else m.from_user.username.lower()

    if user_ref in exempt: return

    if any(word in m.text.lower() for word in KATA_TERLARANG):
        try:
            await m.delete()
            await bot.restrict_chat_member(
                m.chat.id, m.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(hours=24)
            )
            await m.answer(f"🔇 {m.from_user.first_name} di-mute 24 jam karena kata terlarang.")
        except: pass

# ================= 2. LOG JOIN/LEFT =================
@dp.chat_member()
async def member_update_handler(update: ChatMemberUpdated):
    s = await get_conf()
    if not s['log_id']: return
    user = update.from_user
    if update.new_chat_member.status == "member":
        txt = f"🆕 **MEMBER JOIN**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 {update.chat.title}"
    elif update.new_chat_member.status in ["left", "kicked"]:
        txt = f"🚪 **MEMBER KELUAR**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 {update.chat.title}"
    else: return
    try: await bot.send_message(s['log_id'], txt)
    except: pass

# ================= 3. ADMIN DASHBOARD (/settings) =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def admin_dashboard(m: Message):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="📢 Teks FSub", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="🔗 Link FSub/Addlist", callback_data="conf_fsub_link"), InlineKeyboardButton(text="👥 List Username FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="📁 ID CH DB", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="📣 ID CH Post", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="📜 ID Log", callback_data="conf_log_id"), InlineKeyboardButton(text="🛡️ Exempt", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="adm_stats"), InlineKeyboardButton(text="💾 Backup .db", callback_data="adm_dbfile")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="adm_close")]
    ])
    await m.answer("⚙️ **DASHBOARD ADMIN**\nGunakan tombol untuk mengatur bot.", reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def config_trigger(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("conf_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    await c.message.edit_text(f"Kirimkan nilai baru untuk `{field}`:\n(Untuk ID Channel awali dengan -100)")

@dp.message(BotState.set_val)
async def config_saver(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ Berhasil mengupdate `{data['field']}`.")
    await state.clear()

# ================= 4. DATABASE & AUTO UPLOAD =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def auto_upload_handler(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        # Donasi System
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}")]])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"🎁 Donasi dari: {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("✅ Donasi kamu terkirim ke admin untuk di-review.")

    # Admin Upload
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else ("video" if m.video else "doc")
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(BotState.wait_title)
    await m.answer("🏷️ Judul kontennya apa?")

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("📸 Kirimkan Foto Cover/Poster:")

@dp.message(BotState.wait_cover, F.photo)
async def finalize_upload(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code = gen_code()
        
        # Backup to DB Channel
        bk_id = ""
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, caption=f"KODE: `{code}`\nJUDUL: {data['title']}")
            bk_id = str(bk.message_id)
        
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['mtype'], data['title'], bk_id))
            await db.commit()

        # Post to Channel
        if s['post_ch_id']:
            link = f"https://t.me/{BOT_USN}?start={code}"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
        
        await m.answer(f"✅ PUBLISHED!\nLink: `https://t.me/{BOT_USN}?start={code}`")
    except Exception as e:
        await m.answer(f"❌ Error: {e}")
    finally: await state.clear()

# ================= 5. MEMBER INTERACTION (START, ASK, DONASI) =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    # Simpan user ke db stats
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (m.from_user.id, m.from_user.full_name))
        await db.commit()

    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_donasi"), InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Force Join Check
    must_join = []
    if s['fsub_list']:
        for ch in s['fsub_list'].replace("@","").split(","):
            if not ch.strip(): continue
            try:
                mem = await bot.get_chat_member(f"@{ch.strip()}", m.from_user.id)
                if mem.status not in ["member", "administrator", "creator"]:
                    must_join.append(ch.strip())
            except: pass

    if must_join:
        kb = []
        if s['fsub_link']: kb.append([InlineKeyboardButton(text="🔗 JOIN CHANNEL", url=s['fsub_link'])])
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    # Ambil Media
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
        elif row['mtype'] == "video": await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
        else: await bot.send_document(m.chat.id, row['fid'], caption=row['title'])
    else:
        await m.answer("❌ Konten tidak ditemukan.")

@dp.callback_query(F.data.startswith("retry_"))
async def retry_handler(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    await c.message.delete()
    await start_handler(c.message, code_override=code)

@dp.callback_query(F.data == "mem_ask")
async def ask_admin(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_ask)
    await c.message.answer("💬 Silakan kirim pesan/pertanyaan kamu untuk admin:")

@dp.message(BotState.wait_ask)
async def process_ask(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📩 **PESAN ASK**\nDari: {m.from_user.full_name} (`{m.from_user.id}`)\n\n{m.text}")
    await m.answer("✅ Pesan terkirim ke admin.")
    await state.clear()

@dp.callback_query(F.data == "mem_donasi")
async def donasi_button(c: CallbackQuery):
    await c.message.answer("🎁 Silakan kirim Foto/Video yang ingin didonasi (Kirim medianya langsung):")

# ================= 6. BROADCAST & STATS =================
@dp.callback_query(F.data == "adm_stats")
async def show_stats(c: CallbackQuery):
    async with aiosqlite.connect("master.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await c.answer(f"📊 User: {u[0]} | Media: {m[0]}", show_alert=True)

@dp.callback_query(F.data == "adm_dbfile")
async def send_db_file(c: CallbackQuery):
    await c.message.answer_document(FSInputFile("master.db"), caption="Backup Database")

@dp.callback_query(F.data == "adm_close")
async def close_cb(c: CallbackQuery): await c.message.delete()

# ================= BROADCAST =================
@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def bc_start(m: Message, state: FSMContext):
    await state.set_state(BotState.wait_broadcast)
    await m.answer("Kirim pesan yang ingin di broadcast (Teks/Foto/Video):")

@dp.message(BotState.wait_broadcast)
async def bc_process(m: Message, state: FSMContext):
    async with aiosqlite.connect("master.db") as db:
        async with db.execute("SELECT uid FROM users") as cur: users = await cur.fetchall()
    
    count = 0
    for u in users:
        try:
            await bot.copy_message(u[0], m.chat.id, m.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await m.answer(f"✅ Broadcast selesai ke {count} user.")
    await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin"),
        BotCommand(command="donasi", description="Kirim Donasi"),
        BotCommand(command="settings", description="Menu Admin"),
        BotCommand(command="broadcast", description="Broadcast Pesan"),
        BotCommand(command="stats", description="Cek Statistik"),
        BotCommand(command="senddb", description="Backup Database")
    ], scope=BotCommandScopeDefault())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass
