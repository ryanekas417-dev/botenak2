import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command

# ================= KONFIG (ENV VARIABLES) =================
# Di Railway, isi bagian Variables sesuai nama di bawah ini
BOT_TOKEN = os.getenv("BOT_TOKEN",)
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME",)
ADMIN_ID = int(os.getenv("ADMIN_ID",))
BOT_USERNAME = os.getenv("BOT_USERNAME",)

# ================= PATH DB =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ================= DATABASE INIT =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Tabel Media
        await db.execute("""
        CREATE TABLE IF NOT EXISTS media (
            code TEXT PRIMARY KEY,
            file_id TEXT,
            type TEXT,
            caption TEXT
        )
        """)
        # Tabel Users (Untuk fitur broadcast /all)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
        """)
        await db.commit()

# ================= HELPER FUNCTIONS =================
async def is_member(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

def join_keyboard(code: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry:{code}")]
        ]
    )

# ================= USER HANDLERS =================

@dp.message(CommandStart())
async def start_handler(message: Message):
    # Simpan user ke DB agar bisa di-broadcast (/all)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    if len(args) == 1:
        await message.answer("👋 Halo! Kirim link untuk mengakses media.\n\nGunakan `/ask pesan kamu` untuk bertanya ke admin.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    msg_text = message.text.replace("/ask", "").strip()
    if not msg_text:
        await message.reply("❌ Format salah. Contoh: `/ask min link ini mati`")
        return
    
    # Kirim ke Admin
    admin_text = (f"📩 **PESAN MASUK**\n\n"
                  f"Dari: {message.from_user.full_name}\n"
                  f"ID: `{message.from_user.id}`\n"
                  f"Pesan: {msg_text}")
    
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    await message.reply("✅ Pesan kamu sudah terkirim ke admin.")

# ================= ADMIN HANDLERS =================

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db_handler(message: Message):
    if os.path.exists(DB_NAME):
        await message.answer_document(FSInputFile(DB_NAME), caption="📦 Backup Database")
    else:
        await message.answer("❌ DB tidak ditemukan.")

@dp.message(Command("all"), F.from_user.id == ADMIN_ID)
async def broadcast_handler(message: Message):
    msg_text = message.text.replace("/all", "").strip()
    if not msg_text:
        await message.reply("❌ Format salah. Contoh: `/all Halo semuanya`")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
    
    count = 0
    for row in rows:
        try:
            await bot.send_message(row[0], msg_text)
            count += 1
            await asyncio.sleep(0.05) # Jeda dikit biar gak kena spam limit
        except:
            continue
    
    await message.answer(f"✅ Pesan dikirim ke {count} orang.")

@dp.message(F.from_user.id == ADMIN_ID, (F.photo | F.video))
async def admin_upload(message: Message):
    code = uuid.uuid4().hex[:8]
    caption = message.caption or ""

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    else:
        file_id = message.video.file_id
        media_type = "video"

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO media (code, file_id, type, caption) VALUES (?, ?, ?, ?)",
            (code, file_id, media_type, caption)
        )
        await db.commit()

    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    await message.reply(f"✅ Media tersimpan\n🔗 Link:\n{link}")

# ================= SYSTEM HANDLERS =================

@dp.callback_query(F.data.startswith("retry:"))
async def retry_handler(callback):
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    await send_media(callback.message.chat.id, callback.from_user.id, code)

async def send_media(chat_id: int, user_id: int, code: str):
    if not await is_member(user_id):
        await bot.send_message(chat_id, "🚫 Kamu wajib join channel dulu.", reply_markup=join_keyboard(code))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cursor:
            row = await cursor.fetchone()

    if not row:
        await bot.send_message(chat_id, "❌ Link tidak valid.")
        return

    file_id, media_type, caption = row
    caption = caption or ""

    if media_type == "photo":
        await bot.send_photo(chat_id, file_id, caption=caption, protect_content=True)
    else:
        await bot.send_video(chat_id, file_id, caption=caption, protect_content=True)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
