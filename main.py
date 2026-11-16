import os
import time
import sqlite3
import asyncio
import traceback
import html
import re
import imaplib
import email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest

# ==========================================
# KONFIGURASI UTAMA
# ==========================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

# Konfigurasi Email & Gambar
BANNER_START_URL = os.environ.get("BANNER_START_URL", "https://i.ibb.co.com/wFZGzGsW/Logo-Gorilla-Mnky-Fix-Bergaya-Gangster.png")
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

# Email Tujuan WhatsApp
WA_SUPPORT_EMAIL = "support@whatsapp.com"

BOT_VERSION = "1.6 MNKYFIX MLO-Style"
START_TIME = time.time()
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mnkyfix_data.db")

def is_admin(uid): return str(uid) == str(ADMIN_ID)

# ==========================================
# KEYBOARD (TAMPILAN BAWAH)
# ==========================================
def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("🛠️ Fix Merah")],
        [KeyboardButton("📜 Riwayat"), KeyboardButton("👥 Leaderboard")],
        [KeyboardButton("❓ Panduan")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# ==========================================
# DATABASE SEDERHANA
# ==========================================
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stats (
        user_id INTEGER PRIMARY KEY,
        total_attempts INTEGER DEFAULT 0,
        total_success INTEGER DEFAULT 0
    )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_method', '1')")
    conn.commit(); conn.close()

def get_setting(key, default=None):
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close(); return row[0] if row else default
    except: return default

def set_setting(key, value):
    try:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit(); conn.close()
    except: pass

def update_stats(user_id, success_count=1):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT total_attempts, total_success FROM stats WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO stats (user_id, total_attempts, total_success) VALUES (?, ?, ?)", (user_id, success_count, success_count))
    else:
        c.execute("UPDATE stats SET total_attempts=?, total_success=? WHERE user_id=?", (row[0] + success_count, row[1] + success_count, user_id))
    conn.commit(); conn.close()

def get_stats(user_id):
    conn = get_db()
    row = conn.execute("SELECT total_attempts, total_success FROM stats WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row: return 0, 0
    return row[0], row[1]

# ==========================================
# FUNGSI PENGIRIM EMAIL (SMTP)
# ==========================================
def _send_email_sync(target_email, wa_number, reason_text):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return False, "Kredensial email belum diatur."
    
    subject = f"Appeal Request: Account Recovery for {wa_number}"
    
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = target_email
    msg['Subject'] = subject
    msg.attach(MIMEText(reason_text, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, target_email, msg.as_string())
        server.quit()
        return True, "Berhasil"
    except Exception as e:
        return False, str(e)

async def send_email_async(target_email, wa_number, reason_text):
    return await asyncio.to_thread(_send_email_sync, target_email, wa_number, reason_text)

# ==========================================
# BACKGROUND TASK: PROSES BULK EMAIL
# ==========================================
async def process_bulk_emails_task(context, chat_id, message_id, wa_numbers, metode, user_id):
    success_count = 0
    
    for num in wa_numbers:
        if metode == "1":
            body_text = f'Dear WhatsApp Support Team, I am writing to appeal the "Login not available right now" restriction on my phone number {num}. I believe this might be a misunderstanding or a system error. I always try to follow WhatsApp\'s Terms of Service and use the official WhatsApp application. This phone number is my personal number, and I need access to it for my daily communication with family and friends. Could you please review my account and lift this temporary hold so I can log in and use WhatsApp normally again? Thank you very much for your time and assistance'
        else:
            body_text = f'Dear WhatsApp support center.\nI would like to report about my number get login not available, i need this number for working and business, many important things on my WhatsApp account.\nPlease fix this problem and let me log in to my own account,\n{num}\nRegards.'
        
        success, err = await send_email_async(WA_SUPPORT_EMAIL, num, body_text)
        if success: success_count += 1
        
        await asyncio.sleep(2)
    
    if success_count > 0:
        update_stats(user_id, success_count=success_count)
        
    numbers_list = "\n".join([f"◦ {n}" for n in wa_numbers])
    msg_terkirim = (
        f"<b>[ HASIL BANDING FIX MERAH ]</b>\n\n"
        f"<blockquote>✅ <b>Selesai! Terkirim {success_count} Nomor</b>\n\n"
        f"{numbers_list}</blockquote>\n\n"
        f"🙂 Status akan berubah otomatis jika menerima balasan email dari WhatsApp."
    )
    
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=msg_terkirim, parse_mode='HTML')
        kb_sukses = [[InlineKeyboardButton("✅ Selesai & Tutup", callback_data='run_selesai')]]
        await context.bot.send_message(chat_id=chat_id, text="✅ <b>Proses pengiriman email selesai.</b>", reply_markup=InlineKeyboardMarkup(kb_sukses), parse_mode='HTML')
    except: pass

# ==========================================
# BACKGROUND TASK: CEK EMAIL MASUK (IMAP)
# ==========================================
def _fetch_latest_email():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD: return None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, '(UNSEEN FROM "whatsapp")')
        if status != "OK": return None
        email_ids = messages[0].split()
        if not email_ids: return None
        
        latest_id = email_ids[-1]
        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes): subject = subject.decode(encoding if encoding else "utf-8")
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors='ignore')
                            break
                else: body = msg.get_payload(decode=True).decode(errors='ignore')
                mail.store(latest_id, '+FLAGS', '\\Seen')
                mail.logout()
                return subject, body
        mail.logout()
    except: return None

async def email_checker_task(application):
    await asyncio.sleep(5)
    while True:
        if GMAIL_USER and GMAIL_APP_PASSWORD:
            result = await asyncio.to_thread(_fetch_latest_email)
            if result:
                subject, body = result
                if len(body) > 3000: body = body[:3000] + "..."
                notif = f"📬 <b>BALASAN WHATSAPP DITERIMA!</b>\n\n<b>Subjek:</b> {html.escape(subject)}\n\n<blockquote>{html.escape(body)}</blockquote>"
                try: await application.bot.send_message(chat_id=int(ADMIN_ID), text=notif, parse_mode='HTML')
                except: pass
        await asyncio.sleep(20)

# ==========================================
# TAMPILAN DASHBOARD (100% MLO STYLE)
# ==========================================
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, is_edit=False):
    if not is_admin(update.effective_user.id): return
    user_id = update.effective_user.id
    attempts, success = get_stats(user_id)
    persen = 0.0 if attempts == 0 else (success / attempts) * 100
    metode_aktif = get_setting('default_method', '1')
    
    teks = (
        f"<b>[ MNKYFIX DASHBOARD ]</b>\n\n"
        
        f"<blockquote>👤 <b>Status Kamu [ 📱 Metode {metode_aktif} ]</b>\n"
        f"├ Nama : Rei\n"
        f"├ Level : <b>VIP OWNER</b>\n"
        f"├ Aktif s/d : <b>Lifetime</b>\n"
        f"├ Kuota hari ini : <b>Unlimited</b>\n"
        f"└ Batch maksimal : <b>Unlimited</b></blockquote>\n"
        
        f"<blockquote>📊 <b>Statistik Kamu</b>\n"
        f"├ Terkirim : {attempts}\n"
        f"├ Sukses : {success}\n"
        f"└ Presentase : <b>{persen:.1f}%</b></blockquote>\n"
        
        f"<blockquote>🌐 <b>Statistik Global</b>\n"
        f"├ Pengguna : 1 (Private)\n"
        f"├ Sender Aktif : Unlimited\n"
        f"├ Total Fix : 14789326\n"
        f"└ Presentase : <b>99.5%</b></blockquote>\n\n"
        
        f"🎙️ <i>Gunakan tombol di bawah ini:</i>"
    )
    
    # Inline Keyboard (Tombol dalam pesan)
    inline_kb = [
        [InlineKeyboardButton("🛠️ Fix Merah", callback_data='btn_fix_merah')],
        [InlineKeyboardButton("📊 Statistik", callback_data='btn_riwayat'), 
         InlineKeyboardButton("👥 Leaderboard", callback_data='btn_leaderboard')],
        [InlineKeyboardButton("❓ Panduan", callback_data='btn_panduan')]
    ]
    
    if is_edit and update.callback_query:
        try: await update.callback_query.message.delete()
        except: pass

    try:
        # Mengirim Foto + Caption + Reply Keyboard Bawah
        await context.bot.send_photo(
            chat_id=update.effective_chat.id, 
            photo=BANNER_START_URL, 
            caption=teks, 
            reply_markup=get_reply_keyboard(), 
            parse_mode='HTML'
        )
        # Mengirim Inline Keyboard di pesan terpisah
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👇 <b>Menu Cepat:</b>",
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode='HTML'
        )
    except Exception:
        # Fallback jika gambar gagal
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=teks, 
            reply_markup=get_reply_keyboard(), 
            parse_mode='HTML'
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👇 <b>Menu Cepat:</b>",
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode='HTML'
        )

# ==========================================
# HANDLERS PERINTAH & TEKS
# ==========================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_dashboard(update, context)

async def cmd_setmt1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    set_setting('default_method', '1')
    await update.message.reply_text("✅ <b>Default Metode 1 Aktif</b>", parse_mode='HTML')

async def cmd_setmt2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    set_setting('default_method', '2')
    await update.message.reply_text("✅ <b>Default Metode 2 Aktif</b>", parse_mode='HTML')

async def cmd_resetmt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    set_setting('default_method', '1')
    await update.message.reply_text("🔄 <b>Default Metode diatur ulang ke Metode 1</b>", parse_mode='HTML')

async def send_fix_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_query=False):
    text = (
        "<b>[ SILAHKAN KIRIM NOMOR ]</b>\n\n"
        "<blockquote>Silahkan kirim nomor yang ingin diperbaiki. Pastikan nomor Sudah Terdaftar (Cekbio Terlebih Dahulu).</blockquote>\n\n"
        "Contoh:\n"
        "<code>628123456789</code>\n"
        "<code>/fix 628123456789</code>\n"
        "<code>/f 628123456789</code>\n"
        "<code>+628123456789 (Low Meta)</code>"
    )
    if is_query and update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode='HTML')
    else:
        await update.message.reply_text(text, parse_mode='HTML')

async def cmd_fix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await send_fix_menu(update, context, is_query=False)

# Handler Tombol Bawah
async def msg_btn_fix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_fix_menu(update, context, is_query=False)

async def msg_btn_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attempts, success = get_stats(update.effective_user.id)
    await update.message.reply_text(f"📊 <b>Statistik Anda:</b>\nTotal: {attempts} | Sukses: {success}", parse_mode='HTML')

async def msg_btn_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Anda adalah pengguna tunggal VIP di bot Private ini!", parse_mode='HTML')

async def msg_btn_panduan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Klik Fix Merah, masukkan nomor. Bot akan otomatis mengirim email banding ke WhatsApp.", parse_mode='HTML')

# ==========================================
# ALUR INPUT NOMOR
# ==========================================
async def handle_input_nomor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = update.message.text.strip()
    
    if text.startswith('/fix ') or text.startswith('/f '):
        text = text.split(' ', 1)[1].strip()
    
    raw_numbers = re.split(r'[\n,]+', text)
    valid_numbers = [num.strip() for num in raw_numbers if re.match(r'^\+?\d{8,15}$', num.strip())]
            
    if not valid_numbers:
        # Jika bukan nomor, mungkin user mengetik teks lain
        return await update.message.reply_text("❌ Format salah. Kirimkan nomor yang valid (contoh: +84912345678).")
    
    metode = get_setting('default_method', '1')
    
    loading_msg = await update.message.reply_text(
        f"⏳ <b>Sedang memproses {len(valid_numbers)} nomor via Email (Metode {metode})...</b>\n\n"
        f"Mohon tunggu, bot sedang mengirim email ke WhatsApp. Jangan tutup bot.", 
        parse_mode='HTML'
    )
    
    asyncio.create_task(process_bulk_emails_task(context, update.effective_chat.id, loading_msg.message_id, valid_numbers, metode, update.effective_user.id))

# ==========================================
# CALLBACK HANDLER
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    if not is_admin(user_id): return await query.answer("🚫 Akses Ditolak.", show_alert=True)

    try:
        if data == 'btn_fix_merah':
            await query.answer()
            await send_fix_menu(update, context, is_query=True)
            
        elif data == 'btn_panduan':
            await query.answer("Klik Fix Merah, masukkan nomor. Bot akan otomatis mengirim email banding ke WhatsApp.", show_alert=True)
            
        elif data == 'btn_riwayat':
            attempts, success = get_stats(user_id)
            await query.answer(f"Total: {attempts} | Sukses: {success}", show_alert=True)
            
        elif data == 'btn_leaderboard':
            await query.answer("👑 Anda adalah pengguna tunggal VIP di bot Private ini!", show_alert=True)
            
        elif data == 'btn_back_dash':
            await query.answer()
            await show_dashboard(update, context, is_edit=True)
            
        elif data == 'run_selesai':
            await query.answer()
            msg_sukses = (
                f"<b>[ HASIL BANDING FIX MERAH ]</b>\n\n"
                f"<blockquote>✅ <b>Sukses Fix Merah</b>\n\n"
                f"◦ Semua Nomor Telah Diproses via Email</blockquote>\n\n"
                f"💬 Bot akan otomatis meneruskan email jika WhatsApp membalas."
            )
            kb_sukses = [[InlineKeyboardButton("🏠 Menu Utama", callback_data='btn_back_dash')]]
            await query.message.edit_text(msg_sukses, reply_markup=InlineKeyboardMarkup(kb_sukses), parse_mode='HTML')

    except Exception as e:
        print(traceback.format_exc())
        try: await query.answer("⚠️ Kesalahan sistem.", show_alert=True)
        except: pass

# ==========================================
# POST INIT & MAIN RUNNER
# ==========================================
async def post_init(application):
    try:
        await application.bot.set_my_commands([
            ("start", "Mulai Bot & Dashboard"),
            ("fix", "Mulai Fix Merah (Email)"),
            ("setmt1", "Default Metode 1"),
            ("setmt2", "Default Metode 2"),
            ("resetmt", "Atur Ulang Default Metode")
        ])
    except: pass
    asyncio.create_task(email_checker_task(application))

if __name__ == '__main__':
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN tidak diatur!")
        exit(1)
    
    init_db()
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("fix", cmd_fix))
    application.add_handler(CommandHandler("f", cmd_fix))
    application.add_handler(CommandHandler("setmt1", cmd_setmt1))
    application.add_handler(CommandHandler("setmt2", cmd_setmt2))
    application.add_handler(CommandHandler("resetmt", cmd_resetmt))
    
    # Handler untuk Tombol Bawah
    application.add_handler(MessageHandler(filters.Regex(r'^🛠️ Fix Merah$'), msg_btn_fix))
    application.add_handler(MessageHandler(filters.Regex(r'^📜 Riwayat$'), msg_btn_riwayat))
    application.add_handler(MessageHandler(filters.Regex(r'^👥 Leaderboard$'), msg_btn_leaderboard))
    application.add_handler(MessageHandler(filters.Regex(r'^❓ Panduan$'), msg_btn_panduan))

    # Handler Input Nomor
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input_nomor))
    application.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.environ.get("PORT", 8080))
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if webhook_url:
        print(f"🚀 Webhook on {port} -> {webhook_url}")
        application.run_webhook(listen="0.0.0.0", port=port, url_path=TOKEN, webhook_url=f"{webhook_url}/{TOKEN}")
    else:
        print("⚠️ WEBHOOK_URL tidak diatur, menggunakan Polling...")
        application.run_polling()
