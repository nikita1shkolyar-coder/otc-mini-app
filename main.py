import os
import asyncio
import logging
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# ================= НАСТРОЙКИ =================
TG_TOKEN = "9044932823:AAFV-Kc36rZ-XqQflnHmt4QX2rxQluyGBMk"
WEBAPP_URL = "https://otc-mini-app.onrender.com"
MAX_MARKUP_PERCENT = 5.0  # Строгий лимит: разрешено от 0% до 5%, если > 5% — не пропускаем
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

PAIRS_CONFIG = {
    "EUR/USD": {"source": "yahoo", "symbol": "EURUSD=X"},
    "GBP/USD": {"source": "yahoo", "symbol": "GBPUSD=X"},
    "USD/JPY": {"source": "yahoo", "symbol": "USDJPY=X"},
    "AUD/CAD": {"source": "yahoo", "symbol": "AUDCAD=X"},
    "USD/CHF": {"source": "yahoo", "symbol": "USDCHF=X"},
    "BTC/USD": {"source": "binance", "symbol": "BTCUSDT"},
    "ETH/USD": {"source": "binance", "symbol": "ETHUSDT"},
    "SOL/USD": {"source": "binance", "symbol": "SOLUSDT"},
    "XRP/USD": {"source": "binance", "symbol": "XRPUSDT"},
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

def calc_bollinger(prices, period=20):
    if len(prices) < period:
        p = prices[-1]
        return p, p
    window = prices[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = variance ** 0.5
    return sma + 2 * std, sma - 2 * std

async def fetch_market_candles(pair: str, tf: str):
    cfg = PAIRS_CONFIG.get(pair, PAIRS_CONFIG["EUR/USD"])
    interval = "5m" if tf == "5m" else "1m"

    async with ClientSession() as session:
        if cfg["source"] == "binance":
            url = f"https://api.binance.com/api/v3/klines?symbol={cfg['symbol']}&interval={interval}&limit=40"
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Binance HTTP {resp.status}")
                raw = await resp.json()
                return [
                    {
                        "time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4])
                    }
                    for k in raw
                ]
        else:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{cfg['symbol']}?interval={interval}&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, headers=headers, timeout=8) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Market HTTP {resp.status}")
                data = await resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                quote = result["indicators"]["quote"][0]
                candles = []
                for i in range(len(timestamps)):
                    o, h, l, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
                    if o is not None and c is not None:
                        candles.append({
                            "time": int(timestamps[i]) * 1000,
                            "open": float(o),
                            "high": float(h),
                            "low": float(l),
                            "close": float(c)
                        })
                return candles[-40:]

@dp.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Открыть PT Prime Live Scanner",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer(
        "📊 **PT Prime AI • Реальные рыночные пары (Pocket Option)**\n\n"
        "• Прямой поток реальных свечей Forex (пн–пт) и Крипты (24/7).\n"
        "• Фильтр наценки/отклонения до **5%** включительно.\n"
        "• Расчёт **RSI (14)**, **EMA 9/21** и **Bollinger Bands** в реальном времени.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

async def handle_index(request):
    with open("index.html", "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")

async def handle_candles(request):
    pair = request.query.get("pair", "EUR/USD")
    tf = request.query.get("tf", "1m")
    try:
        candles = await fetch_market_candles(pair, tf)
        closes = [c["close"] for c in candles]
        rsi = calc_rsi(closes, 14)
        return web.json_response({"ok": True, "candles": candles, "rsi": rsi})
    except Exception as e:
        logging.error(f"Candles error ({pair}): {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=502)

async def handle_scan(request):
    data = await request.json()
    pair = data.get("pair", "EUR/USD")
    tf = data.get("timeframe", "1m")
    user_markup = float(data.get("markup", 0.0))

    # Проверка лимита наценки: разрешено только от 0% до 5% включительно
    if not (0 <= user_markup <= MAX_MARKUP_PERCENT):
        return web.json_response({
            "ok": False,
            "error": f"Наценка {user_markup}% превышает допустимый лимит в {MAX_MARKUP_PERCENT}%! Вход отклонён."
        })

    try:
        candles = await fetch_market_candles(pair, tf)
        if len(candles) < 20:
            return web.json_response({"ok": False, "error": "Рынок по этой паре сейчас закрыт (выходной). Выбери крипто-пару."})

        closes = [c["close"] for c in candles]
        last_price = closes[-1]
        rsi = calc_rsi(closes, 14)
        ema9 = calc_ema(closes[-15:], 9)
        ema21 = calc_ema(closes[-25:], 21)
        upper_bb, lower_bb = calc_bollinger(closes, 20)

        # Дополнительно проверяем рыночное отклонение цены от EMA21 (не более 5%)
        market_deviation_pct = round(abs((last_price - ema21) / ema21) * 100, 3) if ema21 else 0.0
        if market_deviation_pct > MAX_MARKUP_PERCENT:
            return web.json_response({
                "ok": False,
                "error": f"Аномальный импульс рынка ({market_deviation_pct}% > {MAX_MARKUP_PERCENT}%). Вход пропущен для безопасности."
            })

        call_points = 0
        put_points = 0
        reasons = []

        if rsi <= 33:
            call_points += 2
            reasons.append(f"перепроданность RSI ({rsi})")
        elif rsi >= 67:
            put_points += 2
            reasons.append(f"перекупленность RSI ({rsi})")
        elif rsi < 50:
            call_points += 1
            reasons.append(f"RSI ({rsi}) в зоне отскока вверх")
        else:
            put_points += 1
            reasons.append(f"RSI ({rsi}) в зоне давления вниз")

        if last_price <= lower_bb:
            call_points += 2
            reasons.append("касание нижней полосы Боллинджера")
        elif last_price >= upper_bb:
            put_points += 2
            reasons.append("пробой верхней полосы Боллинджера")

        if ema9 > ema21:
            call_points += 1
            reasons.append("тренд EMA9 > EMA21")
        else:
            put_points += 1
            reasons.append("тренд EMA9 < EMA21")

        is_call = call_points >= put_points
        diff = abs(call_points - put_points)
        confidence = min(94, 72 + diff * 6)

        return web.json_response({
            "ok": True,
            "pair": pair,
            "timeframe": tf,
            "markup": user_markup,
            "direction": "ВВЕРХ 🟢 (CALL)" if is_call else "ВНИЗ 🔴 (PUT)",
            "confidence": confidence,
            "rsi": rsi,
            "reason": f"Наценка {user_markup}% в норме (≤{MAX_MARKUP_PERCENT}%). Анализ {len(candles)} свечей {pair} ({tf}): " + ", ".join(reasons) + "."
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Нет свежих котировок (возможно, биржа закрыта): {e}"})

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
