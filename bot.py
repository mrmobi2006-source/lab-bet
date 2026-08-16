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


async def safe_edit(msg, text, parse_mode="HTML"):
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except Exception:
        try:
            await msg.edit_text(text)
        except Exception:
            pass


async def send_screenshot(page_or_frame, context, chat_id, caption, prefix="ss"):
    try:
        path = f"/tmp/{prefix}_{chat_id}.png"
        if hasattr(page_or_frame, 'screenshot'):
            await page_or_frame.screenshot(path=path, full_page=True)
        else:
            await page_or_frame.screenshot(path=path)
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=open(path, "rb"),
            caption=caption
        )
    except Exception as e:
        print(f"Screenshot error: {e}")


async def find_terminal_frame(page, max_wait=60):
    terminal_frame = None
    for i in range(max_wait):
        for frame in page.frames:
            url = frame.url.lower()
            if "cloudshell" in url or "terminal" in url or "shell" in url:
                terminal_frame = frame
                break
        if terminal_frame:
            break
        await asyncio.sleep(1)
    return terminal_frame


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
        "5️⃣ إرسال روابط VLESS + صور تأكيد\n\n"
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
        await safe_edit(msg, text)

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
            # Step 1
            await edit("🔄 [1/6] جاري فتح رابط Qwiklabs...")
            await page.goto(link, wait_until="networkidle", timeout=90000)
            await asyncio.sleep(5)
            await send_screenshot(page, context, chat_id, "📸 [1/6] صفحة Qwiklabs بعد الفتح", "step1")

            # Step 2
            await edit("🔄 [2/6] التحقق من صفحة الترحيب...")
            page_text = await page.inner_text("body")

            if "Couldn\\'t sign you in" in page_text or "couldn\\'t sign you in" in page_text.lower():
                await edit("❌ Google حظر تسجيل الدخول من هذا الخادم.\nجرب تشغيل البوت محلياً.")
                await send_screenshot(page, context, chat_id, "❌ Google حظر الدخول", "error")
                await browser.close()
                return

            understand_clicked = False
            for btn_text in ["I understand", "Accept", "Agree", "Continue", "Start Lab", "Start lab"]:
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
                await edit("✅ تم الضغط على الزر، جاري التوجيه...")
            else:
                await edit("⏳ في انتظار التوجيه التلقائي...")

            await asyncio.sleep(10)
            current_url = page.url
            await edit(f"🔄 [2/6] الرابط الحالي: <code>{current_url[:80]}...</code>")
            await send_screenshot(page, context, chat_id, "📸 [2/6] بعد الضغط على الزر", "step2")

            if "welcome" in current_url.lower() or "signin" in current_url.lower() or "start-lab" in current_url.lower():
                try:
                    all_btns = await page.query_selector_all("button, [role='button'], input[type='submit'], a[href*='start']")
                    for btn in all_btns:
                        text = await btn.inner_text()
                        if any(x in text.lower() for x in ["understand", "accept", "agree", "continue", "next", "start", "launch"]):
                            await btn.click()
                            await asyncio.sleep(5)
                            break
                except Exception:
                    pass
                await send_screenshot(page, context, chat_id, "📸 [2/6] بعد محاولة إضافية", "step2b")

            # Step 3
            await edit("🔄 [3/6] جاري الانتقال إلى Google Cloud Console...")
            await page.goto("https://console.cloud.google.com/home/dashboard", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(5)
            await send_screenshot(page, context, chat_id, "📸 [3/6] Google Cloud Console", "step3")

            # Step 4
            await edit("🔄 [4/6] جاري فتح Google Cloud Shell...")
            await page.goto(
                "https://shell.cloud.google.com/?hl=en_US&theme=dark&authuser=0&fromcloudshell=true&show=terminal",
                wait_until="networkidle", timeout=120000
            )
            await asyncio.sleep(10)
            await send_screenshot(page, context, chat_id, "📸 [4/6] Cloud Shell (قبل OAuth)", "step4a")

            page_text = await page.inner_text("body")
            oauth_handled = False

            if "Authorize" in page_text or "Sign in" in page_text or "accountchooser" in page.url or "signin" in page.url.lower():
                await edit("🔄 [4/6] جاري التعامل مع صفحة OAuth/Sign-in...")

                for btn_text in ["Authorize", "Allow", "Sign in", "Continue", "Accept", "Next"]:
                    try:
                        btn = await page.wait_for_selector(
                            f'button:has-text("{btn_text}"), [role="button"]:has-text("{btn_text}"), input[type="submit"][value="{btn_text}"]',
                            timeout=3000
                        )
                        if btn:
                            await btn.click()
                            await asyncio.sleep(5)
                            oauth_handled = True
                            break
                    except Exception:
                        continue

                if not oauth_handled:
                    try:
                        accounts = await page.query_selector_all('[data-email], [data-identifier], .d2laZc, [data-test-id="account-list"] > div')
                        if accounts:
                            await accounts[0].click()
                            await asyncio.sleep(5)
                            oauth_handled = True
                    except Exception:
                        pass

                if not oauth_handled:
                    try:
                        email_input = await page.wait_for_selector('input[type="email"], input[name="identifier"]', timeout=5000)
                        if email_input:
                            await edit("⚠️ [4/6] Google يطلب بريد إلكتروني. هذا يعني أن الجلسة غير مسجلة.\n"
                                       "❌ لا يمكن المتابعة تلقائياً — يحتاج تسجيل دخول يدوي.")
                            await send_screenshot(page, context, chat_id, "❌ يحتاج تسجيل دخول يدوي", "error_oauth")
                            await browser.close()
                            return
                    except Exception:
                        pass

                await asyncio.sleep(8)
                await send_screenshot(page, context, chat_id, "📸 [4/6] Cloud Shell (بعد OAuth)", "step4b")

            # Step 5
            await edit("🔄 [5/6] في انتظار استعداد Cloud Shell Terminal...")
            terminal_frame = await find_terminal_frame(page, max_wait=60)

            if not terminal_frame:
                await edit("❌ [5/6] لم يُعثر على Cloud Shell Terminal بعد 60 ثانية.\n"
                           "ربما لم يُفتح Cloud Shell أو هناك مشكلة في الجلسة.")
                await send_screenshot(page, context, chat_id, "❌ لم يُعثر على Terminal", "error_terminal")
                await browser.close()
                return

            await edit("✅ [5/6] تم العثور على Terminal! جاري التحضير...")
            await asyncio.sleep(5)
            await send_screenshot(terminal_frame, context, chat_id, "📸 [5/6] Terminal جاهز", "step5")

            # Step 6
            await edit("🔄 [6/6] جاري تنفيذ سكربت VLESS...\n⏳ ~2-3 دقائق")

            script = """mkdir -p ~/mobo_tunnel && cd ~/mobo_tunnel && \
REGION="europe-west10" && \
SERVICE_NAME="mobo-tunnel-ws" && \
PROJECT_ID=$(gcloud config get-value project) && \
SNI="www.youtube.com" && \
UUID=$(python3 -c "import uuid; print(uuid.uuid4())") && \
cat > start.sh <<'EOF'
#!/bin/sh
cat > /tmp/config.json <<'INNEREOF'
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "port": 8080,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "PLACEHOLDER_UUID", "flow": ""}],
      "decryption": "none",
      "fallbacks": []
    },
    "streamSettings": {
      "network": "ws",
      "wsSettings": {"path": "/"}
    },
    "sniffing": {
      "enabled": true,
      "destOverride": ["http", "tls"]
    }
  }],
  "outbounds": [{
    "protocol": "freedom",
    "settings": {}
  }]
}
INNEREOF
sed -i "s/PLACEHOLDER_UUID/$UUID/g" /tmp/config.json
/usr/bin/xray -config /tmp/config.json
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

            typed = False
            terminal_selectors = [
                "textarea",
                ".xterm-helper-textarea",
                "[aria-label*='Terminal']",
                "[class*='terminal'] textarea",
                "xterm-helper-textarea",
                "[data-test-id='terminal-input']",
            ]

            for sel in terminal_selectors:
                try:
                    elem = await terminal_frame.query_selector(sel)
                    if elem:
                        await terminal_frame.click(sel)
                        await asyncio.sleep(0.5)
                        await terminal_frame.type(sel, script, delay=3)
                        typed = True
                        break
                except Exception as e:
                    print(f"Selector {sel} failed: {e}")
                    continue

            if not typed:
                try:
                    script_escaped = script.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$').replace('"', '\\"')
                    js_code = """
                        const ta = document.querySelector('textarea') || 
                                   document.querySelector('.xterm-helper-textarea') ||
                                   document.querySelector('[class*="terminal"] textarea');
                        if (ta) {
                            ta.focus();
                            ta.value = `""" + script_escaped + """`;
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    """
                    await terminal_frame.evaluate(js_code)
                    typed = True
                except Exception as e:
                    print(f"Evaluate fallback failed: {e}")

            if not typed:
                await edit("❌ [6/6] لم أتمكن من الكتابة في Terminal بأي طريقة.")
                await send_screenshot(terminal_frame, context, chat_id, "❌ فشل الكتابة في Terminal", "error_type")
                await browser.close()
                return

            await asyncio.sleep(1)
            try:
                await terminal_frame.press("textarea", "Enter")
            except Exception:
                try:
                    await terminal_frame.evaluate("document.querySelector('textarea').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}))")
                except Exception:
                    pass

            await edit("🔄 [6/6] في انتظار اكتمال النشر...\n⏳ ~2-3 دقائق")
            await asyncio.sleep(90)
            await send_screenshot(terminal_frame, context, chat_id, "📸 [6/6] Terminal أثناء التنفيذ", "step6_mid")
            await asyncio.sleep(60)

            page_text = ""
            try:
                page_text = await terminal_frame.content()
            except Exception:
                try:
                    page_text = await page.content()
                except Exception:
                    pass

            url_match = re.search(r'URL:([^\s<]+)', page_text)
            uuid_match = re.search(r'UUID:([^\s<]+)', page_text)
            cdn_match = re.search(r'CDN:(vless://[^\s<]+)', page_text)
            direct_match = re.search(r'DIRECT:(vless://[^\s<]+)', page_text)

            await send_screenshot(terminal_frame, context, chat_id, "📸 [6/6] النتيجة النهائية", "step6_final")

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
            else:
                await edit("⚠️ تم التنفيذ لكن لم أتمكن من استخراج الروابط تلقائياً.\n"
                           "تحقق من صور Terminal أعلاه للحصول على النتائج.")

        except PlaywrightTimeout as e:
            await edit(f"❌ <b>انتهى الوقت:</b> {str(e)}")
            try:
                await send_screenshot(page, context, chat_id, f"❌ Timeout: {str(e)}", "error_timeout")
            except Exception:
                pass
        except Exception as e:
            await edit(f"❌ <b>حدث خطأ:</b> {str(e)}")
            try:
                await send_screenshot(page, context, chat_id, f"❌ Error: {str(e)}", "error_general")
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
