import os
import asyncio
import logging
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# ================= НАСТРОЙКИ =================
TG_TOKEN = "9044932823:AAFV-Kc36rZ-XqQflnHmt4QX2rxQluyGBMk"
MRKT_TOKEN = os.environ.get("MRKT_TOKEN", "")
MRKT_API_URL = "https://api.tgmrkt.io/api/v1/gifts/saling"
MAX_MARKUP_LIMIT = 5.0  # Жесткий лимит: не выше 5% от флора
NANO = 1_000_000_000
ITEMS_PER_PAGE = 10
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Полный список коллекций Telegram NFT Gifts (от бюджетных до редких)
COLLECTIONS = [
    "Homemade Cake",
    "Lol Pop",
    "Candy Cane",
    "Jingle Bells",
    "Santa Hat",
    "Ginger Cookie",
    "Winter Wreath",
    "Snow Globe",
    "Snow Mittens",
    "Cookie Heart",
    "B-Day Candle",
    "Desk Calendar",
    "Lunar Snake",
    "Jester Hat",
    "Party Sparkler",
    "Spiced Wine",
    "Hypno Lollipop",
    "Witch Hat",
    "Hex Pot",
    "Evil Eye",
    "Berry Box",
    "Bunny Muffin",
    "Star Notepad",
    "Jelly Bunny",
    "Sakura Flower",
    "Top Hat",
    "Love Potion",
    "Love Candle",
    "Hanging Star",
    "Crystal Ball",
    "Eternal Rose",
    "Trapped Heart",
    "Skull Flower",
    "Flying Broom",
    "Mad Pumpkin",
    "Sharp Tongue",
    "Voodo Doll",
    "Record Player",
    "Electric Skull",
    "Tamagotchi",
    "Genie Lamp",
    "Diamond Ring",
    "Ion Gem",
    "Astral Shard",
    "Mini Oscar",
    "Loot Bag",
    "Kissed Frog",
    "Scared Cat",
    "Signet Ring",
    "Swiss Watch",
    "Vintage Cigar",
    "Magic Potion",
    "Perfume Bottle",
    "Precious Peach",
    "Durov's Cap",
    "Plush Pepe"
]

user_state = {}

def get_cfg(user_id: int):
    if user_id not in user_state:
        user_state[user_id] = {
            "collection": "Homemade Cake",
            "budget": 5.0,
            "markup": 5.0,
            "page": 0,
            "awaiting_budget": False
        }
    return user_state[user_id]

async def fetch_mrkt_lots(collection_name: str, count: int = 30):
    if not MRKT_TOKEN:
        raise RuntimeError("Не задан MRKT_TOKEN в переменных окружения сервера.")

    headers = {
        "Authorization": MRKT_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "collectionNames": [collection_name],
        "ordering": "Price",
        "lowToHigh": True,
        "count": count,
        "cursor": ""
    }

    async with ClientSession() as session:
        async with session.post(MRKT_API_URL, json=payload, headers=headers, timeout=10) as resp:
            if resp.status == 401:
                raise RuntimeError("Токен MRKT_TOKEN устарел (HTTP 401). Обнови токен из DevTools.")
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Ошибка API MRKT ({resp.status}): {text[:120]}")
            data = await resp.json()
            if isinstance(data, list):
                return data
            return data.get("gifts") or data.get("items") or data.get("data") or []

def extract_price_ton(item: dict) -> float:
    raw = item.get("price") or item.get("salePrice") or 0
    val = float(raw)
    return round(val / NANO, 4) if val > 100_000 else round(val, 4)

# ================= МЕНЮ БЕЗ ЭМОДЗИ =================
def build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    cfg = get_cfg(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ПОИСК ЛОТОВ НА MRKT", callback_data="scan_mrkt")],
        [
            InlineKeyboardButton(text=f"Коллекция: {cfg['collection']}", callback_data="menu_col:0"),
            InlineKeyboardButton(text=f"Бюджет: {cfg['budget']} TON", callback_data="menu_budget")
        ],
        [InlineKeyboardButton(text=f"Макс. наценка: +{cfg['markup']}% от флора (лимит 5%)", callback_data="menu_markup")]
    ])

def build_collections_menu(page: int = 0) -> InlineKeyboardMarkup:
    total_pages = (len(COLLECTIONS) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start = page * ITEMS_PER_PAGE
    chunk = COLLECTIONS[start:start + ITEMS_PER_PAGE]

    rows = []
    for i in range(0, len(chunk), 2):
        row = [InlineKeyboardButton(text=chunk[i], callback_data=f"set_col:{chunk[i]}")]
        if i + 1 < len(chunk):
            row.append(InlineKeyboardButton(text=chunk[i + 1], callback_data=f"set_col:{chunk[i + 1]}"))
        rows.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="< Пред.", callback_data=f"menu_col:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="След. >", callback_data=f"menu_col:{page + 1}"))
    rows.append(nav_row)

    rows.append([InlineKeyboardButton(text="Назад в меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def build_budget_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 TON", callback_data="set_budget:1"),
            InlineKeyboardButton(text="2 TON", callback_data="set_budget:2"),
            InlineKeyboardButton(text="5 TON", callback_data="set_budget:5"),
        ],
        [
            InlineKeyboardButton(text="10 TON", callback_data="set_budget:10"),
            InlineKeyboardButton(text="25 TON", callback_data="set_budget:25"),
            InlineKeyboardButton(text="50 TON", callback_data="set_budget:50"),
        ],
        [
            InlineKeyboardButton(text="100 TON", callback_data="set_budget:100"),
            InlineKeyboardButton(text="250 TON", callback_data="set_budget:250"),
        ],
        [InlineKeyboardButton(text="Ввести свой бюджет в TON", callback_data="custom_budget")],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ])

def build_markup_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0% (только флор)", callback_data="set_markup:0"),
            InlineKeyboardButton(text="2%", callback_data="set_markup:2"),
            InlineKeyboardButton(text="3.5%", callback_data="set_markup:3.5"),
            InlineKeyboardButton(text="5% (макс.)", callback_data="set_markup:5"),
        ],
        [InlineKeyboardButton(text="Назад", callback_data="back_main")]
    ])

def render_dashboard(user_id: int) -> str:
    cfg = get_cfg(user_id)
    return (
        "MRKT NFT GIFTS — ПАРСЕР ЛОТОВ\n\n"
        f"Коллекция: {cfg['collection']}\n"
        f"Бюджет: до {cfg['budget']} TON\n"
        f"Допустимая наценка от флора: до +{cfg['markup']}% (максимум 5%)\n\n"
        "Нажмите «ПОИСК ЛОТОВ НА MRKT» для проверки предложений."
    )

# ================= ОБРАБОТЧИКИ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    get_cfg(message.from_user.id)["awaiting_budget"] = False
    await message.answer(
        render_dashboard(message.from_user.id),
        reply_markup=build_main_menu(message.from_user.id)
    )

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@dp.callback_query(F.data == "back_main")
async def cb_back(call: CallbackQuery):
    get_cfg(call.from_user.id)["awaiting_budget"] = False
    await call.message.edit_text(
        render_dashboard(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id)
    )
    await call.answer()

@dp.callback_query(F.data.startswith("menu_col:"))
async def cb_menu_col(call: CallbackQuery):
    page = int(call.data.split(":", 1)[1])
    get_cfg(call.from_user.id)["page"] = page
    await call.message.edit_text(
        "Выберите коллекцию подарков (от бюджетных на 1 стр. до редких):",
        reply_markup=build_collections_menu(page)
    )
    await call.answer()

@dp.callback_query(F.data.startswith("set_col:"))
async def cb_set_col(call: CallbackQuery):
    col = call.data.split(":", 1)[1]
    get_cfg(call.from_user.id)["collection"] = col
    await call.message.edit_text(
        render_dashboard(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id)
    )
    await call.answer(f"Выбрано: {col}")

@dp.callback_query(F.data == "menu_budget")
async def cb_menu_budget(call: CallbackQuery):
    await call.message.edit_text(
        "Выберите максимальный бюджет на подарок (в TON):",
        reply_markup=build_budget_menu()
    )
    await call.answer()

@dp.callback_query(F.data.startswith("set_budget:"))
async def cb_set_budget(call: CallbackQuery):
    val = float(call.data.split(":", 1)[1])
    cfg = get_cfg(call.from_user.id)
    cfg["budget"] = val
    cfg["awaiting_budget"] = False
    await call.message.edit_text(
        render_dashboard(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id)
    )
    await call.answer(f"Бюджет: {val} TON")

@dp.callback_query(F.data == "custom_budget")
async def cb_custom_budget(call: CallbackQuery):
    get_cfg(call.from_user.id)["awaiting_budget"] = True
    await call.message.edit_text("Введите числом ваш максимальный бюджет в TON (например: 3.5 или 15):")
    await call.answer()

@dp.message(F.text)
async def handle_custom_budget_input(message: Message):
    cfg = get_cfg(message.from_user.id)
    if not cfg.get("awaiting_budget"):
        return
    try:
        val = float(message.text.replace(",", ".").strip())
        if val <= 0:
            raise ValueError
        cfg["budget"] = round(val, 2)
        cfg["awaiting_budget"] = False
        await message.answer(
            render_dashboard(message.from_user.id),
            reply_markup=build_main_menu(message.from_user.id)
        )
    except ValueError:
        await message.answer("Некорректное значение. Введите положительное число в TON (например: 4.5):")

@dp.callback_query(F.data == "menu_markup")
async def cb_menu_markup(call: CallbackQuery):
    await call.message.edit_text(
        "Выберите максимальную наценку от флора коллекции (не более 5%):",
        reply_markup=build_markup_menu()
    )
    await call.answer()

@dp.callback_query(F.data.startswith("set_markup:"))
async def cb_set_markup(call: CallbackQuery):
    val = float(call.data.split(":", 1)[1])
    if val > MAX_MARKUP_LIMIT:
        val = MAX_MARKUP_LIMIT
    get_cfg(call.from_user.id)["markup"] = val
    await call.message.edit_text(
        render_dashboard(call.from_user.id),
        reply_markup=build_main_menu(call.from_user.id)
    )
    await call.answer(f"Макс. наценка: +{val}%")

@dp.callback_query(F.data == "scan_mrkt")
async def cb_scan_mrkt(call: CallbackQuery):
    cfg = get_cfg(call.from_user.id)
    col = cfg["collection"]
    budget = cfg["budget"]
    markup_pct = min(cfg["markup"], MAX_MARKUP_LIMIT)

    await call.answer("Запрос к MRKT...")
    await call.message.edit_text(f"Сканирование MRKT по коллекции {col}...")

    try:
        lots = await fetch_mrkt_lots(col, count=30)
        if not lots:
            await call.message.edit_text(
                f"По коллекции {col} сейчас нет активных лотов на MRKT.",
                reply_markup=build_main_menu(call.from_user.id)
            )
            return

        prices = [extract_price_ton(item) for item in lots if extract_price_ton(item) > 0]
        if not prices:
            await call.message.edit_text(
                "Не удалось определить цены лотов.",
                reply_markup=build_main_menu(call.from_user.id)
            )
            return

        floor_price = min(prices)
        max_allowed_by_markup = round(floor_price * (1 + markup_pct / 100.0), 4)
        final_price_cap = min(budget, max_allowed_by_markup)

        if floor_price > budget:
            await call.message.edit_text(
                f"Флор коллекции {col} составляет {floor_price} TON, что превышает ваш бюджет {budget} TON.\n"
                "Увеличьте бюджет или выберите более дешевую коллекцию.",
                reply_markup=build_main_menu(call.from_user.id)
            )
            return

        matched = []
        for item in lots:
            p = extract_price_ton(item)
            if p <= 0:
                continue
            item_markup = ((p - floor_price) / floor_price) * 100.0
            # Строгий фильтр: цена в пределах бюджета И наценка от 0% до markup_pct (не выше 5%)
            if p <= budget and 0 <= item_markup <= markup_pct:
                num = item.get("number") or item.get("giftNumber") or "?"
                model = item.get("modelName") or item.get("model") or "Стандарт"
                bg = item.get("backdropName") or item.get("backdrop") or "-"
                matched.append((p, round(item_markup, 2), num, model, bg))

        if not matched:
            await call.message.edit_text(
                f"Подходящих лотов не найдено.\n"
                f"Флор {col}: {floor_price} TON | Ваш лимит: до {final_price_cap} TON (наценка до +{markup_pct}%).",
                reply_markup=build_main_menu(call.from_user.id)
            )
            return

        lines = [
            f"РЕЗУЛЬТАТЫ MRKT: {col}",
            f"Текущий флор: {floor_price} TON",
            f"Фильтр: бюджет <= {budget} TON, наценка <= +{markup_pct}% (до {max_allowed_by_markup} TON)",
            "----------------------------------------"
        ]
        for p, m_pct, num, model, bg in matched[:10]:
            lines.append(f"#{num} | {p} TON (+{m_pct}% от флора) | Модель: {model} | Фон: {bg}")

        await call.message.edit_text(
            "\n".join(lines),
            reply_markup=build_main_menu(call.from_user.id)
        )

    except Exception as e:
        await call.message.edit_text(
            f"Ошибка при получении данных MRKT:\n{e}",
            reply_markup=build_main_menu(call.from_user.id)
        )

async def handle_health(request):
    return web.Response(text="MRKT Scanner Active")

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
