import os
import asyncio
import re
from urllib.parse import unquote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, ContextTypes, filters
)
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

WAITING_LINK, WAITING_EMAIL, WAITING_PASSWORD, RUNNING = range(4)
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚀 بدء إنشاء VLESS", callback_data="start_vless")],
        [InlineKeyboardButton("📖 كيفية الاستخدام", callback_data="help")]
    ]
    await update.message.reply_text(
        "<b>👋 مرحباً بك في VLESS Auto Deployer!</b>\n\n"
        "هذا البوت يقوم بـ:\n"
        "1️⃣ الدخول إلى رابط Qwiklabs\n"
        "2️⃣ فتح Google Cloud Shell\n"
        "3️⃣ نشر Xray/VLESS على Cloud Run\n"
        "4️⃣ إرسال روابط VLESS إليك\n\n"
        "⚠️ <b>تحذير</b>: البيانات تُستخدم فقط لأتمتة المتصفح ولا تُخزن.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "<b>📖 كيفية الاستخدام:</b>\n\n"
        "1. اضغط 'بدء إنشاء VLESS'\n"
        "2. أرسل رابط Qwiklabs (SSO link)\n"
        "3. أرسل بريدك وكلمة المرور\n"
        "4. انتظر حتى يكتمل النشر\n\n"
        "⚡️ إذا طلب Google رمز تحقق، سيتوقف البوت ويطلب منك إكماله يدوياً، ثم أرسل /done",
        parse_mode="HTML"
    )

async def start_vless(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📎 أرسل لي <b>رابط Qwiklabs</b> (Google SSO link).",
        parse_mode="HTML"
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if "skills.google" not in link and "qwiklabs" not in link:
        await update.message.reply_text("❌ الرابط غير صالح. أرسل رابط Qwiklabs الصحيح.")
        return WAITING_LINK
    context.user_data["qwiklabs_link"] = link
    email_match = re.search(r'Email=([^&]+)', link)
    if email_match:
        email = unquote(email_match.group(1))
        context.user_data["email"] = email
        await update.message.reply_text(
            f"✅ تم استلام الرابط!\n📧 البريد المكتشف: <code>{email}</code>\n\n🔑 أرسل <b>كلمة المرور</b>:",
            parse_mode="HTML"
        )
        return WAITING_PASSWORD
    else:
        await update.message.reply_text("📧 أرسل <b>بريد Qwiklabs</b>:", parse_mode="HTML")
        return WAITING_EMAIL

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("🔑 أرسل <b>كلمة المرور</b>:", parse_mode="HTML")
    return WAITING_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.delete()
    except Exception:
        pass
    context.user_data["password"] = update.message.text.strip()
    msg = await update.message.reply_text("⏳ جاري بدء العملية...\n🌐 سأفتح المتصفح وأدخل إلى Qwiklabs الآن.")
    context.user_data["status_msg"] = msg
    asyncio.create_task(run_automation(update, context))
    return RUNNING

async def run_automation(update, context):
    link = context.user_data["qwiklabs_link"]
    email = context.user_data["email"]
    password = context.user_data["password"]
    chat_id = update.effective_chat.id
    msg = context.user_data["status_msg"]

    async def edit(text):
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            try:
                await msg.edit_text(text)
            except Exception:
                pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = await ctx.new_page()

        try:
            await edit("🔄 [1/7] جاري فتح رابط Qwiklabs...")
            await page.goto(link, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(4)

            await edit("🔄 [2/7] جاري تسجيل الدخول إلى Google...")
            await page.wait_for_selector('input[type="email"]', timeout=15000)
            await page.fill('input[type="email"]', email)
            await page.click("button:has-text('Next'), #identifierNext")
            await asyncio.sleep(3)
            await page.wait_for_selector('input[type="password"]', timeout=15000)
            await page.fill('input[type="password"]', password)
            await page.click("button:has-text('Next'), #passwordNext")
            await asyncio.sleep(5)

            current_url = page.url
            if "challenge" in current_url or "signin" in current_url:
                await asyncio.sleep(5)
                new_url = page.url
                if "challenge" in new_url or "signin" in new_url:
                    await edit(
                        "🔐 <b>تم اكتشاف طلب تحقق إضافي!</b>\n\n"
                        "1. أكمل التحقق يدوياً في المتصفح\n"
                        "2. بعد الانتهاء، أرسل /done هنا\n\n"
                        "⏳ في انتظارك..."
                    )
                    context.user_data["page"] = page
                    context.user_data["browser"] = browser
                    context.user_data["ctx"] = ctx
                    return

            await edit("🔄 [3/7] جاري الانتقال إلى Google Cloud Console...")
            await page.goto("https://console.cloud.google.com/home/dashboard", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(5)

            await edit("🔄 [4/7] جاري فتح Google Cloud Shell...")
            await page.goto(
                "https://shell.cloud.google.com/?hl=en_US&theme=dark&authuser=0&fromcloudshell=true&show=terminal",
                wait_until="networkidle", timeout=120000
            )
            await asyncio.sleep(15)

            await edit("🔄 [5/7] في انتظار استعداد Cloud Shell...")
            await asyncio.sleep(20)

            terminal_frame = None
            for _ in range(10):
                for frame in page.frames:
                    if "cloudshell" in frame.url or "terminal" in frame.url:
                        terminal_frame = frame
                        break
                if terminal_frame:
                    break
                await asyncio.sleep(3)

            await edit("🔄 [6/7] جاري تنفيذ سكربت VLESS...\n⏳ قد يستغرق 2-3 دقائق.")

            script = """mkdir -p ~/mobo_tunnel && cd ~/mobo_tunnel && \
REGION="europe-west10" && \
SERVICE_NAME="mobo-tunnel-ws" && \
PROJECT_ID=$(gcloud config get-value project) && \
SNI="www.youtube.com" && \
UUID=$(python3 -c "import uuid; print(uuid.uuid4())") && \
cat > start.sh <<'EOF'
#!/bin/sh
cat > /tmp/config.json <<CONF
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "port": ${PORT:-8080},
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "${UUID}", "level": 0 }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "ws",
      "wsSettings": { "path": "/" }
    },
    "sniffing": {
      "enabled": true,
      "destOverride": ["http","tls"]
    }
  }],
  "outbounds": [
    {
      "protocol": "freedom",
      "settings": { "domainStrategy": "UseIPv4" },
      "tag": "direct"
    },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [{
      "type": "field",
      "ip": ["geoip:private"],
      "outboundTag": "block"
    }]
  }
}
CONF
exec xray run -config /tmp/config.json
EOF
chmod +x start.sh && \
cat > Dockerfile <<'DOCKEREOF'
FROM teddysun/xray:latest
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 8080
CMD ["/start.sh"]
DOCKEREOF

echo "===DEPLOY_START===" && \
gcloud run deploy $SERVICE_NAME --source . --platform managed --region $REGION --allow-unauthenticated --port 8080 --cpu 4 --memory 2Gi --cpu-boost --concurrency 1000 --min-instances 1 --max-instances 4 --timeout 3600 --project $PROJECT_ID --quiet && \
RUN_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format 'value(status.url)' | sed 's|https://||' | tr -d '[:space:]') && \
VLESS_CDN="vless://${UUID}@${SNI}:443?encryption=none&security=tls&type=ws&host=${RUN_URL}&path=%2F&sni=${SNI}#MOBO_TURBO" && \
VLESS_DIRECT="vless://${UUID}@${RUN_URL}:443?encryption=none&security=tls&type=ws&path=%2F&sni=${RUN_URL}#MOBO_DIRECT" && \
echo "===RESULTS===" && \
echo "URL:${RUN_URL}" && \
echo "UUID:${UUID}" && \
echo "CDN:${VLESS_CDN}" && \
echo "DIRECT:${VLESS_DIRECT}" && \
echo "===END==="
"""

            if terminal_frame:
                try:
                    await terminal_frame.type("textarea", script, delay=10)
                except Exception:
                    pass
                await asyncio.sleep(1)
                await terminal_frame.keyboard.press("Enter")
            else:
                await page.keyboard.type(script, delay=10)
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")

            await edit("🔄 [7/7] في انتظار اكتمال النشر...\n⏳ ~2 دقيقة")
            await asyncio.sleep(90)

            page_text = ""
            if terminal_frame:
                try:
                    page_text = await terminal_frame.content()
                except Exception:
                    page_text = await page.content()
            else:
                page_text = await page.content()

            url_match = re.search(r'URL:([^\s<]+)', page_text)
            uuid_match = re.search(r'UUID:([^\s<]+)', page_text)
            cdn_match = re.search(r'CDN:(vless://[^\s<]+)', page_text)
            direct_match = re.search(r'DIRECT:(vless://[^\s<]+)', page_text)

            screenshot_path = f"/tmp/result_{chat_id}.png"
            await page.screenshot(path=screenshot_path, full_page=True)

            if cdn_match and direct_match:
                run_url = url_match.group(1) if url_match else "غير معروف"
                uuid_val = uuid_match.group(1) if uuid_match else "غير معروف"
                vless_cdn = cdn_match.group(1)
                vless_direct = direct_match.group(1)
                result = (
                    f"✅ <b>تم النشر بنجاح!</b>\n\n"
                    f"🌐 الرابط: <code>https://{run_url}</code>\n"
                    f"🔑 UUID: <code>{uuid_val}</code>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡️ <b>TURBO CDN:</b>\n"
                    f"<code>{vless_cdn}</code>\n\n"
                    f"🚀 <b>DIRECT:</b>\n"
                    f"<code>{vless_direct}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
                await edit(result)
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(screenshot_path, "rb"),
                    caption="📸 لقطة شاشة من Cloud Shell"
                )
            else:
                await edit("⚠️ تم تنفيذ السكربت لكن لم أتمكن من استخراج الروابط تلقائياً.\nتحقق من لقطة الشاشة أدناه.")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(screenshot_path, "rb"),
                    caption="📸 تحقق من النتائج في الصورة"
                )

        except PlaywrightTimeout as e:
            await edit(f"❌ <b>انتهى الوقت:</b> {str(e)}")
            try:
                await page.screenshot(path=f"/tmp/error_{chat_id}.png")
                await context.bot.send_photo(chat_id=chat_id, photo=open(f"/tmp/error_{chat_id}.png", "rb"))
            except Exception:
                pass
        except Exception as e:
            await edit(f"❌ <b>حدث خطأ:</b> {str(e)}")
            try:
                await page.screenshot(path=f"/tmp/error_{chat_id}.png")
                await context.bot.send_photo(chat_id=chat_id, photo=open(f"/tmp/error_{chat_id}.png", "rb"))
            except Exception:
                pass
        finally:
            await browser.close()

async def done_2fa(update, context):
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("✅ تم التأكيد، جاري المتابعة...")
    context.user_data["status_msg"] = msg
    page = context.user_data.get("page")
    browser = context.user_data.get("browser")
    ctx = context.user_data.get("ctx")

    if not page or page.is_closed():
        await msg.edit_text("❌ المتصفح مغلق. أعد المحاولة من البداية.")
        return ConversationHandler.END

    async def edit(text):
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            try:
                await msg.edit_text(text)
            except Exception:
                pass

    try:
        await edit("🔄 [3/7] جاري الانتقال إلى Google Cloud Console...")
        await page.goto("https://console.cloud.google.com/home/dashboard", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)

        await edit("🔄 [4/7] جاري فتح Google Cloud Shell...")
        await page.goto(
            "https://shell.cloud.google.com/?hl=en_US&theme=dark&authuser=0&fromcloudshell=true&show=terminal",
            wait_until="networkidle", timeout=120000
        )
        await asyncio.sleep(15)

        await edit("🔄 [5/7] في انتظار استعداد Cloud Shell...")
        await asyncio.sleep(20)

        terminal_frame = None
        for _ in range(10):
            for frame in page.frames:
                if "cloudshell" in frame.url or "terminal" in frame.url:
                    terminal_frame = frame
                    break
            if terminal_frame:
                break
            await asyncio.sleep(3)

        await edit("🔄 [6/7] جاري تنفيذ سكربت VLESS...\n⏳ ~2-3 دقائق")

        script = """mkdir -p ~/mobo_tunnel && cd ~/mobo_tunnel && \
REGION="europe-west10" && \
SERVICE_NAME="mobo-tunnel-ws" && \
PROJECT_ID=$(gcloud config get-value project) && \
SNI="www.youtube.com" && \
UUID=$(python3 -c "import uuid; print(uuid.uuid4())") && \
cat > start.sh <<'EOF'
#!/bin/sh
cat > /tmp/config.json <<CONF
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "port": ${PORT:-8080},
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "${UUID}", "level": 0 }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "ws",
      "wsSettings": { "path": "/" }
    },
    "sniffing": {
      "enabled": true,
      "destOverride": ["http","tls"]
    }
  }],
  "outbounds": [
    {
      "protocol": "freedom",
      "settings": { "domainStrategy": "UseIPv4" },
      "tag": "direct"
    },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [{
      "type": "field",
      "ip": ["geoip:private"],
      "outboundTag": "block"
    }]
  }
}
CONF
exec xray run -config /tmp/config.json
EOF
chmod +x start.sh && \
cat > Dockerfile <<'DOCKEREOF'
FROM teddysun/xray:latest
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 8080
CMD ["/start.sh"]
DOCKEREOF

echo "===DEPLOY_START===" && \
gcloud run deploy $SERVICE_NAME --source . --platform managed --region $REGION --allow-unauthenticated --port 8080 --cpu 4 --memory 2Gi --cpu-boost --concurrency 1000 --min-instances 1 --max-instances 4 --timeout 3600 --project $PROJECT_ID --quiet && \
RUN_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format 'value(status.url)' | sed 's|https://||' | tr -d '[:space:]') && \
VLESS_CDN="vless://${UUID}@${SNI}:443?encryption=none&security=tls&type=ws&host=${RUN_URL}&path=%2F&sni=${SNI}#MOBO_TURBO" && \
VLESS_DIRECT="vless://${UUID}@${RUN_URL}:443?encryption=none&security=tls&type=ws&path=%2F&sni=${RUN_URL}#MOBO_DIRECT" && \
echo "===RESULTS===" && \
echo "URL:${RUN_URL}" && \
echo "UUID:${UUID}" && \
echo "CDN:${VLESS_CDN}" && \
echo "DIRECT:${VLESS_DIRECT}" && \
echo "===END==="
"""

        if terminal_frame:
            try:
                await terminal_frame.type("textarea", script, delay=10)
            except Exception:
                pass
            await asyncio.sleep(1)
            await terminal_frame.keyboard.press("Enter")
        else:
            await page.keyboard.type(script, delay=10)
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")

        await edit("🔄 [7/7] في انتظار اكتمال النشر...\n⏳ ~2 دقيقة")
        await asyncio.sleep(90)

        page_text = ""
        if terminal_frame:
            try:
                page_text = await terminal_frame.content()
            except Exception:
                page_text = await page.content()
        else:
            page_text = await page.content()

        url_match = re.search(r'URL:([^\s<]+)', page_text)
        uuid_match = re.search(r'UUID:([^\s<]+)', page_text)
        cdn_match = re.search(r'CDN:(vless://[^\s<]+)', page_text)
        direct_match = re.search(r'DIRECT:(vless://[^\s<]+)', page_text)

        screenshot_path = f"/tmp/result_{chat_id}.png"
        await page.screenshot(path=screenshot_path, full_page=True)

        if cdn_match and direct_match:
            run_url = url_match.group(1) if url_match else "غير معروف"
            uuid_val = uuid_match.group(1) if uuid_match else "غير معروف"
            vless_cdn = cdn_match.group(1)
            vless_direct = direct_match.group(1)
            result = (
                f"✅ <b>تم النشر بنجاح!</b>\n\n"
                f"🌐 الرابط: <code>https://{run_url}</code>\n"
                f"🔑 UUID: <code>{uuid_val}</code>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡️ <b>TURBO CDN:</b>\n"
                f"<code>{vless_cdn}</code>\n\n"
                f"🚀 <b>DIRECT:</b>\n"
                f"<code>{vless_direct}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            await edit(result)
            await context.bot.send_photo(chat_id=chat_id, photo=open(screenshot_path, "rb"), caption="📸 لقطة شاشة من Cloud Shell")
        else:
            await edit("⚠️ تم التنفيذ لكن لم أتمكن من استخراج الروابط. تحقق من الصورة.")
            await context.bot.send_photo(chat_id=chat_id, photo=open(screenshot_path, "rb"), caption="📸 تحقق من النتائج")

    except Exception as e:
        await edit(f"❌ خطأ: {str(e)}")
    finally:
        await browser.close()
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("❌ تم إلغاء العملية.")
    return ConversationHandler.END

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_vless, pattern="^start_vless$")],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            RUNNING: [CommandHandler("done", done_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    application.add_handler(conv_handler)
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
