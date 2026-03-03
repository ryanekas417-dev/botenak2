#asu
import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    FSInputFile, CallbackQuery, ChatMemberUpdated # <--- Ganti/Tambah ini
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    OWNER_ID = 0

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

async def loading_anim(msg: Message):
    frames = ["⏳ Loading", "⏳ Loading.", "⏳ Loading..", "⏳ Loading..."]
    temp_msg = await msg.answer(frames[0])
    for _ in range(2): # 2 kali putaran
        for frame in frames:
            try:
                await temp_msg.edit_text(frame)
                await asyncio.sleep(0.3)
            except: break
    return temp_msg
# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_ref_agree = State()
    waiting_for_ref_channel = State()
    waiting_for_vip_group = State()
    waiting_for_fsub_list = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()
    waiting_for_new_admin = State()
    waiting_for_log_group = State() 
    waiting_for_qris = State()
    waiting_for_preview = State()
    waiting_for_manual_cover = State()
    waiting_for_cover = State()
    waiting_for_add_title = State()

class MemberStates(StatesGroup):
    waiting_for_ask = State()
    waiting_for_donation = State()
    waiting_for_vip_ss = State()

class PostMedia(StatesGroup):
    waiting_for_post_title = State()
    waiting_for_final_confirm = State()

# ================= DATABASE HELPER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Tabel Media Dasar
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS titles (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
        
        # Fitur 4 & 5: Content Analytics & Top Weekly
        await db.execute("""CREATE TABLE IF NOT EXISTS views (
            user_id INTEGER, 
            media_code TEXT, 
            viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, media_code))""")
            
        # Fitur 7: Multi Channel Post
        await db.execute("CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, name TEXT)")
        
        # Fitur 11: Referral System
        await db.execute("""CREATE TABLE IF NOT EXISTS referrals (
            owner_id INTEGER, 
            invited_user INTEGER PRIMARY KEY, 
            status TEXT DEFAULT 'valid')""")

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # ... (kode create table kamu yang sudah ada) ...
        
        await db.commit()

        # --- TAMBAHKAN KODE INI DI BAWAH COMMIT ---
        try:
            # Perintah ini untuk nambahin kolom 'title' ke tabel 'media' yang sudah ada
            await db.execute("ALTER TABLE media ADD COLUMN title TEXT")
            await db.commit()
            print("✅ Berhasil menambah kolom title!")
        except:
            # Kalau kolomnya sudah ada (setelah running sekali), dia bakal ke sini
            pass
            
        await db.commit()
# ================= PAYMENT DATABASE =================
async def init_payment_table():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            invoice_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        await db.commit()

async def get_config(key, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def set_config(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ================= VIP INVITE LINK =================
async def send_vip_link(user_id: int):

    vip_group = await get_config("vip_group")

    if not vip_group:
        await bot.send_message(user_id, "❌ VIP group belum diset admin")
        return

    try:

        link = await bot.create_chat_invite_link(
            chat_id=vip_group,
            member_limit=1
        )

        await bot.send_message(
            user_id,
            f"✅ Payment diterima!\n\nLink VIP kamu:\n{link.invite_link}"
        )

    except Exception as e:

        await bot.send_message(user_id, f"❌ Error: {e}")

async def is_admin(user_id: int):
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

async def check_membership(user_id: int):
    raw_targets = await get_config("fsub_channels")
    if not raw_targets or raw_targets.strip() == "": return []
    
    # Pecah berdasarkan spasi dan buang string kosong/sampah
    targets = [t.strip() for t in raw_targets.split() if t.strip()]
    unjoined = []
    
    for target in targets:
        clean_target = target.replace("https://t.me/", "").replace("@", "")
        if not clean_target: continue # Lewatin kalau kosong
        
        try:
            m = await bot.get_chat_member(chat_id=f"@{clean_target}", user_id=user_id)
            if m.status not in ("member", "administrator", "creator"):
                unjoined.append(clean_target)
        except Exception:
            # Kalau channel ga ketemu/bot bukan admin, anggep wajib join
            unjoined.append(clean_target)
    return unjoined

# ================= KEYBOARDS =================
async def get_titles_kb():
    kb = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM titles ORDER BY id DESC LIMIT 10") as cur:
            async for row in cur:
                kb.append([InlineKeyboardButton(text=row[0], callback_data=f"t_sel:{row[0][:20]}")])
    kb.append([InlineKeyboardButton(text="➕ TAMBAH JUDUL", callback_data="add_title_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def member_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 DONASI", callback_data="menu_donasi"), InlineKeyboardButton(text="❓ ASK", callback_data="menu_ask")],
        [InlineKeyboardButton(text="💎 ORDER VIP", callback_data="menu_vip"), InlineKeyboardButton(text="👀 PREVIEW VIP", callback_data="vip_preview")],
        [InlineKeyboardButton(text="🏆 TOP 5 WEEKLY", callback_data="top_weekly"), InlineKeyboardButton(text="🚀 REFERRAL VIP", callback_data="menu_ref")]
    ])

# ================= MEMBER & FSUB =================
@dp.message(CommandStart())
async def start_handler(m: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (m.from_user.id,))
        await db.commit()

    args = m.text.split()
    target_code = args[1] if len(args) > 1 else "none"

    unjoined = await check_membership(m.from_user.id)
    if unjoined:
        kb_list = []
        for ch in unjoined:
            clean_name = ch.replace("@", "")
            kb_list.append([InlineKeyboardButton(text=f"📢 JOIN {ch.upper()}", url=f"https://t.me/{clean_name}")])
        
        kb_list.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"check_sub:{target_code}")])
        return await m.answer("⚠️ **AKSES DIKUNCI**\nSilahkan join channel yang muncul di bawah ini untuk lanjut.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

    if target_code != "none":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (target_code,)) as cur:
                row = await cur.fetchone()
                if row:
                    # LOGIKA ANALYTICS (Fitur 4)
                    try:
                        await db.execute("INSERT OR IGNORE INTO views (user_id, media_code) VALUES (?, ?)", 
                                         (m.from_user.id, target_code))
                        await db.commit()
                    except Exception as e:
                        print(f"Error logging view: {e}")
                                       
                    if row[1] == "photo": await bot.send_photo(m.chat.id, row[0], caption=row[2], protect_content=True)
                    else: await bot.send_video(m.chat.id, row[0], caption=row[2], protect_content=True)
                    return

    await m.answer(f"👋 Halo {m.from_user.first_name}!", reply_markup=member_main_kb())

@dp.callback_query(F.data.startswith("check_sub:"))
async def check_sub_cb(c: CallbackQuery):
    unjoined = await check_membership(c.from_user.id)
    if unjoined:
        return await c.answer("❌ Kamu belum join semua channel di atas!", show_alert=True)
    
    await c.message.delete()
    code = c.data.split(":")[1]
    # Re-trigger start logic
    new_m = Message(
        message_id=c.message.message_id, date=c.message.date, chat=c.message.chat,
        from_user=c.from_user, text=f"/start {code}"
    )
    await start_handler(new_m)

# ================= LOGIKA AUTO POST (MULTI-PART) =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=(m.caption or ""), parts=[])
    await state.set_state(PostMedia.waiting_for_post_title)
    await m.reply("📝 **PILIH JUDUL:**", reply_markup=await get_titles_kb())

@dp.callback_query(PostMedia.waiting_for_post_title, F.data.startswith("t_sel:"))
async def select_title_handler(c: CallbackQuery, state: FSMContext):
    title = c.data.split(":")[1]
    await add_part_to_list(c.message, state, title)

@dp.callback_query(PostMedia.waiting_for_post_title, F.data == "add_title_btn")
async def add_new_title_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Ketik judul baru:")
    await state.set_state(AdminStates.waiting_for_add_title)

@dp.message(AdminStates.waiting_for_add_title)
async def process_save_title(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO titles (title) VALUES (?)", (m.text,))
        await db.commit()
    await add_part_to_list(m, state, m.text)

async def add_part_to_list(msg, state, p_title):
    data = await state.get_data()
    code = uuid.uuid4().hex[:15]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO media (code, file_id, type, caption) VALUES (?, ?, ?, ?)", 
                         (code, data['temp_fid'], data['temp_type'], data['temp_caption']))
        await db.commit()
    
    parts = data.get('parts', [])
    parts.append(code)
    await state.update_data(parts=parts, current_title=p_title)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ TAMBAH PART LAIN", callback_data="add_more_part")],
        [InlineKeyboardButton(text="🚀 POST SEKARANG", callback_data="final_post")]
    ])
    await msg.answer(f"✅ Part {len(parts)} siap.\nJudul: **{p_title}**", reply_markup=kb)
    await state.set_state(PostMedia.waiting_for_final_confirm)

@dp.callback_query(PostMedia.waiting_for_final_confirm, F.data == "final_post")
async def check_cover_mode(c: CallbackQuery, state: FSMContext):
    mode = await get_config("cover_mode", "OFF")
    
    if mode == "ON":
        # JANGAN panggil final_post_select_ch, tapi panggil show_channel_selection
        await show_channel_selection(c.message, state)
    else:
        # Mode OFF, minta cover manual dulu
        await c.message.answer("🖼 **COVER MODE OFF**\nSilakan kirim foto yang ingin dijadikan cover untuk post ini:")
        await state.set_state(AdminStates.waiting_for_manual_cover)

@dp.message(AdminStates.waiting_for_manual_cover, F.photo)
async def handle_manual_cover(m: Message, state: FSMContext):
    # Simpan file_id cover khusus untuk post ini saja ke state
    await state.update_data(manual_cover=m.photo[-1].file_id)
    
    # Lanjut ke pilih channel (panggil fungsi pilih channel)
    # Kita buatkan helper untuk panggil menu pilih channel
    await show_channel_selection(m, state)

async def show_channel_selection(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cur:
            rows = await cur.fetchall()
            
    if not rows:
        return await m.answer("❌ Daftarkan channel dulu di /panel!")
        
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"📤 KE: {r[0]}", callback_data=f"send_to:{r[0]}")])
    kb.append([InlineKeyboardButton(text="🚀 POST KE SEMUA", callback_data="send_to:all")])
    
    await m.answer("🎯 **PILIH TUJUAN POSTING:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
@dp.callback_query(F.data.startswith("send_to:"))
async def execute_posting(c: CallbackQuery, state: FSMContext):
    target = c.data.split(":")[1]
    data = await state.get_data()
    
    # Ambil data yang diperlukan dari state
    parts = data.get('parts', [])
    p_title = data.get('current_title', 'Video Baru')
    
    # 1. DEFINISIKAN TARGETS (PENTING!)
    targets = []
    if target == "all":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT channel_id FROM channels") as cur:
                rows = await cur.fetchall()
                targets = [r[0] for r in rows]
    else:
        # Jika cuma satu channel, masukkan ke dalam list
        targets = [target]

    if not targets:
        return await c.answer("❌ Tidak ada channel tujuan!", show_alert=True)

    # 2. Buat Keyboard Part
    bot_info = await bot.get_me()
    kb_rows = []
    row = []
    for i, code in enumerate(parts, 1):
        row.append(InlineKeyboardButton(text=f"Part {i}", url=f"https://t.me/{bot_info.username}?start={code}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row: kb_rows.append(row)
    
    # 3. Tentukan Cover
    mode = await get_config("cover_mode", "OFF")
    cover_to_use = await get_config("cover_file_id") if mode == "ON" else data.get("manual_cover")

    # 4. MULAI KIRIM
    success = 0
    for ch_id in targets:
        try:
            if cover_to_use:
                await bot.send_photo(
                    ch_id, 
                    cover_to_use, 
                    caption=f" **{p_title}**\n\n", 
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
                )
            else:
                await bot.send_message(
                    ch_id, 
                    f" **{p_title}**\n\n", 
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
                )
            success += 1
        except Exception as e:
            print(f"Gagal kirim ke {ch_id}: {e}")

    await c.message.edit_text(f"✅ Berhasil dipost ke {success} channel.")
    await state.clear()
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(PostMedia.waiting_for_final_confirm))
async def handle_next_part(m: Message, state: FSMContext):
    data = await state.get_data()
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=(m.caption or ""))
    await add_part_to_list(m, state, data['current_title'])

@dp.callback_query(PostMedia.waiting_for_final_confirm, F.data == "final_post")
async def final_post_handler(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parts, p_title = data['parts'], data['current_title']
    bot_user = (await bot.get_me()).username
    
    # Generate Keyboard Parts
    kb_rows = []
    row = []
    for i, code in enumerate(parts, 1):
        row.append(InlineKeyboardButton(text=f"Part {i}", url=f"https://t.me/{bot_user}?start={code}"))
        if len(row) == 2: kb_rows.append(row); row = []
    if row: kb_rows.append(row)
    
    # MULTI CHANNEL (Fitur 7) & COVER (Fitur 9)
    ch_id = await get_config("channel_post") # Nanti bisa dikembangin ke multi-loop
    cover_mode = await get_config("cover_mode", "OFF")
    cover_file = await get_config("cover_file_id")
    
    load = await loading_anim(c.message)
    try:
        if cover_mode == "ON" and cover_file:
            await bot.send_photo(ch_id, cover_file, caption=f"🎬 **{p_title}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        else:
            # Jika mode OFF, kirim tanpa cover atau kirim file part 1 sebagai cover
            await bot.send_message(ch_id, f"🎬 **{p_title}**\n\nSilahkan pilih part di bawah:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        await load.edit_text("✅ BERHASIL DI POST!")
    except Exception as e:
        await load.edit_text(f"❌ GAGAL: {e}")
    
    await state.clear()
# ================= MEMBER INTERACTION (FORWARDED) =================
@dp.callback_query(F.data == "menu_ask")
async def ask_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim pesanmu:"); await state.set_state(MemberStates.waiting_for_ask)

@dp.message(MemberStates.waiting_for_ask)
async def process_ask(m: Message, state: FSMContext):
    await m.forward(OWNER_ID)
    await bot.send_message(OWNER_ID, f"📩 **ASK DARI: {m.from_user.id}**", 
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")]]))
    await m.reply("✅ Terkirim."); await state.clear()

@dp.callback_query(F.data == "menu_donasi")
async def donasi_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim donasi/pesan:"); await state.set_state(MemberStates.waiting_for_donation)

@dp.message(MemberStates.waiting_for_donation)
async def process_donation(m: Message, state: FSMContext):
    cap = m.caption or m.text or "Tanpa pesan"
    await m.forward(OWNER_ID)
    await bot.send_message(OWNER_ID, f"🎁 **DONASI BARU**\nUser: `{m.from_user.id}`\nCaption: {cap}")
    await m.reply("✅ Terkirim."); await state.clear()

@dp.callback_query(F.data == "menu_vip")
async def order_vip(c: CallbackQuery, state: FSMContext):
    qris = await get_config("qris_file_id")
    if not qris: return await c.answer("QRIS kosong.", show_alert=True)
    await bot.send_photo(c.message.chat.id, qris, caption="Kirim SS Bukti Bayar:")
    await state.set_state(MemberStates.waiting_for_vip_ss)

@dp.callback_query(F.data == "vip_preview")
async def preview_vip(c: CallbackQuery):
    prev = await get_config("preview_msg_id")
    if prev: await bot.copy_message(c.message.chat.id, OWNER_ID, int(prev))
    else: await c.answer("Preview kosong.")

@dp.message(MemberStates.waiting_for_vip_ss, F.photo)
async def process_vip_ss(m: Message, state: FSMContext):
    # Kirim ke Admin (Owner)
    await m.forward(OWNER_ID)
    
    # Tombol buat Admin ambil tindakan
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ APPROVE", callback_data=f"vip_action:approve:{m.from_user.id}"),
            InlineKeyboardButton(text="❌ REJECT", callback_data=f"vip_action:reject:{m.from_user.id}")
        ],
        [InlineKeyboardButton(text="💬 CHAT USER", callback_data=f"reply:{m.from_user.id}")]
    ])
    
    await bot.send_message(
        OWNER_ID, 
        f"💎 **BUKTI TRANSFER BARU**\n\n"
        f"User: `{m.from_user.id}`\n"
        f"Nama: {m.from_user.full_name}",
        reply_markup=kb
    )
    await m.reply("✅ Bukti transfer telah dikirim ke Admin. Mohon tunggu proses verifikasi.")
    await state.clear()

# ================= ADMIN & CONFIG =================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id): return
    btns = [
        [InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="open_settings")],
        [InlineKeyboardButton(text="🖼 COVER", callback_data="set_cover"), InlineKeyboardButton(text="🖼 QRIS", callback_data="set_qris")],
        [InlineKeyboardButton(text="📺 PREVIEW", callback_data="set_preview")],
        [InlineKeyboardButton(text="👑 VIP GROUP", callback_data="set_vip_group")],
        [InlineKeyboardButton(text="📜 SET LOG GROUP", callback_data="set_log_group")],
        [InlineKeyboardButton(text="🎯 SET REF CHANNEL", callback_data="set_ref_ch")],
        [InlineKeyboardButton(text="📡 BC", callback_data="menu_broadcast"), InlineKeyboardButton(text="📦 DB", callback_data="menu_db")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="close_panel")]
    ]
    await message.reply("🛠 **PANEL**", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data == "open_settings")
async def settings_cb(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    
    # Ambil status mode saat ini untuk tampilan tombol
    mode = await get_config("cover_mode", "OFF")
    status_emoji = "🟢" if mode == "ON" else "🔴"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 POST CH", callback_data="set_post")],
        [InlineKeyboardButton(text="👥 FSUB", callback_data="set_fsub_list")],
        # Tombol Baru di sini:
        [InlineKeyboardButton(text=f"{status_emoji} COVER MODE: {mode}", callback_data="toggle_cover")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="close_panel")]
    ])
    await c.message.edit_text("⚙️ **CONFIG SETTINGS**", reply_markup=kb)

@dp.callback_query(F.data == "toggle_cover")
async def toggle_cover_handler(c: CallbackQuery):
    # Ambil status sekarang
    curr = await get_config("cover_mode", "OFF")
    # Balik statusnya
    new_mode = "OFF" if curr == "ON" else "ON"
    
    await set_config("cover_mode", new_mode)
    await c.answer(f"✅ Mode Cover diubah ke {new_mode}", show_alert=True)
    
    # Refresh menu biar tulisan tombolnya berubah
    await settings_cb(c)

@dp.callback_query(F.data == "set_post")
async def set_post_menu(c: CallbackQuery):
    # Menampilkan list channel yang sudah terdaftar
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT channel_id FROM channels") as cur:
            rows = await cur.fetchall()
    
    text = "📢 **DAFTAR CHANNEL POSTING**\n\n"
    if rows:
        for r in rows: text += f"• `{r[0]}`\n"
    else:
        text += "Belum ada channel."
    
    kb = [
        [InlineKeyboardButton(text="➕ TAMBAH CHANNEL", callback_data="add_ch_post")],
        [InlineKeyboardButton(text="🗑 HAPUS SEMUA", callback_data="clear_ch_post")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="open_settings")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "add_ch_post")
async def add_ch_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim ID Channel (contoh: -100xxx):")
    await state.set_state(AdminStates.waiting_for_channel_post)

@dp.message(AdminStates.waiting_for_channel_post)
async def save_new_ch(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (m.text.strip(),))
        await db.commit()
    await m.reply("✅ Channel ditambahkan ke list!")
    await state.clear()

@dp.callback_query(F.data == "set_fsub_list")
async def set_fsub_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim username (spasi): `@ch1 @ch2`:"); await state.set_state(AdminStates.waiting_for_fsub_list)

@dp.message(AdminStates.waiting_for_fsub_list)
async def process_fsub(m: Message, state: FSMContext):
    await set_config("fsub_channels", m.text.strip()); await m.reply("✅ Set."); await state.clear()

@dp.callback_query(F.data == "menu_db", F.from_user.id == OWNER_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME): await c.message.reply_document(FSInputFile(DB_NAME))
    await c.answer()

@dp.message(Command("update"))
async def update_database(m: Message):
    if not await is_admin(m.from_user.id): return
    if not m.reply_to_message or not m.reply_to_message.document: return await m.reply("❌ Reply .db")
    file = await bot.get_file(m.reply_to_message.document.file_id)
    await bot.download_file(file.file_path, DB_NAME)
    await init_db(); await m.reply("✅ UPDATED")

@dp.callback_query(F.data.startswith("reply:"))
async def reply_cb(c: CallbackQuery, state: FSMContext):
    await state.update_data(target=c.data.split(":")[1])
    await c.message.answer("Ketik balasan:"); await state.set_state(AdminStates.waiting_for_reply)

@dp.message(AdminStates.waiting_for_reply)
async def process_reply_send(m: Message, state: FSMContext):
    d = await state.get_data()
    try: await m.copy_to(d['target']); await m.reply("✅ OK")
    except: await m.reply("❌ Gagal")
    await state.clear()

@dp.callback_query(F.data.startswith("vip_action:"))
async def vip_decision(c: CallbackQuery):
    # Cek apakah yang mencet beneran admin
    if not await is_admin(c.from_user.id):
        return await c.answer("Lu bukan admin!", show_alert=True)

    data = c.data.split(":")
    action = data[1]     # approve atau reject
    target_id = int(data[2]) # ID user yang mau di-acc
    
    log_ch = await get_config("log_group") # Ambil ID grup log dari database
    
    if action == "approve":
        vip_group = await get_config("vip_group")
        if not vip_group: 
            return await c.answer("❌ Error: Group VIP belum diset di /panel!", show_alert=True)
        
        try:
            # Fitur 2: Link otomatis max 1 orang
            link = await bot.create_chat_invite_link(chat_id=vip_group, member_limit=1)
            
            await bot.send_message(
                target_id, 
                f"✅ **PEMBAYARAN DISETUJUI!**\n\nSelamat datang di VIP. Ini link akses kamu:\n{link.invite_link}\n\n*Note: Link ini hanya bisa diklik satu kali.*"
            )
            await c.message.edit_text(f"✅ User `{target_id}` Berhasil di-Approve.")

            # Fitur 3: Kirim ke VIP JOIN LOGGER
            if log_ch:
                try:
                    # Ambil info user buat di log
                    u = await bot.get_chat(target_id)
                    log_msg = (
                        f"👥 **VIP JOIN LOGGER**\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"👤 **Nama:** [{u.first_name}](tg://user?id={target_id})\n"
                        f"🆔 **ID:** `{target_id}`\n"
                        f"🔗 **Profil:** [Klik Disini](tg://user?id={target_id})\n"
                        f"✅ **Status:** Manual Approved"
                    )
                    await bot.send_message(log_ch, log_msg)
                except: pass # Biar ga eror kalau bot belum join grup log
                
        except Exception as e:
            await c.answer(f"Gagal buat link: {e}", show_alert=True)
            
    elif action == "reject":
        try:
            await bot.send_message(target_id, "❌ **PEMBAYARAN DITOLAK**\n\nMohon maaf, bukti transfer kamu tidak valid atau tidak terbaca. Silahkan hubungi admin.")
            await c.message.edit_text(f"❌ User `{target_id}` Berhasil di-Reject.")
        except: pass

@dp.callback_query(F.data == "set_post")
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Username Channel:"); await state.set_state(AdminStates.waiting_for_channel_post)

@dp.message(AdminStates.waiting_for_channel_post)
async def process_set_post(m: Message, state: FSMContext):
    await set_config("channel_post", m.text.strip()); await m.reply("✅ Set."); await state.clear()

@dp.callback_query(F.data == "set_cover")
async def btn_set_cover(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto:"); await state.set_state(AdminStates.waiting_for_cover)

@dp.message(AdminStates.waiting_for_cover, F.photo)
async def save_cover(m: Message, state: FSMContext):
    await set_config("cover_file_id", m.photo[-1].file_id); await m.reply("✅ OK."); await state.clear()

@dp.callback_query(F.data == "set_qris")
async def btn_set_qris(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim QRIS:"); await state.set_state(AdminStates.waiting_for_qris)

@dp.message(AdminStates.waiting_for_qris, F.photo)
async def save_qris(m: Message, state: FSMContext):
    await set_config("qris_file_id", m.photo[-1].file_id); await m.reply("✅ OK."); await state.clear()

@dp.callback_query(F.data == "set_preview")
async def btn_set_prev(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim media preview:"); await state.set_state(AdminStates.waiting_for_preview)

@dp.message(AdminStates.waiting_for_preview)
async def save_preview(m: Message, state: FSMContext):
    await set_config("preview_msg_id", str(m.message_id)); await m.reply("✅ OK."); await state.clear()

# ================= SET VIP GROUP =================
@dp.callback_query(F.data == "set_vip_group")
async def set_vip_group_btn(c: CallbackQuery, state: FSMContext):

    if not await is_admin(c.from_user.id):
        return

    await c.message.answer("Kirim username group VIP\ncontoh:\n@vipgroup")

    await state.set_state(AdminStates.waiting_for_vip_group)


@dp.message(AdminStates.waiting_for_vip_group)
async def save_vip_group(m: Message, state: FSMContext):

    await set_config("vip_group", m.text.strip())

    await m.reply("✅ VIP group set")

    await state.clear()

@dp.callback_query(F.data == "menu_broadcast", F.from_user.id == OWNER_ID)
async def broadcast_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim BC:"); await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast, F.from_user.id == OWNER_ID)
async def process_broadcast(m: Message, state: FSMContext):
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            async for row in cur:
                try: await m.copy_to(row[0]); count += 1; await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Terkirim ke {count} user."); await state.clear()

@dp.message(Command("resetfsub"))
async def reset_fsub_darurat(m: Message):
    if not await is_admin(m.from_user.id): return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM config WHERE key='fsub_channels'")
        await db.commit()
    await m.reply("✅ **FSUB DIBERSIHKAN TOTAL!**\nSekarang fsub kosong. Silahkan set ulang lewat /panel dengan bener.")

@dp.callback_query(F.data == "close_panel")
async def close_panel(c: CallbackQuery): await c.message.delete()

@dp.callback_query(F.data == "set_log_group")
async def set_log_group_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim ID Group untuk Log VIP (Contoh: -100123456789):")
    await state.set_state(AdminStates.waiting_for_log_group)

# Daftarkan state baru ini di class AdminStates (di paling atas kode)
# Tambahkan: waiting_for_log_group = State() 

@dp.message(AdminStates.waiting_for_log_group)
async def save_log_group(m: Message, state: FSMContext):
    await set_config("log_group", m.text.strip())
    await m.reply("✅ VIP Log Group Berhasil Diset!")
    await state.clear()

# --- FITUR 5: TOP 5 WEEKLY ---
@dp.callback_query(F.data == "top_weekly")
@dp.callback_query(F.data == "top_weekly")
async def top_weekly_handler(c: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        query = """
            SELECT COALESCE(m.title, 'Video'), COUNT(v.user_id) as total, m.code
            FROM views v
            JOIN media m ON v.media_code = m.code
            GROUP BY v.media_code
            ORDER BY total DESC
            LIMIT 5
        """
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    if not rows:
        return await c.answer("📊 Belum ada data. Ayo tonton video dulu!", show_alert=True)

    text = "🏆 **TOP 5 VIDEO REAL-TIME**\n\n"
    kb = []
    bot_user = (await bot.get_me()).username
    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]} — ({row[1]} views)\n"
        kb.append([InlineKeyboardButton(text=f"▶️ NONTON: {row[0]}", url=f"https://t.me/{bot_user}?start={row[2]}")])
    
    kb.append([InlineKeyboardButton(text="🔙 KEMBALI", callback_data="close_panel")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
# --- FITUR 10 & 11: REFERRAL SYSTEM ---
@dp.callback_query(F.data == "menu_ref")
async def ref_info(c: CallbackQuery):
    text = (
        "🚀 **REFERRAL VIP SYSTEM**\n\n"
        "Ajak 20 orang join bot ini dan dapatkan AKSES VIP GRATIS!\n"
        "1. Klik setuju untuk buat link.\n"
        "2. Sebar link kamu.\n"
        "3. Jika capai 20 orang, klik klaim."
    )
    kb = [[InlineKeyboardButton(text="✅ SETUJU & BUAT LINK", callback_data="gen_ref_link")],
          [InlineKeyboardButton(text="📊 CEK STATUS / KLAIM", callback_data="status_ref")]]
    await c.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# --- SET CHANNEL REFERRAL ---
@dp.callback_query(F.data == "set_ref_ch")
async def set_ref_ch_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim username channel (@channel) atau forward pesan dari channel tersebut:")
    await state.set_state(AdminStates.waiting_for_ref_channel)

@dp.message(AdminStates.waiting_for_ref_channel)
async def save_ref_ch(m: Message, state: FSMContext):
    ch_id = ""
    if m.forward_from_chat: ch_id = m.forward_from_chat.id
    elif m.text.startswith("@"): ch_id = m.text
    else: return await m.reply("Gagal. Kirim @username atau forward post.")
    
    await set_config("ref_channel", str(ch_id))
    await m.reply(f"✅ Channel Referral Set: {ch_id}")
    await state.clear()

# --- GENERATE LINK KHUSUS (Fitur 10) ---
# --- FITUR 10 & 11: REFERRAL SYSTEM (OPTIMIZED) ---

@dp.callback_query(F.data == "menu_ref")
async def ref_info(c: CallbackQuery):
    # Tahap 1: Penjelasan awal (Sesuai permintaanmu)
    text = (
        "🚀 **PROGRAM REFERRAL VIP**\n\n"
        "Dapatkan akses VIP Gratis dengan mengajak 20 teman!\n\n"
        "**Cara Kerja:**\n"
        "1. Klik setuju untuk membuat link referral khusus.\n"
        "2. Sebarkan link tersebut ke teman atau grup.\n"
        "3. Setiap orang yang join lewat linkmu, poin bertambah.\n"
        "4. Setelah 20 poin, kamu bisa klaim hadiah ke Admin."
    )
    kb = [
        [InlineKeyboardButton(text="✅ SETUJU & BUAT LINK", callback_data="gen_ref_link")],
        [InlineKeyboardButton(text="❌ TOLAK", callback_data="close_panel")]
    ]
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "gen_ref_link")
async def gen_ref_handler(c: CallbackQuery):
    ref_ch = await get_config("ref_channel")
    if not ref_ch: 
        return await c.answer("❌ Admin belum mengatur Channel Referral!", show_alert=True)
    
    try:
        # Tahap 2: Link baru dibuat HANYA jika setuju
        link = await bot.create_chat_invite_link(chat_id=ref_ch, name=f"REF_{c.from_user.id}")
        
        text = (
            "✅ **LINK REFERRAL KAMU SIAP!**\n\n"
            f"Silakan sebarkan link ini:\n`{link.invite_link}`\n\n"
            "Bot akan memberitahumu setiap ada orang yang join."
        )
        kb = [[InlineKeyboardButton(text="📊 CEK PROGRES", callback_data="status_ref")]]
        await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except Exception as e:
        await c.message.answer(f"❌ Gagal: Pastikan bot Admin di {ref_ch}")

@dp.chat_member()
async def tracking_public_join(event: ChatMemberUpdated):
    # Tahap 3: Notifikasi Pribadi setiap ada yang join
    if event.new_chat_member.status == "member":
        invite_link = event.invite_link
        if invite_link and invite_link.name and invite_link.name.startswith("REF_"):
            try:
                inviter_id = int(invite_link.name.split("_")[1])
                new_user_id = event.from_user.id
                if inviter_id == new_user_id: return

                async with aiosqlite.connect(DB_NAME) as db:
                    # Anti-cheat: satu user diajak cuma dihitung sekali
                    res = await db.execute("SELECT 1 FROM referrals WHERE invited_user=?", (new_user_id,))
                    if await res.fetchone(): return

                    await db.execute("INSERT INTO referrals (owner_id, invited_user) VALUES (?, ?)", (inviter_id, new_user_id))
                    async with db.execute("SELECT COUNT(*) FROM referrals WHERE owner_id=?", (inviter_id,)) as cur:
                        count = (await cur.fetchone())[0]
                    await db.commit()
                
                # Kasih tau secara pribadi
                if count == 20:
                    text_win = "🎊 **SELAMAT!** Kamu berhasil mengajak 20 orang!\n\nKlik tombol di bawah untuk klaim hadiah VIP kamu."
                    kb_win = [[InlineKeyboardButton(text="🎁 KLAIM HADIAH VIP", callback_data="klaim_ref_reward")]]
                    await bot.send_message(inviter_id, text_win, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_win))
                else:
                    await bot.send_message(inviter_id, f"🔔 **Poin Masuk!**\nSeseorang join via link kamu.\nTotal: `{count}` / 20")
            except: pass

@dp.callback_query(F.data == "status_ref")
async def status_ref(c: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE owner_id=?", (c.from_user.id,)) as cur:
            count = (await cur.fetchone())[0]
            
    text = f"📊 **STATUS REFERRAL**\n\nProgres: `{count}` / 20 orang."
    kb = []
    if count >= 20:
        kb.append([InlineKeyboardButton(text="🎁 KLAIM VIP", callback_data="klaim_ref_reward")])
    kb.append([InlineKeyboardButton(text="🔙 KEMBALI", callback_data="menu_ref")])
    await c.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "klaim_ref_reward")
async def process_klaim_ref(c: CallbackQuery):
    # Tahap 4: Forward ke Admin untuk Approve
    kb_admin = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ APPROVE (Kirim Link VIP)", callback_data=f"vip_action:approve:{c.from_user.id}"),
            InlineKeyboardButton(text="❌ TOLAK", callback_data=f"reply:{c.from_user.id}")
        ]
    ])
    
    await bot.send_message(
        OWNER_ID, 
        f"📩 **KLAIM REFERRAL BARU**\n\n"
        f"User: `{c.from_user.id}`\n"
        f"Nama: {c.from_user.full_name}\n"
        f"Poin: 20 (Sistem Terverifikasi)",
        reply_markup=kb_admin
    )
    await c.message.edit_text("✅ **PERMINTAAN KLAIM TERKIRIM!**\nAdmin akan segera memberikan link VIP kamu. Mohon tunggu.")

# --- SET CHANNEL REFERRAL (ADMIN ONLY) ---
@dp.callback_query(F.data == "set_ref_ch")
async def set_ref_ch_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim username channel (@channel) tempat referral bekerja:")
    await state.set_state(AdminStates.waiting_for_ref_channel)

@dp.message(AdminStates.waiting_for_ref_channel)
async def save_ref_ch(m: Message, state: FSMContext):
    await set_config("ref_channel", m.text.strip())
    await m.reply(f"✅ Channel Referral Set ke: {m.text}")
    await state.clear()
    
async def main():
    await init_db() 
    await init_payment_table()
    await bot.delete_webhook(drop_pending_updates=True)
    
    # WAJIB: Tambahkan allowed_updates agar bot bisa dapet info member join
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member", "chat_join_request"])
if __name__ == "__main__":
    asyncio.run(main())

















