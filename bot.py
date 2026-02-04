import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, CallbackQuery, ChatMemberUpdated
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME") # Target Auto-Post sekarang ke sini
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")

raw_log_id = os.getenv("LOG_GROUP_ID", "").replace("@", "")
if raw_log_id.replace("-", "").isdigit():
    LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))
else:
    LOG_GROUP_ID = ADMIN_ID

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

# ================= LOG MEMBER JOIN/LEFT =================

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    user = event.new_chat_member.user
    text = (
        f"✅ **MEMBER BERGABUNG**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Nama: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🔗 Username: @{user.username if user.username else '-'}\n"
        f"🌐 Chat: {event.chat.title}"
    )
    await bot.send_message(LOG_GROUP_ID, text, parse_mode="Markdown")

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEFT))
async def on_user_left(event: ChatMemberUpdated):
    user = event.old_chat_member.user
    text = (
        f"❌ **MEMBER KELUAR**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Nama: {user.full_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"🔗 Username: @{user.username if user.username else '-'}\n"
        f"🌐 Chat: {event.chat.title}"
    )
    await bot.send_message(LOG_GROUP_ID, text, parse_mode="Markdown")

# ================= HELPERS =================
async def check_membership(user_id: int):
    results = []
    for chat in [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]:
        if not chat: continue
        target = chat if chat.startswith("@") else f"@{chat}"
        try:
            m = await bot.get_chat_member(target, user_id)
            results.append(m.status in ("member", "administrator", "creator"))
        except: results.append(False)
    return results

# ================= HANDLERS ADMIN =================

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def send_db(message: Message):
    if os.path.exists(DB_NAME):
        await message.reply_document(FSInputFile(DB_NAME), caption="Backup database.")
    else:
        await message.reply("DB Kosong.")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def admin_or_user_upload(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        fid = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else message.document.file_id)
        mtype = "photo" if message.photo else "video"
        await state.update_data(temp_fid=fid, temp_type=mtype)
        await state.set_state(PostMedia.waiting_for_title)
        return await message.reply("📝 **MODE POSTING**\nMasukkan **JUDUL** konten:")

    await bot.send_message(LOG_GROUP_ID, f"🎁 **DONASI MASUK**\nDari: {message.from_user.full_name}")
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ POST KE CH", callback_data=f"app_donasi"),
        InlineKeyboardButton(text="❌ REJECT", callback_data="reject")
    ]])
    await bot.send_message(ADMIN_ID, f"Review donasi dari {message.from_user.full_name}:", reply_markup=kb)
    await message.reply("✅ Konten donasi terkirim ke admin.")

@dp.callback_query(F.data == "reject")
async def reject_cb(c: CallbackQuery):
    await c.message.delete()
    await c.answer("Ditolak.")

@dp.callback_query(F.data == "app_donasi")
async def approve_cb(c: CallbackQuery, state: FSMContext):
    await state.set_state(PostMedia.waiting_for_title)
    await c.message.answer("📝 Admin, masukkan **JUDUL** postingan:")
    await c.answer()

@dp.message(PostMedia.waiting_for_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER** untuk postingan di Channel:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_and_post_ch(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    final_fid = data.get('temp_fid', m.photo[-1].file_id)
    final_type = data.get('temp_type', "photo")
    title = data['title']
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, final_fid, final_type, title))
        await db.commit()
    
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    
    # AUTO POST KE CHANNEL 2
    ch_target = CH2_USERNAME if CH2_USERNAME.startswith("@") else f"@{CH2_USERNAME}"
    caption_ch = f"🔥 **{title}**\n\n👇 **KLIK TOMBOL DIBAWAH** 👇"
    kb_ch = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
    
    try:
        await bot.send_photo(ch_target, m.photo[-1].file_id, caption=caption_ch, reply_markup=kb_ch, parse_mode="Markdown")
        post_status = f"✅ Berhasil di-post ke {ch_target}"
    except Exception as e:
        post_status = f"❌ Gagal post ke CH: {str(e)}"

    await m.answer(f"✅ **SELESAI**\n\n{post_status}\nLink: `{link}`")
    await bot.send_message(LOG_GROUP_ID, f"📢 **KONTEN PUBLISH**\nJudul: {title}\nLink: {link}")
    await state.clear()

# ================= HANDLERS MEMBER =================

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    cmd = message.text.split(maxsplit=1)
    if len(cmd) < 2: return await message.reply("⚠️ Format: `/ask pesan` ")
    await bot.send_message(ADMIN_ID, f"📩 **ASK**\nDari: {message.from_user.full_name}\nPesan: {cmd[1]}")
    await message.reply("✅ Terkirim ke admin.")

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        return await message.answer(f"👋 Halo {message.from_user.first_name}!")
    
    code = args[1]
    status = await check_membership(message.from_user.id)
    if not all(status):
        btns = []
        links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
        for i in range(len(status)):
            if not status[i] and links[i]:
                btns.append([InlineKeyboardButton(text=f"JOIN CH/GRUP {i+1}", url=f"https://t.me/{links[i].replace('@','')}")])
        btns.append([InlineKeyboardButton(text="🔄 UPDATE", callback_data=f"retry:{code}")])
        return await message.answer("🚫 Join dulu ya:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    if row:
        if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=row[2])
        else: await bot.send_video(message.chat.id, row[0], caption=row[2])
    else: await message.answer("❌ Link salah.")

# ================= BOOTING =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot Nyala!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
