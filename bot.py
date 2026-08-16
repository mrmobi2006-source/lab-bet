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

WAITING_LINK = 0
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚀 بدء إنشاء VLESS", callback_data="start_vless")],
    ]
    await update.message.reply_text(
        "<b>👋 مرحباً بك في VLESS Auto Deployer!</b>\n\n"
        "هذا البوت يقوم بـ:\n"
        "1️⃣ فتح رابط Qwiklabs مباشرة\n"
        "2️⃣ الضغط على 'I understand' إذا ظهرت\n"
        "3️⃣ فتح Google Cloud Shell\n"
        "4️⃣ نشر Xray/VLESS على Cloud Run\n"
        "5️⃣ إرسال روابط VLESS إليك\n\n"
        "⚠️ <b>تحذير</b>: أرسل رابط Qwiklabs فقط — لا يحتاج بريد أو كلمة مرور!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def start_vless(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📎 أرسل لي <b>رابط Qwiklabs</b> (Google SSO link).\n\n"
        "مثال:\n"
        "<code>https://www.skills.google/google_sso?fallback=...</code>",
        parse_mode="HTML"
    )
    return WAITING_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if "skills.google" not in link and "qwiklabs" not in link:
        await update.message.reply_text("❌ الرابط غير صالح. أرسل رابط Qwiklabs الصحيح.")
        return WAITING_LINK

    context.user_data["qwiklabs_link"] = link
    msg = await update.message.reply_text("⏳ جاري فتح رابط Qwiklabs مباشرة...")
    context.user_data["status_msg"] = msg

    asyncio.create_task(run_automation(update, context))
    return ConversationHandler.END

async def run_automation(update, context):
    link = context.user_data["qwiklabs_link"]
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
                "--disable-blink-features=AutomationControlled",
            ]
        )
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)
        page = await ctx.new_page()

        try:
            # ── 1. فتح رابط Qwiklabs مباشرة ──
            await edit("🔄 [1/5] جاري فتح رابط Qwiklabs...")
            await page.goto(link, wait_until="networkidle", timeout=90000)
            await asyncio.sleep(5)

            # ── 2. التحقق من صفحة "I understand" ──
            await edit("🔄 [2/5] التحقق من صفحة الترحيب...")
            page_text = await page.inner_text("body")

            # Check for errors
            if "Couldn\'t sign you in" in page_text:
                await edit("❌ Google حظر تسجيل الدخول من هذا الخادم.<br>جرب تشغيل البوت محلياً.")
                await browser.close()
                return

            # Click "I understand" if present
            understand_clicked = False
            for btn_text in ["I understand", "Accept", "Agree", "Continue"]:
                try:
                    btn = await page.wait_for_selector(
                        f'button:has-text("{btn_text}"), [role="button"]:has-text("{btn_text}"), input[type="submit"][value="{btn_text}"]',
                        timeout=5000
                    )
                    if btn:
                        await btn.click()
                        understand_clicked = True
                        await asyncio.sleep(4)
                        break
                except Exception:
                    continue

            if understand_clicked:
                await edit("✅ تم الضغط على 'I understand'، جاري التوجيه...")
            else:
                await edit("⏳ في انتظار التوجيه التلقائي...")

            # Wait for redirect to complete
            await asyncio.sleep(8)

            # Check current URL
            current_url = page.url
            await edit(f"🔄 [3/5] الرابط الحالي: {current_url[:60]}...")

            # If still on welcome page, try clicking any button
            if "welcome" in current_url.lower() or "signin" in current_url.lower():
                try:
                    all_btns = await page.query_selector_all("button, [role='button'], input[type='submit']")
                    for btn in all_btns:
                        text = await btn.inner_text()
                        if any(x in text.lower() for x in ["understand", "accept", "agree", "continue", "next"]):
                            await btn.click()
                            await asyncio.sleep(5)
                            break
                except Exception:
                    pass

            # ── 3. الانتقال إلى Cloud Console ──
            await edit("🔄 [3/5] جاري الانتقال إلى Google Cloud Console...")
            await page.goto("https://console.cloud.google.com/home/dashboard", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(5)

            # ── 4. فتح Cloud Shell ──
            await edit("🔄 [4/5] جاري فتح Google Cloud Shell...")
            await page.goto(
                "https://shell.cloud.google.com/?hl=en_US&theme=dark&authuser=0&fromcloudshell=true&show=terminal",
                wait_until="networkidle", timeout=120000
            )
            await asyncio.sleep(10)

            # Handle OAuth / Authorize page if it appears
            page_text = await page.inner_text("body")
            if "Authorize" in page_text or "Sign in" in page_text or "accountchooser" in page.url:
                await edit("🔄 [4/5] جاري التعامل مع صفحة OAuth...")
                # Try to click any authorize/signin button
                for btn_text in ["Authorize", "Allow", "Sign in", "Continue", "Accept"]:
                    try:
                        btn = await page.wait_for_selector(
                            f'button:has-text("{btn_text}"), [role="button"]:has-text("{btn_text}"), input[type="submit"][value="{btn_text}"]',
                            timeout=3000
                        )
                        if btn:
                            await btn.click()
                            await asyncio.sleep(5)
                            break
                    except Exception:
                        continue
                # If account chooser, try clicking the first account
                try:
                    accounts = await page.query_selector_all('[data-email], [data-identifier], .d2laZc')
                    if accounts:
                        await accounts[0].click()
                        await asyncio.sleep(5)
                except Exception:
                    pass

            await asyncio.sleep(10)

            await edit("🔄 [4/5] في انتظار استعداد Cloud Shell...")
            await asyncio.sleep(20)

            # Find terminal iframe
            terminal_frame = None
            for _ in range(10):
                for frame in page.frames:
                    if "cloudshell" in frame.url or "terminal" in frame.url:
                        terminal_frame = frame
                        break
                if terminal_frame:
                    break
                await asyncio.sleep(3)

            # ── 5. تنفيذ السكربت ──
            await edit("🔄 [5/5] جاري تنفيذ سكربت VLESS...<br>⏳ ~2-3 دقائق")

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

            # FIX: Use page.keyboard instead of terminal_frame.keyboard
            if terminal_frame:
                try:
                    # Focus the terminal frame first
                    await terminal_frame.evaluate("document.querySelector('textarea').focus()")
                    await asyncio.sleep(1)
                    await terminal_frame.type("textarea", script, delay=5)
                except Exception:
                    # Fallback: type in main page
                    await page.keyboard.type(script, delay=5)
            else:
                await page.keyboard.type(script, delay=5)

            await asyncio.sleep(1)
            await page.keyboard.press("Enter")

            await edit("🔄 [5/5] في انتظار اكتمال النشر...<br>⏳ ~2 دقيقة")
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
                await edit("⚠️ تم التنفيذ لكن لم أتمكن من استخراج الروابط. تحقق من الصورة.")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(screenshot_path, "rb"),
                    caption="📸 تحقق من النتائج"
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

async def cancel(update, context):
    await update.message.reply_text("❌ تم إلغاء العملية.")
    return ConversationHandler.END

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_vless, pattern="^start_vless$")],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
