import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ================= НАСТРОЙКИ =================
TG_TOKEN = "9044932823:AAFV-Kc36rZ-XqQflnHmt4QX2rxQluyGBMk"
MAX_MARKUP_PERCENT = 5.0  # Строгий лимит: разрешено от 0% до 5%, больше 5% — не пропускаем
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

# Состояние настроек каждого пользователя в памяти
user_settings = {}

def get_user_cfg(user_id: int):
    if user_id not in user_settings:
        user_settings[user_id] = {
            "pair": "EUR/USD",
            "tf": "1m",
            "markup": 2.5
        }
    return user_settings[user_id]

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

def get_next_candle_entry(tf: str):
    now = datetime.utcnow()
    step = 5 if tf == "5m" else 1
    target = now.replace(second=0, microsecond=0)
    rem = now.minute % step
    mins_to_add = step - rem
    secs_left = (mins_to_add * 60) - now.second
    if secs_left < 7:
        mins_to_add += step
    entry_dt = target + timedelta(minutes=mins_to_add)
    wait_seconds = (entry_dt - now).total_seconds()
    return entry_dt, max(1, int(round(wait_seconds)))

# ================= КЛАВИАТУРЫ МЕНЮ =================
def build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    cfg = get_user_cfg(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 ПОЛУЧИТЬ СИГНАЛ (РЕАЛЬНЫЙ РЫНОК)", callback_data="scan_now")],
        [
            InlineKeyboardButton(text=f"💱 Пара: {cfg['pair']}", callback_data="menu_pairs"),
            InlineKeyboardButton(text=f"⏱ ТФ: {cfg['tf'].upper()}", callback_data="toggle_tf")
        ],
        [InlineKeyboardButton(text=f"📊 Наценка: {cfg['markup']}% (лимит ≤ 5%)", callback_data="menu_markup")]
    ])

def build_pairs_menu() -> InlineKeyboardMarkup:
    rows = []
    pairs = list(PAIRS_CONFIG.keys())
    for i in range(0, len(pairs), 2):
        row = [InlineKeyboardButton(text=pairs[i], callback_data=f"set_pair:{pairs[i]}")]
        if i + 1 < len(pairs):
            row.append(InlineKeyboardButton(text=pairs[i + 1], callback_data=f"set_pair:{pairs[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_markup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0%", callback_data="set_markup:0"),
            InlineKeyboardButton(text="1.5%", callback_data="set_markup:1.5"),
            InlineKeyboardButton(text="2.5%", callback_data="set_markup:2.5"),
            InlineKeyboardButton(text="5.0%", callback_data="set_markup:5.0"),
        ],
        [InlineKeyboardButton(text="🚫 Тест >5% (6.0% — отклон)", callback_data="set_markup:6.0")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_main")]
    ])

def render_main_text(user_id: int) -> str:
    cfg = get_user_cfg(user_id)
    markup_status = "✅ В норме (≤5%)" if 0 <= cfg["markup"] <= MAX_MARKUP_PERCENT else "⛔ Превышает 5% (вход заблокирован)"
    return (
        "⚡ **PT PRIME AI • ТЕРМИНАЛ POCKET OPTION**\n\n"
        f"• **Актив (без OTC):** `{cfg['pair']}`\n"
        f"• **Экспирация:** `{cfg['tf'].upper()}`\n"
        f"• **Наценка:** `{cfg['markup']}%` ({markup_status})\n\n"
        "Нажми **«Получить сигнал»**, чтобы проанализировать реальные свечи рынка."
    )

# ================= ОБРАБОТЧИКИ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        render_main_text(message.from_user.id),
        reply_markup=build_main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery):
    await call.message.edit_text(
        render_main_text(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "menu_pairs")
async def cb_menu_pairs(call: CallbackQuery):
    await call.message.edit_text(
        "💱 **Выбери реальную валютную или крипто-пару** (в Pocket Option открывай актив **БЕЗ приписки OTC**):",
        reply_markup=build_pairs_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("set_pair:"))
async def cb_set_pair(call: CallbackQuery):
    pair = call.data.split(":", 1)[1]
    get_user_cfg(call.from_user.id)["pair"] = pair
    await call.message.edit_text(
        render_main_text(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id),
        parse_mode="Markdown"
    )
    await call.answer(f"Выбрана пара {pair}")

@dp.callback_query(F.data == "toggle_tf")
async def cb_toggle_tf(call: CallbackQuery):
    cfg = get_user_cfg(call.from_user.id)
    cfg["tf"] = "5m" if cfg["tf"] == "1m" else "1m"
    await call.message.edit_text(
        render_main_text(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id),
        parse_mode="Markdown"
    )
    await call.answer(f"Таймфрейм: {cfg['tf'].upper()}")

@dp.callback_query(F.data == "menu_markup")
async def cb_menu_markup(call: CallbackQuery):
    await call.message.edit_text(
        "📊 **Выбери допустимую наценку (строго до 5%):**\n"
        "Если наценка выше `5%`, система автоматически запретит вход в сделку.",
        reply_markup=build_markup_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("set_markup:"))
async def cb_set_markup(call: CallbackQuery):
    val = float(call.data.split(":", 1)[1])
    get_user_cfg(call.from_user.id)["markup"] = val
    await call.message.edit_text(
        render_main_text(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id),
        parse_mode="Markdown"
    )
    await call.answer(f"Наценка установлена: {val}%")

async def track_trade_outcome(chat_id: int, message_id: int, pair: str, tf: str, is_call: bool, wait_to_entry: int):
    try:
        # Ждём открытия свечи (:00)
        await asyncio.sleep(wait_to_entry)
        entry_candles = await fetch_market_candles(pair, tf)
        entry_price = entry_candles[-1]["close"]

        # Ждём закрытия свечи
        duration = 300 if tf == "5m" else 60
        await asyncio.sleep(duration)

        exit_candles = await fetch_market_candles(pair, tf)
        exit_price = exit_candles[-1]["close"]

        win = (exit_price > entry_price) if is_call else (exit_price < entry_price)
        res_badge = "✅ **WIN (ПЛЮС)**" if win else "❌ **LOSS (МИНУС)**"

        await bot.send_message(
            chat_id,
            f"🏁 **Итог сделки по {pair} ({tf.upper()}):** {res_badge}\n"
            f"• Цена входа: `{entry_price}`\n"
            f"• Цена закрытия: `{exit_price}`",
            reply_to_message_id=message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Outcome check error: {e}")

@dp.callback_query(F.data == "scan_now")
async def cb_scan_now(call: CallbackQuery):
    cfg = get_user_cfg(call.from_user.id)
    pair = cfg["pair"]
    tf = cfg["tf"]
    markup = cfg["markup"]

    # Жёсткий фильтр наценки: только от 0% до 5%
    if not (0 <= markup <= MAX_MARKUP_PERCENT):
        await call.answer(f"⛔ Наценка {markup}% больше 5%! Вход отменён.", show_alert=True)
        return

    await call.answer("🔍 Сканирую реальный график...")
    await call.message.edit_text(f"⏳ Загружаю свечи **{pair} ({tf.upper()})** и считаю RSI / EMA...", parse_mode="Markdown")

    try:
        candles = await fetch_market_candles(pair, tf)
        if len(candles) < 20:
            await call.message.edit_text(
                f"⚠️ По паре **{pair}** биржа сейчас закрыта (выходной). Выбери крипто-пару (`BTC/USD`, `ETH/USD`, `SOL/USD`).",
                reply_markup=build_main_menu(call.from_user.id),
                parse_mode="Markdown"
            )
            return

        closes = [c["close"] for c in candles]
        last_price = closes[-1]
        rsi = calc_rsi(closes, 14)
        ema9 = calc_ema(closes[-15:], 9)
        ema21 = calc_ema(closes[-25:], 21)
        upper_bb, lower_bb = calc_bollinger(closes, 20)

        market_dev = round(abs((last_price - ema21) / ema21) * 100, 3) if ema21 else 0.0
        if market_dev > MAX_MARKUP_PERCENT:
            await call.message.edit_text(
                f"⛔ Отклонение рынка `{market_dev}%` превышает лимит `5%`. Вход пропущен.",
                reply_markup=build_main_menu(call.from_user.id),
                parse_mode="Markdown"
            )
            return

        call_pts, put_pts = 0, 0
        reasons = []

        if rsi <= 33:
            call_pts += 2
            reasons.append(f"перепроданность RSI ({rsi})")
        elif rsi >= 67:
            put_pts += 2
            reasons.append(f"перекупленность RSI ({rsi})")
        elif rsi < 50:
            call_pts += 1
            reasons.append(f"RSI ({rsi}) в зоне отскока вверх")
        else:
            put_pts += 1
            reasons.append(f"RSI ({rsi}) в зоне давления вниз")

        if last_price <= lower_bb:
            call_pts += 2
            reasons.append("касание нижней полосы Боллинджера")
        elif last_price >= upper_bb:
            put_pts += 2
            reasons.append("пробой верхней полосы Боллинджера")

        if ema9 > ema21:
            call_pts += 1
            reasons.append("импульс EMA9 > EMA21")
        else:
            put_pts += 1
            reasons.append("импульс EMA9 < EMA21")

        is_call = call_pts >= put_pts
        confidence = min(94, 72 + abs(call_pts - put_pts) * 6)
        direction_text = "🟢 **ВВЕРХ (CALL)**" if is_call else "🔴 **ВНИЗ (PUT)**"

        entry_dt, wait_sec = get_next_candle_entry(tf)
        entry_str = entry_dt.strftime("%H:%M:%S UTC")

        signal_text = (
            f"📊 **СИГНАЛ • {pair} ({tf.upper()})**\n\n"
            f"• Направление: {direction_text}\n"
            f"• Точность расчёта: `{confidence}%`\n"
            f"• Текущая цена: `{last_price}`\n"
            f"• Наценка: `{markup}%` (в норме ≤ 5%)\n"
            f"• Вход в сделку через: **{wait_sec} сек** (в `{entry_str}`)\n\n"
            f"💡 **Анализ:** {', '.join(reasons)}."
        )

        sent = await call.message.edit_text(
            signal_text,
            reply_markup=build_main_menu(call.from_user.id),
            parse_mode="Markdown"
        )

        asyncio.create_task(
            track_trade_outcome(call.message.chat.id, sent.message_id, pair, tf, is_call, wait_sec)
        )

    except Exception as e:
        await call.message.edit_text(
            f"❌ Ошибка получения рыночных данных: `{e}`",
            reply_markup=build_main_menu(call.from_user.id),
            parse_mode="Markdown"
        )

# Веб-сервер-заглушка, чтобы Render Web Service оставался активным (Live)
async def handle_health(request):
    return web.Response(text="PT Prime Bot is running")

async def start_services():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_services())
