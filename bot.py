import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, CallbackQuery, ChatMemberUpdated, ChatPermissions
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")
EXEMPT_USERNAME = os.getenv("EXEMPT_USERNAME")

raw_log_id = os.getenv("LOG_GROUP_ID", "").replace("@", "")
if raw_log_id.replace("-", "").isdigit():
    LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))
else:
    LOG_GROUP_ID = ADMIN_ID

KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

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

# ================= MENU COMMANDS =================
async def set_commands():
    member_cmd = [
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin"),
        BotCommand(command="donasi", description="Kirim Konten")
    ]
    await bot.set_my_commands(member_cmd, scope=BotCommandScopeDefault())
    if ADMIN_ID:
        admin_cmd = member_cmd + [
            BotCommand(command="stats", description="Statistik"),
            BotCommand(command="senddb", description="Ambil Database"),
            BotCommand(command="id", description="Cek ID")
        ]
        try:
            await bot.set_my_commands(admin_cmd, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except: pass

# ================= LOG MEMBER & FILTER KATA =================

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    user = event.new_chat_member.user
    text = f"✅ **MEMBER JOIN**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 {event.chat.title}"
    await bot.send_message(LOG_GROUP_ID, text)

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEFT))
async def on_user_left(event: ChatMemberUpdated):
    user = event.old_chat_member.user
    text = f"❌ **MEMBER KELUAR**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 {event.chat.title}"
    await bot.send_message(LOG_GROUP_ID, text)

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def filter_kata(message: Message):
    curr_usn = message.from_user.username
    if message.from_user.id == ADMIN_ID or (curr_usn and curr_usn.lower() == EXEMPT_USERNAME.lower()):
        return
    if any(k in message.text.lower() for k in KATA_KOTOR):
        try:
            await message.delete()
            until = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(message.chat.id, message.from_user.id, ChatPermissions(can_send_messages=False), until_date=until)
            await message.answer(f"🚫 {message.from_user.mention_html()} Mute 24 Jam (Kata Terlarang!)", parse_mode="HTML")
            await bot.send_message(LOG_GROUP_ID, f"🔇 **AUTO MUTE**\nUser: {message.from_user.full_name}\nKata: {message.text}")
        except: pass

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
        await message.reply_document(FSInputFile(DB_NAME))

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def stats(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await message.answer(f"📊 User: {u[0]} | Media: {m[0]}")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def handle_uploads(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        fid = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else message.document.file_id)
        await state.update_data(temp_fid=fid, temp_type="photo" if message.photo else "video")
        await state.set_state(PostMedia.waiting_for_title)
        return await message.reply("📝 Admin, masukkan **JUDUL**:")

    await bot.send_message(LOG_GROUP_ID, f"🎁 **DONASI MASUK**\nDari: {message.from_user.full_name}")
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ POST", callback_data="app_donasi"), InlineKeyboardButton(text="❌ REJECT", callback_data="reject")]])
    await bot.send_message(ADMIN_ID, f"Review donasi {message.from_user.full_name}:", reply_markup=kb)
    await message.reply("✅ Terkirim ke admin.")

@dp.callback_query(F.data == "reject")
async def reject_cb(c: CallbackQuery):
    await c.message.delete()

@dp.callback_query(F.data == "app_donasi")
async def approve_cb(c: CallbackQuery, state: FSMContext):
    await state.set_state(PostMedia.waiting_for_title)
    await c.message.answer("📝 Judul donasi:")
    await c.answer()

@dp.message(PostMedia.waiting_for_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER**:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    fid = data.get('temp_fid', m.photo[-1].file_id)
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, fid, data.get('temp_type', "photo"), data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    ch_target = CH2_USERNAME if CH2_USERNAME.startswith("@") else f"@{CH2_USERNAME}"
    kb_ch = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 NONTON", url=link)]])
    
    try:
        await bot.send_photo(ch_target, m.photo[-1].file_id, caption=f"🔥 **{data['title']}**", reply_markup=kb_ch)
    except: pass

    await m.answer(f"✅ Berhasil!\nLink: `{link}`")
    await bot.send_message(LOG_GROUP_ID, f"📢 **KONTEN PUBLISH**\n{data['title']}\n{link}")
    await state.clear()

# ================= HANDLERS MEMBER =================

@dp.callback_query(F.data.startswith("retry:"))
async def retry_btn(c: CallbackQuery):
    code = c.data.split(":")[1]
    await c.message.delete()
    # Memicu ulang logika start
    await start_handler(c.message, code_override=code, user_override=c.from_user)

@dp.message(Command("donasi"))
async def donasi_manual(message: Message):
    await message.answer("🙏 Silakan kirim Foto/Video donasi kamu langsung ke sini.")

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    cmd = message.text.split(maxsplit=1)
    if len(cmd) < 2: return await message.reply("⚠️ Format: `/ask pesan` ")
    await bot.send_message(ADMIN_ID, f"📩 **ASK**: {cmd[1]}\nDari: {message.from_user.full_name}")
    await message.reply("✅ Terkirim.")

@dp.message(CommandStart())
async def start_handler(message: Message, code_override=None, user_override=None):
    user = user_override or message.from_user
    uid = user.id
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        await db.commit()
    
    text_args = message.text.split(" ", 1)
    code = code_override or (text_args[1] if len(text_args) > 1 else None)
    
    if not code:
        return await message.answer(f"👋 Halo {user.first_name}!")
    
    status = await check_membership(uid)
    if not all(status):
        btns = []
        links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
        for i, (s, l) in enumerate(zip(status, links)):
            if not s and l:
                btns.append([InlineKeyboardButton(text=f"JOIN {i+1}", url=f"https://t.me/{l.replace('@','')}")])
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry:{code}")])
        return await bot.send_message(message.chat.id if not code_override else message.chat.id, "🚫 Join dulu:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur: row = await cur.fetchone()
    if row:
        if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=row[2])
        else: await bot.send_video(message.chat.id, row[0], caption=row[2])

# ================= BOOTING =================
async def main():
    await init_db()
    await set_commands()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
