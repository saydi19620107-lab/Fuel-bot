import os
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

DB = "fuel.db"
FUEL_TYPES = ["АИ-92", "АИ-95", "АИ-98", "ДТ"]
STATUSES = {"yes": "🟢 Есть", "low": "🟡 Мало", "no": "🔴 Нет"}

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS stations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, city TEXT NOT NULL, address TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, station_id INTEGER NOT NULL, fuel_type TEXT NOT NULL, status TEXT NOT NULL, user_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()

def get_cities():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT DISTINCT city FROM stations ORDER BY city")
    r = [x[0] for x in cur.fetchall()]; conn.close(); return r

def get_stations(city):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT id, name, address FROM stations WHERE city=? ORDER BY name", (city,))
    r = cur.fetchall(); conn.close(); return r

def get_station(sid):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT id, name, city, address FROM stations WHERE id=?", (sid,))
    r = cur.fetchone(); conn.close(); return r

def add_report(sid, fuel, status, uid):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("DELETE FROM reports WHERE station_id=? AND fuel_type=? AND user_id=? AND created_at > datetime('now', '-10 minutes')", (sid, fuel, uid))
    cur.execute("INSERT INTO reports (station_id, fuel_type, status, user_id) VALUES (?, ?, ?, ?)", (sid, fuel, status, uid))
    conn.commit(); conn.close()

def get_station_status(sid):
    conn = sqlite3.connect(DB); cur = conn.cursor()
    result = {}
    for fuel in FUEL_TYPES:
        cur.execute("SELECT status, created_at FROM reports WHERE station_id=? AND fuel_type=? AND created_at > datetime('now', '-3 hours') ORDER BY created_at DESC LIMIT 1", (sid, fuel))
        result[fuel] = cur.fetchone()
    conn.close(); return result

def time_ago(ts):
    try: t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except: return ts
    d = datetime.utcnow() - t
    m = int(d.total_seconds() // 60)
    if m < 1: return "только что"
    if m < 60: return f"{m} мин назад"
    h = m // 60
    if h < 24: return f"{h} ч назад"
    return f"{h // 24} дн назад"

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("⛽ Проверить наличие"))
    kb.add(KeyboardButton("📍 Сообщить о наличии"))
    kb.add(KeyboardButton("ℹ️ Помощь"))
    return kb

def cities_kb(prefix):
    kb = InlineKeyboardMarkup()
    for c in get_cities(): kb.add(InlineKeyboardButton(text=c, callback_data=f"{prefix}:{c}"))
    return kb

def stations_kb(city, prefix):
    kb = InlineKeyboardMarkup()
    for sid, name, addr in get_stations(city): kb.add(InlineKeyboardButton(text=name, callback_data=f"{prefix}:{sid}"))
    return kb

def fuels_kb(sid, prefix):
    kb = InlineKeyboardMarkup()
    for f in FUEL_TYPES: kb.add(InlineKeyboardButton(text=f, callback_data=f"{prefix}:{sid}:{f}"))
    return kb

def statuses_kb(sid, fuel):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="🟢 Есть", callback_data=f"set:{sid}:{fuel}:yes"))
    kb.add(InlineKeyboardButton(text="🟡 Мало", callback_data=f"set:{sid}:{fuel}:low"))
    kb.add(InlineKeyboardButton(text="🔴 Нет", callback_data=f"set:{sid}:{fuel}:no"))
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(m: types.Message):
    await m.answer("⛽ <b>Бензин Якутии</b>\n\nПомогаю узнать, где есть топливо, и отметить наличие на АЗС.\n\nВыберите действие в меню ниже 👇", reply_markup=main_menu(), parse_mode="HTML")

@dp.message_handler(commands=["help"])
@dp.message_handler(lambda m: m.text == "ℹ️ Помощь")
async def cmd_help(m: types.Message):
    await m.answer("ℹ️ <b>Как пользоваться</b>\n\n🔍 Проверить наличие — выберите город → АЗС\n\n📍 Сообщить о наличии — отметьте статус. Данные актуальны 3 часа.", parse_mode="HTML")

@dp.message_handler(commands=["fuel"])
@dp.message_handler(lambda m: m.text == "⛽ Проверить наличие")
async def check_fuel(m: types.Message):
    await m.answer("Выберите город:", reply_markup=cities_kb("check_city"))

@dp.message_handler(commands=["report"])
@dp.message_handler(lambda m: m.text == "📍 Сообщить о наличии")
async def report_start(m: types.Message):
    await m.answer("Выберите город:", reply_markup=cities_kb("rep_city"))

@dp.callback_query_handler(lambda c: c.data.startswith("check_city:"))
async def cb_check_city(cb: types.CallbackQuery):
    city = cb.data.split(":", 1)[1]
    if not get_stations(city): await cb.answer("Нет АЗС", show_alert=True); return
    await cb.message.edit_text(f"📍 <b>{city}</b>\nВыберите АЗС:", reply_markup=stations_kb(city, "check_st"), parse_mode="HTML")
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("check_st:"))
async def cb_check_st(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1]); st = get_station(sid)
    if not st: await cb.answer("Не найдена", show_alert=True); return
    _, name, city, addr = st
    s = get_station_status(sid)
    lines = [f"⛽ <b>{name}</b>", f"📍 {city}, {addr}", ""]
    for f in FUEL_TYPES:
        r = s.get(f)
        if r: lines.append(f"{f}: {STATUSES.get(r[0], r[0])} <i>({time_ago(r[1])})</i>")
        else: lines.append(f"{f}: ⚪ Нет данных")
    lines.append("\n⚠️ Данные от пользователей, актуальны 3 часа.")
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"check_st:{sid}"))
    kb.add(InlineKeyboardButton(text="📍 Отметить наличие", callback_data=f"rep_st:{sid}"))
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("rep_city:"))
async def cb_rep_city(cb: types.CallbackQuery):
    city = cb.data.split(":", 1)[1]
    if not get_stations(city): await cb.answer("Нет АЗС", show_alert=True); return
    await cb.message.edit_text(f"📍 <b>{city}</b>\nВыберите АЗС:", reply_markup=stations_kb(city, "rep_st"), parse_mode="HTML")
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("rep_st:"))
async def cb_rep_st(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1]); st = get_station(sid)
    if not st: await cb.answer("Не найдена", show_alert=True); return
    _, name, city, addr = st
    await cb.message.edit_text(f"⛽ <b>{name}</b>\n📍 {city}, {addr}\n\nВыберите вид топлива:", reply_markup=fuels_kb(sid, "rep_fuel"), parse_mode="HTML")
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("rep_fuel:"))
async def cb_rep_fuel(cb: types.CallbackQuery):
    _, sid, fuel = cb.data.split(":"); sid = int(sid)
    st = get_station(sid)
    await cb.message.edit_text(f"⛽ <b>{st[1]}</b>\nТопливо: <b>{fuel}</b>\n\nЧто сейчас на заправке?", reply_markup=statuses_kb(sid, fuel), parse_mode="HTML")
    await cb.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("set:"))
async def cb_set(cb: types.CallbackQuery):
    _, sid, fuel, status = cb.data.split(":"); sid = int(sid)
    add_report(sid, fuel, status, cb.from_user.id)
    st = get_station(sid)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="🔄 Проверить статус", callback_data=f"check_st:{sid}"))
    await cb.message.edit_text(f"✅ Спасибо! Отметили:\n\n⛽ <b>{st[1]}</b>\n🛢 {fuel}: {STATUSES[status]}", parse_mode="HTML", reply_markup=kb)
    await cb.answer("Записано!")
@dp.message_handler(commands=["del_station"])
async def cmd_del_station(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    args = m.text.split(" ", 1)
    if len(args) < 2 or args[1].count("|") != 1:
        await m.answer("Формат: /del_station Город | Название")
        return
    city, name = [x.strip() for x in args[1].split("|")]
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT id FROM stations WHERE city=? AND name=?", (city, name))
    row = cur.fetchone()
    if not row:
        conn.close()
        await m.answer("❌ Не найдено: " + city + " / " + name)
        return
    sid = row[0]
    cur.execute("DELETE FROM stations WHERE id=?", (sid,))
    cur.execute("DELETE FROM reports WHERE station_id=?", (sid,))
    conn.commit(); conn.close()
    await m.answer("🗑 Удалено: " + city + " / " + name)


@dp.message_handler(commands=["add_station"])
async def cmd_add_station(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    args = m.text.split(" ", 1)
    if len(args) < 2 or args[1].count("|") != 2:
        await m.answer("Формат: /add_station Город | Название | Адрес")
        return
    city, name, address = [x.strip() for x in args[1].split("|")]
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("INSERT INTO stations (name, city, address) VALUES (?, ?, ?)", (name, city, address))
    conn.commit(); conn.close()
    await m.answer("✅ Добавлено: " + city + " / " + name)


def load_stations():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM stations")
    if cur.fetchone()[0] > 0:
        conn.close()
        return
    STATIONS = [
        ("Туймаада Нефть (Вилюйский тракт)", "Якутск", "Вилюйский тракт, 5 км"),
        ("Туймаада Нефть (Покровский тракт)", "Якутск", "Покровский тракт, 3 км"),
        ("Роснефть (Чернышевского)", "Якутск", "ул. Чернышевского, 100"),
        ("Роснефть (Дзержинского)", "Якутск", "ул. Дзержинского, 20"),
        ("Газпромнефть (Лермонтова)", "Якутск", "ул. Лермонтова, 60"),
        ("АЗС на Птицефабрике", "Якутск", "Покровский тракт, 10 км"),
        ("АЗС (Сервис Ойл)", "Якутск", "Покровский тракт, 5 км"),
        ("АЗС (СибОйл)", "Якутск", "ул. Петра Алексеева, 70/2"),
        ("АЗС (СибОйл)", "Якутск", "Вилюйский тракт, 6/1"),
        ("АЗС №1 (Саханефтегазсбыт)", "Якутск", "пр. М. Николаева, 19/1а"),
        ("АЗС №6 (Саханефтегазсбыт)", "Якутск", "Жатайский перекресток, 1"),
        ("АЗС №51 (Саханефтегазсбыт)", "Якутск", "ул. 50 лет Советской Армии, 49б"),
        ("АЗС №62 (Саханефтегазсбыт)", "Якутск", "Хатын-Юряхское шоссе, 4 км"),
        ("АЗС №15 (Саханефтегазсбыт)", "Намцы", "ул. Ленина, 24 к 1"),
        ("АЗС (Саханефтегазсбыт)", "Намцы", "ул. Чернышевского, 104"),
        ("ПАГЗС", "Жатай", "Намский тракт, 16 км"),
        ("АЗС №7 (ДСК)", "Октемцы", "Покровский тракт, 49 км"),
        ("АЗС №9 (Саханефтегазсбыт)", "Покровск", "ул. Энергетиков, 2"),
        ("АЗС (Саханефтегазсбыт)", "Покровск", "ул. Ярославского, 45з"),
        ("АЗС №10 (Саханефтегазсбыт)", "Мохсоголлох", "Хангаласский район"),
        ("АЗС (Саханефтегазсбыт)", "Булгунняхтах", "с. Булгунняхтах"),
        ("АЗС №1402 (Саханефтегазсбыт)", "Качикатцы", "с. Качикатцы"),
        ("АЗС (Саханефтегазсбыт)", "Кердем", "с. Кердем"),
        ("АЗС (Саханефтегазсбыт)", "Мирный", "ул. Ленина, 1"),
        ("АЗС №2 (Саханефтегазсбыт)", "Мирный", "ул. Тихонова, 10"),
        ("АЗС (Саханефтегазсбыт)", "Ленск", "ул. Победы, 5"),
        ("АЗС №3 (Саханефтегазсбыт)", "Ленск", "ул. Первомайская, 20"),
        ("АЗС (Саханефтегазсбыт)", "Нерюнгри", "пр. Ленина, 15"),
        ("АЗС №5 (Саханефтегазсбыт)", "Нерюнгри", "ул. Южно-Якутская, 30"),
        ("АЗС (Саханефтегазсбыт)", "Алдан", "ул. Ленина, 20"),
        ("АЗС №7 (Саханефтегазсбыт)", "Алдан", "ул. Мегино-Кангаласская, 5"),
        ("АЗС (Саханефтегазсбыт)", "Томмот", "ул. Пионерская, 5"),
        ("АЗС (Саханефтегазсбыт)", "Хандыга", "ул. Ленина, 1"),
        ("АЗС (Саханефтегазсбыт)", "Усть-Нера", "ул. Ленина, 10"),
        ("АЗС (Саханефтегазсбыт)", "Оймякон", "с. Томтор, ул. Советская, 1"),
        ("АЗС №12 (Саханефтегазсбыт)", "Бердигестях", "ФАД «Вилюй», 188 км"),
        ("АЗС (Саханефтегазсбыт)", "Вилюйск", "ул. Мира, 84"),
        ("АЗС №61 (Саханефтегазсбыт)", "Хоринцы", "с. Хоринцы"),
        ("АЗС №39 (Саханефтегазсбыт)", "Верхневилюйск", "с. Верхневилюйск"),
        ("АЗС №41 (Саханефтегазсбыт)", "Нюрба", "с. Антоновка"),
        ("КАЗС (Саханефтегазсбыт)", "Малыкай", "ул. Мегежекского, 37"),
        ("КАЗС (Саханефтегазсбыт)", "Убоян", "с. Убоян"),
        ("АЗС №45 (Саханефтегазсбыт)", "Сунтар", "ул. Вилюйская, 2"),
        ("КАЗС (Саханефтегазсбыт)", "Кутана", "с. Кутана"),
        ("АЗС (ЯТЭК)", "Сунтар", "ул. Октябрьская, 57"),
        ("АЗС №9 (Саханефтегазсбыт)", "Майя", "ул. Героя Попова"),
        ("АЗС (ОПТИ)", "Нижний Бестях", "ул. Майинская трасса, 3"),
        ("АЗС (Туймаада-Нефть)", "Чурапча", "ул. Трактовая, 1"),
        ("АЗС №71 (Саханефтегазсбыт)", "Ытык-Кюель", "с. Ытык-Кюель"),
        ("АЗС (Саханефтегазсбыт)", "Усть-Мая", "ул. Атласова"),
        ("АЗС (Саханефтегазсбыт)", "Усть-Миль", "с. Усть-Миль"),
        ("АЗС (Саханефтегазсбыт)", "Эжанцы", "с. Эжанцы"),
        ("КАЗС (Саханефтегазсбыт)", "Абага", "с. Абага"),
        ("КАЗС (Саханефтегазсбыт)", "Эмиссы", "с. Эмиссы"),
        ("АЗС №143 (Саханефтегазсбыт)", "Олекминск", "г. Олекминск"),
        ("КАЗС (Саханефтегазсбыт)", "Саныяхтах", "с. Саныяхтах"),
    ]
    cur.executemany("INSERT INTO stations (name, city, address) VALUES (?, ?, ?)", STATIONS)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    load_stations()
    print("Бот запущен")
    executor.start_polling(dp, skip_updates=True)
