import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatMemberUpdated
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
    if message.caption and message.caption.startswith("/all"): return
    code = uuid.uuid4().hex[:8]
    f_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_t = "photo" if message.photo else "video"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)", (code, f_id, m_t, message.caption or ""))
        await db.commit()
    await message.reply(f"🔗 Link: `https://t.me/{BOT_USERNAME}?start={code}`", parse_mode="Markdown")

@dp.message(Command("all"), F.from_user.id == ADMIN_ID)
@dp.message(F.from_user.id == ADMIN_ID, F.caption.startswith("/all"))
async def broadcast_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor: rows = await cursor.fetchall()
    count = 0
    for row in rows:
        try:
            await bot.copy_message(chat_id=row[0], from_chat_id=message.chat.id, message_id=message.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await message.reply(f"✅ Berhasil kirim neng {count} member.")

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db_handler(message: Message):
    if os.path.exists(DB_NAME):
        file_db = FSInputFile(DB_NAME, filename="media.db")
        await bot.send_document(message.chat.id, file_db, caption="Iki db terbarumu su.")
    else:
        await message.reply("DB ora ketemu!")

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def stats_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await message.answer(f"📊 Stats:\nUsers: {u[0]}\nMedia: {m[0]}")

@dp.message(F.chat.type == "private", F.from_user.id == ADMIN_ID, F.reply_to_message)
async def reply_admin_handler(message: Message):
    reply_text = message.reply_to_message.text or message.reply_to_message.caption
    if reply_text and "🆔 ID:" in reply_text:
        try:
            target_id = int(reply_text.split("🆔 ID:")[1].strip().split("\n")[0].replace("`", ""))
            await bot.copy_message(target_id, message.chat.id, message.message_id)
            await message.reply(f"✅ Pesan dikirim neng user `{target_id}`")
        except Exception as e:
            await message.reply(f"❌ Gagal kirim: {e}")

# ================= 2. HANDLER GRUP (FILTER ONLY) =================

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def filter_kata_grup(message: Message):
    if any(kata in message.text.lower() for kata in KATA_KOTOR):
        try:
            await message.delete()
            await message.answer(f"TOLOL {message.from_user.mention_html()} GABOLEH NGETIK ITU DISINI, SEKALI LAGI GW MUTE!", parse_mode="HTML")
        except Exception: pass

# ================= 3. HANDLER USER & FITUR UMUM =================

@dp.callback_query(F.data.startswith("retry:"))
async def retry_callback(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    status = await check_membership(callback.from_user.id)
    if all(status):
        await callback.message.delete()
        await send_media(callback.message.chat.id, callback.from_user.id, code)
    else:
        await callback.answer("⚠️ kamu blom join semua!", show_alert=True)

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    args = message.text.split(" ", 1)
    if len(args) == 1:
        await message.answer("👋 aloo sayang ketik / buat lihat daftar fitur.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await message.reply("⚠️ Cara: `/ask pesan` ")
    user_info = f"📩 **PESAN ANYAR (ASK)**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    await bot.send_message(ADMIN_ID, f"{user_info}\n\n💬 Pesan: {args[1]}", parse_mode="Markdown")
    await message.reply("✅ Pesanmu udah dikirim ke admin.")

@dp.message(Command("donasi"))
async def donasi_start(message: Message):
    await message.answer("🙏 maaciw donasinya.\n\n**Silahkan kirim video/foto serta caption.**\nOtomatis akan diteruskan ke Admin.")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document))
async def handle_donasi_upload(message: Message):
    if message.from_user.id == ADMIN_ID: return
    user_info = f"🎁 **DONASI/KONTEN ANYAR**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    try:
        await bot.send_message(ADMIN_ID, user_info, parse_mode="Markdown")
        await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        await message.reply("✅ File udah dikirim ke admin thanks!.")
    except Exception: pass

# ================= SYSTEM & POLLING =================

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

async def main():
    await init_db()
    await set_commands()
    print("Bot is Running...")
    await dp.start_polling(bot, allowed_updates=["message", "chat_member", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
