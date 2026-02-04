import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler # Install: pip install apscheduler

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatPermissions
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ================= KONFIG AMAN =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
BOT_USERNAME = os.getenv("BOT_USERNAME")
EXEMPT_USERNAME = os.getenv("EXEMPT_USERNAME")

KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= STATE UNTUK POSTING =================
class PostDonasi(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE & MENU INIT =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def set_commands():
    commands = [
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin (Sambat)"),
        BotCommand(command="donasi", description="Kirim Konten/Donasi"),
        BotCommand(command="stats", description="Cek Statistik (Admin)")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

# ================= 1. FITUR AUTO BACKUP (SCHEDULER) =================
async def auto_backup_db():
    if os.path.exists(DB_NAME):
        file_db = FSInputFile(DB_NAME, filename=f"backup_{datetime.now().strftime('%Y%m%d')}.db")
        await bot.send_document(ADMIN_ID, file_db, caption=f"🔄 **AUTO BACKUP DB**\nTanggal: {datetime.now().strftime('%d-%m-%Y')}")

# ================= HELPER =================
async def check_membership(user_id: int):
    results = []
    for chat in [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]:
        target = chat if chat.startswith("@") else f"@{chat}"
        try:
            m = await bot.get_chat_member(target, user_id)
            results.append(m.status in ("member", "administrator", "creator"))
        except Exception:
            results.append(False)
    return results

def join_keyboard(code: str, status: list):
    buttons = []
    names = ["📢 JOIN CHANNEL 1", "📢 JOIN CHANNEL 2", "👥 JOIN GRUP"]
    links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
    for i in range(3):
        if not status[i]:
            clean_link = links[i].replace("@", "")
            buttons.append([InlineKeyboardButton(text=names[i], url=f"https://t.me/{clean_link}")])
    buttons.append([InlineKeyboardButton(text="🔄 UPDATE / COBA LAGI", callback_data=f"retry:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_approval_kb(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ POST", callback_data=f"approve_post:{user_id}"),
            InlineKeyboardButton(text="❌ REJECT", callback_data=f"reject_post:{user_id}")
        ]
    ])

# ================= 2. HANDLER ADMIN & POSTING =================

@dp.callback_query(F.data.startswith("reject_post:"), F.from_user.id == ADMIN_ID)
async def reject_donasi(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Konten ditolak & dihapus.", show_alert=True)

@dp.callback_query(F.data.startswith("approve_post:"), F.from_user.id == ADMIN_ID)
async def approve_donasi(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(PostDonasi.waiting_for_title)
    await callback.message.answer("Sip! Sekarang kirim **JUDUL** buat postingan ini:")
    await callback.answer()

@dp.message(PostDonasi.waiting_for_title, F.from_user.id == ADMIN_ID)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(PostDonasi.waiting_for_photo)
    await message.answer("Oke, sekarang kirim **FOTO COVER** untuk link ini:")

@dp.message(PostDonasi.waiting_for_photo, F.from_user.id == ADMIN_ID, F.photo)
async def process_final_post(message: Message, state: FSMContext):
    data = await state.get_data()
    title = data['title']
    cover_photo = message.photo[-1].file_id
    code = uuid.uuid4().hex[:8]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?, ?, ?, ?)", (code, cover_photo, "photo", title))
        await db.commit()
    
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    caption_post = f"🔥 **{title}**\n\n🔗 Link: `{link}`"
    
    await bot.send_photo(ADMIN_ID, cover_photo, caption=caption_post, parse_mode="Markdown")
    await message.answer("✅ Postingan siap! Silahkan copy text di atas.")
    await state.clear()

# ================= 3. FITUR AUTO-MUTE (DI GRUP) =================

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def filter_kata_grup(message: Message):
    current_username = message.from_user.username
    if message.from_user.id == ADMIN_ID or (current_username and current_username.lower() == EXEMPT_USERNAME.lower()):
        return
        
    if any(kata in message.text.lower() for kata in KATA_KOTOR):
        try:
            await message.delete()
            # Mute user selama 24 jam
            until_date = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await message.answer(f"🚫 {message.from_user.mention_html()} DI-MUTE 24 JAM karena ngetik kata terlarang!", parse_mode="HTML")
            
            # FITUR LOGS: Kirim ke Admin
            await bot.send_message(ADMIN_ID, f"📢 **LOG MUTE**\nUser: {message.from_user.full_name}\nID: `{message.from_user.id}`\nKata: {message.text}")
        except Exception: pass

# ================= 4. FITUR LOGS (NOTIF START) =================

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        # LOGS: Notif user baru buka bot
        await bot.send_message(ADMIN_ID, f"👤 **USER AKTIF**\nNama: {message.from_user.full_name}\nID: `{message.from_user.id}`")
        await message.answer("👋 aloo sayang ketik / buat lihat daftar fitur.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

# ================= HANDLER UMUM LAINNYA =================

@dp.message(Command("donasi"))
async def donasi_start(message: Message):
    await message.answer("🙏 maaciw donasinya.\n\n**Silahkan kirim video/foto.**\nOtomatis akan diteruskan ke Admin untuk direview.")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document))
async def handle_donasi_upload(message: Message):
    if message.from_user.id == ADMIN_ID: return
    user_info = f"🎁 **DONASI/KONTEN ANYAR**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    try:
        await bot.send_message(ADMIN_ID, user_info, parse_mode="Markdown")
        await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        await bot.send_message(ADMIN_ID, "Mau diposting konten di atas?", reply_markup=admin_approval_kb(message.from_user.id))
        await message.reply("✅ File udah dikirim ke admin thanks!.")
    except Exception: pass

async def send_media(chat_id: int, user_id: int, code: str):
    status = await check_membership(user_id)
    if not all(status):
        await bot.send_message(chat_id, "🚫 harus join semua jika udah klik cobalagi!", reply_markup=join_keyboard(code, status))
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cursor: row = await cursor.fetchone()
    if not row: return await bot.send_message(chat_id, "❌ Link mati atau salah.")
    if row[1] == "photo": await bot.send_photo(chat_id, row[0], caption=row[2], protect_content=True)
    else: await bot.send_video(chat_id, row[0], caption=row[2], protect_content=True)

# ================= SYSTEM & POLLING =================

async def main():
    await init_db()
    await set_commands()
    
    # Setup Scheduler untuk Backup DB setiap jam 00:00
    scheduler.add_job(auto_backup_db, 'cron', hour=0, minute=0)
    scheduler.start()
    
    print("Bot is Running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
