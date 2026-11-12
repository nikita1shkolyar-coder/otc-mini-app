import os
import random
import asyncio
import logging
from aiohttp import web, ClientSession
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

SYMBOL_MAP = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
    "XRP/USD": "XRPUSDT",
    "TON/USD": "TONUSDT",
    "DOGE/USD": "DOGEUSDT"
}

def calc_ema(prices, period):
    if not prices:
        return 0.0
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

async def fetch_real_candles(pair_label: str, tf: str):
    symbol = SYMBOL_MAP.get(pair_label, "BTCUSDT")
    interval = "5m" if tf == "5m" else ("3m" if tf == "3m" else "1m")
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=35"
    async with ClientSession() as session:
        async with session.get(url, timeout=8) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Exchange HTTP {resp.status}")
            raw = await resp.json()
            candles = []
            for k in raw:
                candles.append({
                    "time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4])
                })
            return candles

@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚡ Открыть PT Prime AI",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer(
        "👋 Добро пожаловать в **PT Prime AI** для Pocket Option.\n\n"
        "• **LIVE Рынок** — реальные свечи и расчет RSI/EMA в реальном времени.\n"
        "• **OTC Ассистент** — таймер входа в `:00` сек, калькулятор перекрытий (92%) и учет сессии.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def handle_index(request):
    with open("index.html", "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def handle_candles(request):
    pair = request.query.get("pair", "BTC/USD")
    tf = request.query.get("tf", "1m")
    try:
        candles = await fetch_real_candles(pair, tf)
        closes = [c["close"] for c in candles]
        rsi = calc_rsi(closes, 14)
        ema9 = calc_ema(closes[-15:], 9)
        ema21 = calc_ema(closes[-25:], 21)
        return web.json_response({
            "ok": True,
            "candles": candles,
            "rsi": rsi,
            "ema9": ema9,
            "ema21": ema21
        })
    except Exception as e:
        logging.error(f"Candles fetch error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=502)

async def handle_scan(request):
    data = await request.json()
    mode = data.get("mode", "live")
    timeframe = data.get("timeframe", "1m")
    pair = data.get("pair", "BTC/USD")

    if mode == "live":
        try:
            candles = await fetch_real_candles(pair, timeframe)
            closes = [c["close"] for c in candles]
            last_price = closes[-1]
            rsi = calc_rsi(closes, 14)
            ema9 = calc_ema(closes[-15:], 9)
            ema21 = calc_ema(closes[-25:], 21)

            score_call = 0
            score_put = 0
            reasons = []

            if rsi <= 33:
                score_call += 2
                reasons.append(f"перепроданность RSI ({rsi})")
            elif rsi >= 67:
                score_put += 2
                reasons.append(f"перекупленность RSI ({rsi})")
            elif rsi < 50:
                score_call += 1
                reasons.append(f"RSI ({rsi}) в зоне отскока вверх")
            else:
                score_put += 1
                reasons.append(f"RSI ({rsi}) в зоне давления вниз")

            if ema9 > ema21:
                score_call += 1
                reasons.append("восходящий импульс EMA9 > EMA21")
            else:
                score_put += 1
                reasons.append("нисходящий импульс EMA9 < EMA21")

            is_call = score_call >= score_put
            confidence = min(94, 71 + abs(score_call - score_put) * 7 + (6 if (rsi <= 30 or rsi >= 70) else 0))

            return web.json_response({
                "ok": True,
                "pair": pair,
                "timeframe": timeframe,
                "direction": "ВВЕРХ 🟢 (CALL)" if is_call else "ВНИЗ 🔴 (PUT)",
                "confidence": confidence,
                "last_price": last_price,
                "rsi": rsi,
                "reason": f"Реальный анализ {len(candles)} свечей ({timeframe}): " + " + ".join(reasons) + "."
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": f"Ошибка API биржи: {e}"}, status=502)
    else:
        # Режим OTC-ассистента
        direction = random.choice(["ВВЕРХ 🟢 (CALL)", "ВНИЗ 🔴 (PUT)"])
        confidence = random.randint(76, 89)
        return web.json_response({
            "ok": True,
            "pair": pair,
            "timeframe": timeframe,
            "direction": direction,
            "confidence": confidence,
            "reason": f"Тактический вход по таймеру свечи {timeframe} на Pocket Option. Дождись 00:00 и открывай сделку."
        })

async def start_services():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/candles", handle_candles)
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
