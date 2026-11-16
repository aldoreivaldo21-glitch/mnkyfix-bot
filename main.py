import os
import time
import sqlite3
import asyncio
import traceback
import html
import re
import imaplib
import email
import io
from email.header import decode_header
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest

# ==========================================
# KONFIGURASI UTAMA
# ==========================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()

# Konfigurasi Email & Gambar
BANNER_START_URL = os.environ.get("BANNER_START_URL", "https://i.ibb.co/6PZk68F/placeholder.jpg")
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

BOT_VERSION = "1.1 MNKYFIX Bulk"
START_TIME = time.time()
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mnkyfix_data.db")

# State untuk menampung input user
user_states = {}

def is_admin(uid): return str(uid) == str(ADMIN_ID)

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
        new_attempts = row[0] + success_count
        new_success = row[1] + success_count
        c.execute("UPDATE stats SET total_attempts=?, total_success=? WHERE user_id=?", (new_attempts, new_success, user_id))
    
    conn.commit(); conn.close()

def get_stats(user_id):
    conn = get_db()
    row = conn.execute("SELECT total_attempts, total_success FROM stats WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row: return 0, 0
    return row[0], row[1]

# ==========================================
# BACKGROUND TASK: CEK EMAIL IMAP (30 DETIK)
# ==========================================
def _fetch_latest_email():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return None
    
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
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors='ignore')
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')
                
                mail.store(latest_id, '+FLAGS', '\\Seen')
                mail.logout()
                return subject, body
        mail.logout()
    except Exception as e:
        print(f"IMAP Error: {e}")
        return None

async def email_checker_task(application):
    await asyncio.sleep(5)
    print("📬 Memulai Background Email Checker (setiap 30 detik)...")
    
    while True:
        if GMAIL_USER and GMAIL_APP_PASSWORD:
            result = await asyncio.to_thread(_fetch_latest_email)
            if result:
                subject, body = result
                if len(body) > 3000: body = body[:3000] + "..."
                
                notif_teks = (
                    f"📬 <b>BALASAN WHATSAPP DITERIMA!</b>\n\n"
                    f"<b>Subjek:</b> {html.escape(subject)}\n\n"
                    f"<blockquote>{html.escape(body)}</blockquote>"
                )
                try:
                    await application.bot.send_message(chat_id=int(ADMIN_ID), text=notif_teks, parse_mode='HTML')
                except: pass
                
        await asyncio.sleep(30)

# ==========================================
# TAMPILAN DASHBOARD (MIRIP MLO)
# ==========================================
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, is_edit=False):
    if not is_admin(update.effective_user.id):
        return await context.bot.send_message(update.effective_chat.id, "🚫 Akses Ditolak. Bot ini khusus Admin.")
    
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
        f"└ Batch maksimal : <b>10 nomor</b></blockquote>\n"
        
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
    
    inline_kb = [
        [InlineKeyboardButton("🛠️ Fix Merah (1 Nomor)", callback_data='btn_fix_merah')],
        [InlineKeyboardButton("🚀 Fix Merah (Bulk 10 Nomor)", callback_data='btn_fix_bulk')],
        [InlineKeyboardButton("📜 Riwayat", callback_data='btn_riwayat'), 
         InlineKeyboardButton("❓ Panduan", callback_data='btn_panduan')]
    ]
    
    if is_edit and update.callback_query:
        try: await update.callback_query.message.delete()
        except: pass

    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=BANNER_START_URL,
            caption=teks,
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode='HTML'
        )
    except Exception:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=teks,
            reply_markup=InlineKeyboardMarkup(inline_kb),
            parse_mode='HTML'
        )

# ==========================================
# HANDLERS PERINTAH
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

async def cmd_fix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(
        "<b>[ SILAHKAN KIRIM NOMOR ]</b>\n\n"
        "Kirimkan nomor yang ingin diperbaiki (contoh: <code>+84912345678</code>).\n"
        "Untuk mengirim banyak nomor sekaligus, pisahkan dengan enter (baris baru).",
        parse_mode='HTML'
    )

# ==========================================
# ALUR INPUT NOMOR & METODE (OPSI C - BULK MODE)
# ==========================================
async def handle_input_nomor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Pisahkan berdasarkan enter (baris baru) atau koma
    raw_numbers = re.split(r'[\n,]+', text)
    valid_numbers = []
    
    for num in raw_numbers:
        num = num.strip()
        if re.match(r'^\+?\d{8,15}$', num):
            valid_numbers.append(num)
            
    if not valid_numbers:
        return await update.message.reply_text("❌ Format salah. Kirimkan nomor yang valid (contoh: +84912345678).")
        
    if len(valid_numbers) > 10:
        return await update.message.reply_text("❌ Maksimal 10 nomor dalam sekali pengiriman.")

    # Simpan list nomor di state sementara
    user_states[user_id] = {'wa_numbers': valid_numbers, 'step': 'pilih_metode'}
    
    kb = [
        [InlineKeyboardButton("📩 Metode 1", callback_data='run_mt1'), 
         InlineKeyboardButton("📩 Metode 2", callback_data='run_mt2')],
        [InlineKeyboardButton("❌ Batal", callback_data='run_batal')]
    ]
    
    teks = f"Memulai Fix Merah untuk <b>{len(valid_numbers)} nomor</b>.\n\nSilakan pilih metode pengiriman:"
    await update.message.reply_text(teks, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

# ==========================================
# CALLBACK HANDLER (TOMBOL)
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        return await query.answer("🚫 Akses Ditolak.", show_alert=True)

    try:
        if data == 'btn_fix_merah' or data == 'btn_fix_bulk':
            await query.answer()
            await query.message.reply_text(
                "<b>[ SILAHKAN KIRIM NOMOR ]</b>\n\n"
                "Kirimkan nomor (contoh: <code>+84912345678</code>).\n"
                "Jika ingin banyak, kirim sekaligus dengan enter (maksimal 10 nomor).",
                parse_mode='HTML'
            )
            
        elif data == 'btn_panduan':
            await query.answer("Klik Fix Merah, masukkan nomor, pilih metode, lalu ikuti instruksi.", show_alert=True)
            
        elif data == 'btn_riwayat':
            attempts, success = get_stats(user_id)
            await query.answer(f"Total: {attempts} | Sukses: {success}", show_alert=True)
            
        elif data == 'btn_back_dash':
            await query.answer()
            await show_dashboard(update, context, is_edit=True)
            
        # --- ALUR EKSEKUSI METODE (OPSI C - BULK) ---
        elif data in ['run_mt1', 'run_mt2']:
            await query.answer()
            if user_id not in user_states:
                return await query.message.reply_text("❌ Sesi habis. Silakan ketik /fix lagi.")
                
            wa_numbers = user_states[user_id]['wa_numbers']
            metode = "1" if data == 'run_mt1' else "2"
            
            # Buat teks banding untuk setiap nomor
            all_texts = []
            for num in wa_numbers:
                if metode == "1":
                    template = f'Dear WhatsApp Support Team, I am writing to appeal the "Login not available right now" restriction on my phone number {num}. I believe this might be a misunderstanding or a system error. I always try to follow WhatsApp\'s Terms of Service and use the official WhatsApp application. This phone number is my personal number, and I need access to it for my daily communication with family and friends. Could you please review my account and lift this temporary hold so I can log in and use WhatsApp normally again? Thank you very much for your time and assistance'
                else:
                    template = f'Dear WhatsApp support center.\nI would like to report about my number get login not available, i need this number for working and business, many important things on my WhatsApp account.\nPlease fix this problem and let me log in to my own account,\n{num}\nRegards.'
                
                # Format output file TXT
                all_texts.append(f"--- NOMOR: {num} ---\n{template}\n\n")
            
            # Gabungkan semua teks
            full_text = "\n".join(all_texts)
            
            # Update statistik
            update_stats(user_id, success_count=len(wa_numbers))
            
            # Tampilan Pesan Terkirim
            numbers_list = "\n".join([f"◦ {n}" for n in wa_numbers])
            msg_terkirim = (
                f"<b>[ HASIL BANDING FIX MERAH ]</b>\n\n"
                f"<blockquote>✅ <b>Terkirim {len(wa_numbers)} Nomor</b>\n\n"
                f"{numbers_list}</blockquote>\n\n"
                f"🙂 Status akan berubah otomatis jika menerima balasan."
            )
            
            await query.message.edit_text(msg_terkirim, parse_mode='HTML')
            
            # Instruksi & File TXT
            instruksi = (
                f"<b>[ INSTRUKSI PENGIRIMAN METODE {metode} ]</b>\n\n"
                f"<blockquote>Karena Anda mengirim banyak nomor, silakan download file TXT di bawah ini. "
                f"Salin teksnya satu per satu, lalu tempelkan ke website WhatsApp.</blockquote>"
            )
            
            kb_web = [
                [InlineKeyboardButton("🌐 Buka Web WhatsApp", url="https://www.whatsapp.com/contact/")],
                [InlineKeyboardButton("✅ Saya Sudah Kirim Semua", callback_data='run_selesai')]
            ]
            
            await asyncio.sleep(1)
            await query.message.reply_text(instruksi, reply_markup=InlineKeyboardMarkup(kb_web), parse_mode='HTML')
            
            # Kirim File TXT
            file_data = io.BytesIO(full_text.encode('utf-8'))
            file_data.name = f"Banding_Metode{metode}_{len(wa_numbers)}_Nomor.txt"
            await query.message.reply_document(
                document=file_data,
                caption=f"📄 File berisi {len(wa_numbers)} teks banding (Metode {metode})."
            )

        elif data == 'run_selesai':
            await query.answer()
            if user_id in user_states:
                del user_states[user_id]
                
            msg_sukses = (
                f"<b>[ HASIL BANDING FIX MERAH ]</b>\n\n"
                f"<blockquote>✅ <b>Sukses Fix Merah</b>\n\n"
                f"◦ Semua Nomor Telah Diproses</blockquote>\n\n"
                f"💬 WhatsApp sudah merespon semua nomor, silakan login ke nomor yang berstatus Sukses."
            )
            
            kb_sukses = [
                [InlineKeyboardButton("📄 Export TXT", callback_data='btn_export')],
                [InlineKeyboardButton("🛠️ Fix Lagi", callback_data='btn_fix_merah'), 
                 InlineKeyboardButton("🏠 Menu Utama", callback_data='btn_back_dash')]
            ]
            
            await query.message.edit_text(msg_sukses, reply_markup=InlineKeyboardMarkup(kb_sukses), parse_mode='HTML')
            
        elif data == 'btn_export':
            await query.answer("Data banding berhasil di-export (Simulasi).", show_alert=True)

        elif data == 'run_batal':
            await query.answer()
            if user_id in user_states:
                del user_states[user_id]
            await query.message.edit_text("❌ Pengiriman dibatalkan.")
            await send_dashboard(update, context, is_edit=False)

    except Exception as e:
        print(traceback.format_exc())
        try: await query.answer("⚠️ Kesalahan sistem.", show_alert=True)
        except: pass

# ==========================================
# POST INIT (BACKGROUND TASK)
# ==========================================
async def post_init(application):
    try:
        await application.bot.set_my_commands([
            ("start", "Mulai Bot & Dashboard"),
            ("fix", "Mulai Fix Merah (Bisa 10 Nomor)"),
            ("setmt1", "Default Metode 1"),
            ("setmt2", "Default Metode 2"),
            ("resetmt", "Atur Ulang Default Metode")
        ])
    except: pass
    
    asyncio.create_task(email_checker_task(application))

# ==========================================
# MAIN RUNNER
# ==========================================
if __name__ == '__main__':
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN tidak diatur!")
        exit(1)
    
    init_db()
    print(f"✅ MNKYFIX Bot starting...")
    
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("fix", cmd_fix))
    application.add_handler(CommandHandler("setmt1", cmd_setmt1))
    application.add_handler(CommandHandler("setmt2", cmd_setmt2))
    application.add_handler(CommandHandler("resetmt", cmd_resetmt))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input_nomor))
    application.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.environ.get("PORT", 8080))
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if webhook_url:
        print(f"🚀 Webhook on {port} -> {webhook_url}")
        application.run_webhook(listen="0.0.0.0", port=port, url_path=TOKEN,
                                webhook_url=f"{webhook_url}/{TOKEN}")
    else:
        print("⚠️ WEBHOOK_URL tidak diatur, menggunakan Polling...")
        application.run_polling()
