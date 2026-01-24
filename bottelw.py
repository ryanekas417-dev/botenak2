import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command

# ================= KONFIG AMAN (DARI RAILWAY) =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CH1_USERNAME = os.getenv("CH1_USERNAME") # Channel 1
CH2_USERNAME = os.getenv("CH2_USERNAME") # Channel 2
GROUP_USERNAME = os.getenv("GROUP_USERNAME") # Grup
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
BOT_USERNAME = os.getenv("BOT_USERNAME")

# ================= PATH DB =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ================= DATABASE INIT =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS media (
            code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT
        )
        """)
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

# ================= HELPER FUNCTIONS =================
async def is_member(user_id: int) -> bool:
    try:
        # Cek kabeh: Channel 1, Channel 2, lan Grup
        m1 = await bot.get_chat_member(CH1_USERNAME, user_id)
        m2 = await bot.get_chat_member(CH2_USERNAME, user_id)
        m3 = await bot.get_chat_member(GROUP_USERNAME, user_id)
        
        allowed = ("member", "administrator", "creator")
        return m1.status in allowed and m2.status in allowed and m3.status in allowed
    except:
        return False

def join_keyboard(code: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 CHANNEL 1", url=f"https://t.me/{CH1_USERNAME[1:]}")],
        [InlineKeyboardButton(text="📢 CHANNEL 2", url=f"https://t.me/{CH2_USERNAME[1:]}")],
        [InlineKeyboardButton(text="👥 GRUP DISKUSI", url=f"https://t.me/{GROUP_USERNAME[1:]}")],
        [InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry:{code}")]
    ])

# ================= USER HANDLERS =================
@dp.message(CommandStart())
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    if len(args) == 1:
        await message.answer("👋 Halo! Join kabeh channel dhisik nggo ngakses media.\n\nGunakan `/ask [pesan]` nggo takon admin.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    msg_text = message.text.replace("/ask", "").strip()
    if not msg_text:
        await message.reply("❌ Format salah. Contoh: `/ask min link mati`")
        return
    
    admin_text = (f"📩 **PESAN BARU**\nUser: {message.from_user.full_name}\nID: `{message.from_user.id}`\n\nPesan: {msg_text}")
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    await message.reply("✅ Pesan terkirim ke admin.")

# ================= ADMIN HANDLERS =================
@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def reply_handler(message: Message):
    orig_msg = message.reply_to_message.text or message.reply_to_message.caption
    if orig_msg and "ID:" in orig_msg:
        try:
            target_user_id = int(orig_msg.split("ID:")[1].split("\n")[0].strip())
            await bot.send_message(target_user_id, f"💬 **Balasan Admin:**\n\n{message.text}")
            await message.reply("✅ Berhasil dibalas.")
        except:
            await message.reply("❌ Gagal balas, ID ora ketemu.")

@dp.message(Command("all"), F.from_user.id == ADMIN_ID)
async def broadcast_handler(message: Message):
    # Support Foto/Video/Text
    target_msg = message.reply_to_message if message.reply_to_message else message
    msg_cap = target_msg.caption or target_msg.text or ""
    msg_cap = msg_cap.replace("/all", "").strip()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
    
    await message.answer(f"🚀 Memulai broadcast ke {len(rows)} user...")
    success, block = 0, 0
    
    for row in rows:
        try:
            if target_msg.photo:
                await bot.send_photo(row[0], target_msg.photo[-1].file_id, caption=msg_cap)
            elif target_msg.video:
                await bot.send_video(row[0], target_msg.video.file_id, caption=msg_cap)
            else:
                if not msg_cap: continue
                await bot.send_message(row[0], msg_cap)
            
            success += 1
            await asyncio.sleep(0.3) # DELAY ANTI-SPAM
        except Exception as e:
            if "forbidden" in str(e).lower(): block += 1
            continue
            
    await message.answer(f"✅ Broadcast rampung!\nBerhasil: {success}\nBlocked: {block}")

@dp.message(F.from_user.id == ADMIN_ID, (F.photo | F.video))
async def admin_upload(message: Message):
    code = uuid.uuid4().hex[:8]
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_type = "photo" if message.photo else "video"
    caption = message.caption or ""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)", (code, file_id, m_type, caption))
        await db.commit()
    await message.reply(f"✅ Tersimpan!\n🔗 Link: `https://t.me/{BOT_USERNAME}?start={code}`", parse_mode="Markdown")

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db_handler(message: Message):
    if os.path.exists(DB_NAME):
        await message.answer_document(FSInputFile(DB_NAME), caption="📦 Backup DB")
    else:
        await message.answer("❌ DB Kosong.")

# ================= SYSTEM =================
@dp.callback_query(F.data.startswith("retry:"))
async def retry_handler(callback):
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    await send_media(callback.message.chat.id, callback.from_user.id, code)

async def send_media(chat_id: int, user_id: int, code: str):
    if not await is_member(user_id):
        await bot.send_message(chat_id, "🚫 harus join dulu channel & grup syg kalo udah cobalagi!", reply_markup=join_keyboard(code))
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cursor:
            row = await cursor.fetchone()
    if not row: return await bot.send_message(chat_id, "❌ Link salah.")
    f_id, m_type, cap = row
    if m_type == "photo": await bot.send_photo(chat_id, f_id, caption=cap, protect_content=True)
    else: await bot.send_video(chat_id, f_id, caption=cap, protect_content=True)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":

    asyncio.run(main())
