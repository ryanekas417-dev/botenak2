import asyncio, os, aiosqlite, traceback, random, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, CallbackQuery, ChatMemberUpdated)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ISI_TOKEN_DISINI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 
BOT_USN = os.getenv("BOT_USERNAME", "UsernameBot").replace("@", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    set_val = State()

def gen_code():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=30))

# ================= DATABASE & SETTINGS =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT, bk_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, name TEXT)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, 
            btn_nonton TEXT, fsub_list TEXT, fsub_link TEXT, 
            db_ch_id TEXT, post_ch_id TEXT, log_id TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_nonton, fsub_list, fsub_link, db_ch_id, post_ch_id, log_id) 
            VALUES (1, 'Halo! Selamat datang', 'Wajib join channel di bawah!', '🎬 NONTON', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= LOGIKA MEMBER (START & FSUB) =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    # Deteksi kode dari link t.me/bot?start=KODE
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    # 1. Cek Force Join
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
        # Gunakan arg agar tombol Coba Lagi tahu media mana yang diminta
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}" if arg else "check_sub")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    # 2. Kirim Media jika ada Argumen (Ingatan DB)
    if arg:
        async with aiosqlite.connect("master.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
        
        if row:
            try:
                if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
                else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
            except:
                await m.answer("❌ Media gagal dikirim. Mungkin file telah dihapus dari DB Channel.")
        else:
            await m.answer("❌ Maaf, konten tidak ditemukan dalam ingatan saya.")
    else:
        # Tampilan Start Biasa
        await m.answer(s['start_txt'])

@dp.callback_query(F.data.startswith("retry_"))
async def retry_callback(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    if code == "None": code = None
    await c.message.delete()
    # Panggil ulang fungsi start dengan kode yang sama
    await start_handler(c.message, code_override=code)
    await c.answer()

# ================= ADMIN: AUTO POST SYSTEM =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), F.from_user.id == ADMIN_ID)
async def admin_upload(m: Message, state: FSMContext):
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(BotState.wait_title)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="exit_state")]])
    await m.answer("🏷️ **JUDUL:**\nKetik judul untuk konten ini:", reply_markup=kb)

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="exit_state")]])
    await m.answer("📸 **COVER:**\nKirim foto cover untuk dipost di channel:", reply_markup=kb)

@dp.message(BotState.wait_cover, F.photo)
async def finalize_auto_post(m: Message, state: FSMContext):
    data = await state.get_data()
    s = await get_conf()
    code = gen_code()
    
    if not s['db_ch_id'] or not s['post_ch_id']:
        await state.clear()
        return await m.answer("❌ Error: ID Channel DB atau Post belum di-set di /settings!")

    try:
        # 1. Simpan/Backup ke DB Channel (Ingatan Abadi)
        bk = await bot.send_photo(
            s['db_ch_id'], 
            data['fid'] if data['mtype'] == "photo" else data['fid'], 
            caption=f"📝 **DATABASE BACKUP**\nCODE: `{code}`\nTITLE: {data['title']}"
        )
        
        # 2. Simpan ke Database Lokal
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", 
                           (code, data['fid'], data['mtype'], data['title'], str(bk.message_id)))
            await db.commit()

        # 3. Auto Post ke Channel Utama dengan Tombol Nonton
        link_nonton = f"https://t.me/{BOT_USN}?start={code}"
        kb_post = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link_nonton)]])
        
        await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb_post)
        await m.answer(f"✅ **BERHASIL DIPOST!**\n\nKode: `{code}`\nLink: {link_nonton}")
        
    except Exception as e:
        await m.answer(f"❌ Terjadi kesalahan: {e}")
    finally:
        await state.clear()

# ================= ADMIN SETTINGS =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def admin_settings(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ID Channel Post", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="ID Channel DB", callback_data="conf_db_ch_id")],
        [InlineKeyboardButton(text="Username FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="Teks Tombol Nonton", callback_data="conf_btn_nonton")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="exit_state")]
    ])
    await m.answer("⚙️ **PANEL SETTINGS ADMIN**", reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def edit_config(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("conf_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    await c.message.edit_text(f"Kirim nilai baru untuk `{field}`:", 
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="exit_state")]]))

@dp.message(BotState.set_val)
async def save_config(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ `{data['field']}` berhasil diperbarui.")
    await state.clear()

@dp.callback_query(F.data == "exit_state")
async def exit_handler(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.delete()
    await c.answer("Dibatalkan.")

# ================= RUN BOT =================
async def main():
    await init_db()
    # Setting CMD: Member hanya lihat /start
    await bot.set_my_commands([BotCommand(command="start", description="Mulai Bot")], scope=BotCommandScopeDefault())
    # Setting CMD: Admin lihat menu lengkap
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="settings", description="Pengaturan Bot")
    ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
