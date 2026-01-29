import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest

# ================= KONFIG AMAN =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
BOT_USERNAME = os.getenv("BOT_USERNAME")

KATA_KOTOR = ["open bo", "promosi", "bio", "slot gacor", "vcs"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

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
        BotCommand(command="donasi", description="Kirim Konten/Donasi")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

# ================= HELPER =================
async def check_membership(user_id: int):
    results = []
    # Priksa username diawali @ opo ora
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

# ================= 1. HANDLER KHUSUS ADMIN =================

@dp.message(F.from_user.id == ADMIN_ID, (F.photo | F.video), F.chat.type == "private")
async def admin_upload(message: Message):
    if message.caption and message.caption.startswith("/all"):
        return # Skip nek iki broadcast
    code = uuid.uuid4().hex[:8]
    f_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_t = "photo" if message.photo else "video"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)", (code, f_id, m_t, message.caption or ""))
        await db.commit()
    await message.reply(f"🔗 Link: `https://t.me/{BOT_USERNAME}?start={code}`", parse_mode="Markdown")

# FIX: BROADCAST SUPPORT FOTO/VIDEO
@dp.message(Command("all"), F.from_user.id == ADMIN_ID)
@dp.message(F.from_user.id == ADMIN_ID, F.caption.startswith("/all"))
async def broadcast_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
    
    count = 0
    for row in rows:
        try:
            # Ngirim duplikat pesen admin (iso teks/foto/video)
            await bot.copy_message(chat_id=row[0], from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05) 
        except Exception:
            pass
    await message.reply(f"✅ Berhasil kirim neng {count} member.")

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db_handler(message: Message):
    if os.path.exists(DB_NAME):
        file_db = FSInputFile(DB_NAME, filename="media.db")
        await bot.send_document(message.chat.id, file_db, caption="Iki db terbarumu su.")
    else:
        await message.reply("DB ora ketemu!")

# ================= 2. HANDLER USER & CALLBACK =================

# FIX: HANDLER COBA LAGI (RETRY)
@dp.callback_query(F.data.startswith("retry:"))
async def retry_callback(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    status = await check_membership(callback.from_user.id)
    
    if all(status):
        await callback.message.delete()
        await send_media(callback.message.chat.id, callback.from_user.id, code)
    else:
        await callback.answer("⚠️ join dulu ke semuanya ini!", show_alert=True)

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        await message.answer("👋 aloo sayang ketik / buat lihat daftar fitur.\nJoin dulu buat akses konten.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply("⚠️ Cara: `/ask pesan` ")
    
    pesan_user = args[1]
    user_info = f"📩 **PESAN ANYAR (ASK)**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    await bot.send_message(ADMIN_ID, f"{user_info}\n\n💬 Pesan: {pesan_user}", parse_mode="Markdown")
    await message.reply("✅ Pesanmu udah dikirim ke admin.")

@dp.message(Command("donasi"))
async def donasi_start(message: Message):
    await message.answer("🙏 maaciw donasinya.\n\n**Silahkan kirim video/foto serta caption.**")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document))
async def handle_donasi_upload(message: Message):
    if message.from_user.id == ADMIN_ID: return
    user_info = f"🎁 **DONASI ANYAR**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    await bot.send_message(ADMIN_ID, user_info, parse_mode="Markdown")
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await message.reply("✅ File udah dikirim ke admin.")

# ================= 3. SYSTEM & SEND MEDIA =================

async def send_media(chat_id: int, user_id: int, code: str):
    status = await check_membership(user_id)
    if not all(status):
        await bot.send_message(chat_id, "🚫 Join semuanya dulu sayang kalo udah klik COBA LAGI!", reply_markup=join_keyboard(code, status))
        return
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cursor: 
            row = await cursor.fetchone()
    
    if not row: 
        return await bot.send_message(chat_id, "❌ Link mati atau salah.")
    
    if row[1] == "photo":
        await bot.send_photo(chat_id, row[0], caption=row[2], protect_content=True)
    else:
        await bot.send_video(chat_id, row[0], caption=row[2], protect_content=True)

# ================= 3. HANDLER GRUP (FIXED) =================

# Iki nggo nangkep wong anyar mlebu
@dp.message(F.chat.type.in_({"group", "supergroup"}), F.new_chat_members)
async def welcome_grup(message: Message):
    for member in message.new_chat_members:
        await message.answer(f"Selamat datang {member.mention_html()}, ramein grupnya, BEBAS TAPI SOPAN SU!", parse_mode="HTML")

# Iki sing luwih akurat nggo nangkep wong metu/metu paksa
@dp.chat_member()
async def on_user_leave(event: types.ChatMemberUpdated):
    # Cek nek statuse saiki dadi 'left' utawa 'kicked'
    if event.new_chat_member.status in ["left", "kicked"]:
        user = event.new_chat_member.user
        await bot.send_message(
            event.chat.id, 
            f"KONTOL NI {user.mention_html()} MALAH OUT CUIH!", 
            parse_mode="HTML"
        )

# ================= SYSTEM & POLLING (FIXED) =================

# ... bagean send_media tetep podo ...

async def main():
    await init_db()
    await set_commands()
    print("Bot is Running...")
    
    # PENTING: Kudu nambahne allowed_updates=["message", "chat_member", "callback_query"]
    # Supaya bot gelem ngrungokake wong mlebu/metu grup (chat_member)
    await dp.start_polling(bot, allowed_updates=["message", "chat_member", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
