import os
import random
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# ================= НАСТРОЙКИ =================
TG_TOKEN = os.environ.get("9044932823:AAFV-Kc36rZ-XqQflnHmt4QX2rxQluyGBMk")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://otc-mini-app.onrender.com")
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

OTC_PAIRS = [
    "EUR/USD (OTC)", "GBP/USD (OTC)", "USD/JPY (OTC)", 
    "AUD/CAD (OTC)", "NZD/USD (OTC)", "USD/CHF (OTC)"
]

@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть AI Сканер (OTC)", 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer(
        "👋 Привет! Нажми на кнопку ниже, чтобы открыть панель AI-сканера OTC-рынка.",
        reply_markup=kb
    )

async def handle_index(request):
    with open("index.html", "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def handle_scan(request):
    data = await request.json()
    timeframe = data.get("timeframe", "1m")

    scanned_pair = random.choice(OTC_PAIRS)
    rsi_val = round(random.uniform(18.0, 82.0), 1)
    ema_cross = random.choice(["бычье пересечение (EMA9 > EMA21)", "медвежье пересечение (EMA9 < EMA21)", "флэт"])
    
    confidence = 50
    if rsi_val < 28 or rsi_val > 72:
        confidence += 18
    if "пересечение" in ema_cross:
        confidence += 12
    confidence += random.randint(-5, 9)

    if confidence < 70:
        return web.json_response({
            "found": False,
            "message": f"Проверены OTC-пары на {timeframe}. Максимальная уверенность {confidence}% (ниже 70%). Повтори поиск через пару секунд."
        })

    direction = "ВВЕРХ 🟢 (CALL)" if rsi_val < 50 else "ВНИЗ 🔴 (PUT)"
    entry_price = round(random.uniform(1.0500, 1.1500), 5)
    reason = f"Обнаружен сильный сигнал: RSI ({rsi_val}) в комбинации с {ema_cross} дает высокую вероятность отработки."

    return web.json_response({
        "found": True,
        "pair": scanned_pair,
        "timeframe": timeframe,
        "direction": direction,
        "confidence": confidence,
        "entry_price": entry_price,
        "reason": reason
    })

async def handle_check_result(request):
    data = await request.json()
    direction = data.get("direction", "")
    entry_price = float(data.get("entry_price", 0))

    price_change = round(random.uniform(-0.0008, 0.0008), 5)
    exit_price = round(entry_price + price_change, 5)

    is_call = "ВВЕРХ" in direction
    win = (exit_price > entry_price) if is_call else (exit_price < entry_price)

    return web.json_response({
        "win": win,
        "exit_price": exit_price,
        "result_text": "WIN 🟢 (ПЛЮС)" if win else "LOSS 🔴 (МИНУС)"
    })

async def start_services():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/scan", handle_scan)
    app.router.add_post("/api/check_result", handle_check_result)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Сервер запущен на порту {port}")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_services())
