import logging
import aiosqlite
import random
import string
import json
import io
import asyncio
import os

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ساعت رسمی ایران برای نمایش و تعمیرات زمان‌دار
TEHRAN_TZ = ZoneInfo('Asia/Tehran')

def now_tehran() -> datetime:
    """زمان فعلی به وقت ایران (بدون tzinfo برای سازگاری با iso ذخیره شده)"""
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)

from io import BytesIO
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes,
    JobQueue
)
from telegram.constants import ParseMode
import qrcode
import httpx
# هدیه شارژ کیف پول
WALLET_BONUS_MIN = 300000      # حداقل مبلغ برای دریافت هدیه
WALLET_BONUS_PERCENT = 5       # درصد هدیه

# ==================== تنظیمات ====================
BOT_TOKEN = "8865620196:AAHzsrcyh5Ql0oAqGPlTfn0DSfwPZ7vyzxE"          # توکن ربات
ADMIN_ID = 8837001390                      # آیدی عددی ادمین
CHANNEL_USERNAME = "@nexroofficial"        # کانال جوین اجباری
SUPPORT_USERNAME = "@RoTex8"               # پشتیبانی
CARD_NUMBER = "6037701156614445"
CARD_NAME = "حبیب صادقی"
REFERRAL_BONUS = 5000                      # هدیه هر رفرال

# اطلاعات پنل مرزبان (همه کانفیگ‌ها از این پنل ساخته می‌شوند)
PANEL_URL = "https://marzban-panel-production-7c00.up.railway.app"
PANEL_USERNAME = "admin"
PANEL_PASSWORD = "12345678sina"

# محدودیت‌ها و تنظیمات جدید
MAX_PENDING_ORDERS = 2          # حداکثر سفارش در انتظار همزمان برای هر کاربر
USAGE_WARNING_PERCENT = 85      # درصد هشدار مصرف
EXPIRE_WARN_HOURS = 24          # چند ساعت قبل از انقضا هشدار بده
AUTO_RENEW_HOURS = 24           # چند ساعت قبل از انقضا تمدید خودکار انجام شود
BALANCE_WARN_HOURS = 72         # چند ساعت قبل از انقضا هشدار کمبود موجودی برای تمدید خودکار
TEST_DELETE_AFTER_HOURS = 48    # حذف خودکار اکانت تست بعد از چند ساعت

# پروکسی — قیمت‌های پایه (قابل تغییر از پنل ادمین)
PROXY_PRICE_HOLLAND = 50000
PROXY_PRICE_AMERICA = 35000
PROXY_PRICE_SINGAPORE = 25000
PROXY_PRICE_PER_DAY = 500          # قیمت هر روز پروکسی
PROXY_MIN_QTY = 1
PROXY_MAX_QTY = 50
PROXY_MIN_DAYS = 1
PROXY_MAX_DAYS = 90
# =================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States
(
    WAITING_USERNAME, WAITING_RECEIPT, WAITING_DISCOUNT,
    WAITING_WALLET_AMOUNT, WAITING_WALLET_RECEIPT,
    ADMIN_ADD_TARIFF_GB, ADMIN_ADD_TARIFF_PRICE,
    ADMIN_WELCOME, ADMIN_RULES, ADMIN_DISCOUNT_CODE,
    ADMIN_DISCOUNT_PERCENT, ADMIN_DISCOUNT_LIMIT, ADMIN_DISCOUNT_EXPIRE,
    ADMIN_BAN, ADMIN_UNBAN, ADMIN_BROADCAST,
    ADMIN_MSG_USER_ID, ADMIN_MSG_TEXT,
    ADMIN_TEST_RECHARGE, ADMIN_ADD_BALANCE_ID,
    ADMIN_ADD_BALANCE_AMOUNT, ADMIN_ADD_BALANCE_NOTE,
    ADMIN_ALL_BALANCE,
    ADMIN_DEDUCT_ID, ADMIN_DEDUCT_AMOUNT,
    ADMIN_SEARCH_USER,
    ADMIN_SET_REFERRAL, ADMIN_SET_MIN_CHARGE,
    ADMIN_SET_SERVICE_DAYS,
    ADMIN_PANEL_NAME, ADMIN_PANEL_URL, ADMIN_PANEL_USER, ADMIN_PANEL_PASS,
    ADMIN_EDIT_TARIFF_GB, ADMIN_EDIT_TARIFF_PRICE,
    WAITING_TICKET, ADMIN_REPLY_TICKET,
    RENEW_WAITING_RECEIPT,
    ADMIN_ADD_ADMIN_ID,
    ADMIN_SET_CHANNEL,
    ADMIN_BROADCAST_ADMINS,
    ADMIN_MSG_ADMIN_TARGET,
    ADMIN_MSG_ADMIN_TEXT,
    ADMIN_WARN_TARGET,
    ADMIN_WARN_TEXT,
    ADMIN_CLEAR_WARN_TARGET,
    CUSTOM_WAITING_GB,
    CUSTOM_WAITING_DAYS,
    ADMIN_SET_CUSTOM_GB_PRICE,
    ADMIN_SET_CUSTOM_DAY_PRICE,
    TRANSFER_WAITING_TARGET,
    TRANSFER_CONFIRM,
    ADMIN_TRACKING_SEARCH,
    ADMIN_SET_TEST_VOLUME,
    WAITING_DURATION,
    # پروکسی
    PROXY_WAITING_RECEIPT,
    ADMIN_PROXY_CHARGE,
    ADMIN_PROXY_SET_PRICE,
    ADMIN_REJECT_REASON,
    TRACK_ORDER_CODE,
    ADMIN_FAQ,
    # کد هدیه
    ADMIN_GIFT_CODE,
    ADMIN_GIFT_VOLUME,
    ADMIN_GIFT_DAYS,
    ADMIN_GIFT_SERVER,
    ADMIN_GIFT_MAX_USES,
    WAITING_GIFT_CODE,
    # پنل / تعمیرات / سوالات آماده
    ADMIN_PANEL_CFG_SEARCH,
    ADMIN_PANEL_CFG_DELETE,
    ADMIN_MAINT_HOURS,
    ADMIN_SQA_ADD_TITLE,
    ADMIN_SQA_ADD_ANSWER,
    ADMIN_SQA_EDIT_ANSWER,
) = range(73)

# ==================== دیتابیس ====================
async def init_db():
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance INTEGER DEFAULT 0,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                is_banned INTEGER DEFAULT 0,
                join_date TEXT,
                test_used INTEGER DEFAULT 0,
                last_test_at TEXT
            )
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_test_at TEXT")
        except:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN warnings INTEGER DEFAULT 0")
        except:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                url TEXT,
                username TEXT,
                password TEXT,
                panel_type TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tariffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_type TEXT,
                volume_gb INTEGER,
                price INTEGER,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                server_type TEXT,
                volume_gb INTEGER,
                price INTEGER,
                final_price INTEGER,
                discount_code TEXT,
                config_name TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                config_data TEXT,
                warned_85 INTEGER DEFAULT 0,
                expire_warned INTEGER DEFAULT 0,
                panel_username TEXT,
                tracking_code TEXT,
                auto_renew INTEGER DEFAULT 0,
                balance_warned INTEGER DEFAULT 0
            )
        """)
        # ستون‌های جدید برای دیتابیس‌های قدیمی
        for col, typ in [
            ("warned_85", "INTEGER DEFAULT 0"),
            ("expire_warned", "INTEGER DEFAULT 0"),
            ("panel_username", "TEXT"),
            ("tracking_code", "TEXT"),
            ("auto_renew", "INTEGER DEFAULT 0"),
            ("balance_warned", "INTEGER DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
            except:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS discount_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                percent INTEGER,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                expires_at TEXT,
                starts_at TEXT,
                created_at TEXT
            )
        """)
        for col, typ in [
            ("expires_at", "TEXT"),
            ("starts_at", "TEXT"),
            ("created_at", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE discount_codes ADD COLUMN {col} {typ}")
            except:
                pass
        # کدهای هدیه یک‌بارمصرف (حجم + روز مشخص)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                volume_gb INTEGER NOT NULL,
                days INTEGER NOT NULL,
                server_type TEXT DEFAULT 'holland',
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                created_by INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_charges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS test_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                status TEXT DEFAULT 'open',
                admin_reply TEXT,
                created_at TEXT,
                replied_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 1,
                added_at TEXT,
                added_by INTEGER,
                can_add_admin INTEGER DEFAULT 0,
                can_toggle_admin INTEGER DEFAULT 0
            )
        """)
        # ستون‌های دسترسی برای دیتابیس‌های قدیمی
        for col, typ in [
            ("can_add_admin", "INTEGER DEFAULT 0"),
            ("can_toggle_admin", "INTEGER DEFAULT 0"),
            ("can_finance", "INTEGER DEFAULT 1"),
            ("can_support", "INTEGER DEFAULT 1"),
        ]:
            try:
                await db.execute(f"ALTER TABLE admins ADD COLUMN {col} {typ}")
            except:
                pass
        # جدول جلوگیری از رسید تکراری
        await db.execute("""
            CREATE TABLE IF NOT EXISTS used_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_unique_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                context TEXT,
                created_at TEXT
            )
        """)
        # لاگ اقدامات ادمین
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                detail TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS join_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT UNIQUE,
                is_active INTEGER DEFAULT 1,
                added_at TEXT
            )
        """)
        # جدول موجودی پروکسی‌ها (هر ردیف یک پروکسی آماده فروش)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                proxy_text TEXT NOT NULL,
                is_sold INTEGER DEFAULT 0,
                order_id INTEGER,
                created_at TEXT
            )
        """)
        # سفارش‌های پروکسی
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                location TEXT,
                quantity INTEGER,
                days INTEGER,
                unit_price INTEGER,
                days_price INTEGER,
                final_price INTEGER,
                status TEXT DEFAULT 'pending',
                proxies_data TEXT,
                tracking_code TEXT,
                created_at TEXT
            )
        """)
        await db.commit()

        # اطمینان از وجود ادمین اصلی
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (ADMIN_ID,)) as cur:
            if not await cur.fetchone():
                await db.execute(
                    "INSERT INTO admins (user_id, is_active, added_at, added_by) VALUES (?, 1, ?, ?)",
                    (ADMIN_ID, datetime.now().isoformat(), ADMIN_ID)
                )
                await db.commit()

        # مهاجرت کانال پیش‌فرض به جدول join_channels
        async with db.execute("SELECT COUNT(*) FROM join_channels") as cur:
            ch_count = (await cur.fetchone())[0]
        if ch_count == 0:
            default_ch = CHANNEL_USERNAME if CHANNEL_USERNAME else ""
            # اگر از settings هم کانال قدیمی باشد
            async with db.execute("SELECT value FROM settings WHERE key = 'channel_username'") as cur:
                old = await cur.fetchone()
            if old and old[0] and old[0].strip():
                default_ch = old[0].strip()
            if default_ch:
                if not default_ch.startswith("@") and not default_ch.lstrip("-").isdigit():
                    default_ch = "@" + default_ch
                try:
                    await db.execute(
                        "INSERT INTO join_channels (channel, is_active, added_at) VALUES (?, 1, ?)",
                        (default_ch, datetime.now().isoformat())
                    )
                    await db.commit()
                except:
                    pass

        # تعرفه‌های پیش‌فرض
        async with db.execute("SELECT COUNT(*) FROM tariffs") as cur:
            count = (await cur.fetchone())[0]
        if count == 0:
            defaults = [
                ("holland", 5, 70000), ("holland", 10, 150000),
                ("holland", 15, 200000), ("holland", 20, 250000),
                ("holland", 50, 400000),
                ("multi", 5, 60000), ("multi", 10, 130000),
                ("multi", 15, 180000), ("multi", 20, 220000),
                ("multi", 50, 350000),
                ("unlimited", 1, 399000), ("unlimited", 2, 699000),
                ("unlimited", 3, 899000),
            ]
            for s, v, p in defaults:
                await db.execute(
                    "INSERT INTO tariffs (server_type, volume_gb, price) VALUES (?, ?, ?)",
                    (s, v, p)
                )
            await db.commit()
        else:
            # اگر تعرفه‌های نامحدود وجود ندارند، اضافه کن
            async with db.execute("SELECT COUNT(*) FROM tariffs WHERE server_type = 'unlimited'") as cur:
                unlim_count = (await cur.fetchone())[0]
            if unlim_count == 0:
                for v, p in [(1, 399000), (2, 699000), (3, 899000)]:
                    await db.execute(
                        "INSERT INTO tariffs (server_type, volume_gb, price) VALUES (?, ?, ?)",
                        ("unlimited", v, p)
                    )
                await db.commit()

        # تنظیمات پیش‌فرض
        async with db.execute("SELECT COUNT(*) FROM settings") as cur:
            count = (await cur.fetchone())[0]
        if count == 0:
            welcome = (
                "🌟 به ربات فروش کانفیگ خوش آمدید!\n\n"
                "از طریق این ربات می‌تونید به راحتی سرویس مورد نظرتون رو خریداری کنید.\n"
                "از منوی زیر گزینه مورد نظرتون رو انتخاب کنید 👇"
            )
            rules = """📜 قوانین و مقررات استفاده از ربات

۱️⃣ خرید سرویس از این ربات به معنی پذیرش کامل این قوانینه.
۲️⃣ اطلاعات سرویس (کانفیگ/یوزرنیم/پسورد) فقط برای استفاده شخصی شماست؛ اشتراک‌گذاری یا فروش مجدد اون بدون هماهنگی با پشتیبانی مجاز نیست.
۳️⃣ بعد از ارسال رسید یا پرداخت با کیف پول، سفارش شما در سریع‌ترین زمان ممکن توسط ادمین بررسی و تحویل داده میشه.
۴️⃣ در صورت واریز اشتباه یا مغایرت مبلغ، سفارش ممکنه رد بشه؛ لطفاً از طریق پشتیبانی پیگیری کنید.
۵️⃣ وجه واریزی برای سرویس‌های تحویل‌داده‌شده قابل استرداد نیست، مگر در صورت وجود مشکل فنی از سمت ما.
۶️⃣ موجودی کیف پول فقط داخل همین ربات و برای خرید سرویس قابل استفاده است و قابل برداشت نقدی نیست.
۷️⃣ استفاده از سرویس‌ها برای فعالیت‌های غیرقانونی یا مخرب (هک، اسپم، آزار دیگران و ...) ممنوعه و در صورت مشاهده، سرویس بدون اطلاع قبلی مسدود میشه.
۸️⃣ قیمت‌ها و تعرفه‌ها ممکنه بدون اطلاع قبلی تغییر کنن؛ قیمت لحظه ثبت سفارش ملاک نهایی است.
۹️⃣ برای هرگونه سؤال یا مشکل، از بخش «💬 پشتیبانی» با ما در ارتباط باشید.

با تشکر از اعتماد شما 🙏"""
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("welcome", welcome))
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("rules", rules))
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("referral_bonus", "5000"))
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("min_charge", "10000"))
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("service_days", "30"))
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("channel_username", CHANNEL_USERNAME))
            await db.commit()

        for key, default in [
            ("referral_bonus", "5000"),
            ("min_charge", "10000"),
            ("service_days", "30"),
            ("maintenance", "0"),
            ("maintenance_until", ""),
            ("channel_username", CHANNEL_USERNAME),
            ("custom_price_per_gb", "12000"),   # قیمت هر گیگ در پلن دلخواه
            ("custom_price_per_day", "3000"),   # قیمت هر روز در پلن دلخواه
            ("custom_min_gb", "5"),
            ("custom_max_gb", "200"),
            ("custom_min_days", "7"),
            ("custom_max_days", "90"),
            ("test_volume_mb", "30"),           # حجم اکانت تست به مگابایت
            ("price_per_day", "1000"),         # نرخ هر روز اضافی
            ("min_service_days", "7"),
            ("max_service_days", "90"),
            # پروکسی
            ("proxy_price_holland", str(PROXY_PRICE_HOLLAND)),
            ("proxy_price_america", str(PROXY_PRICE_AMERICA)),
            ("proxy_price_singapore", str(PROXY_PRICE_SINGAPORE)),
            ("proxy_price_per_day", str(PROXY_PRICE_PER_DAY)),
        ]:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                if not await cur.fetchone():
                    await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, default))
        await db.commit()

        # پنل‌ها: همه انواع (هلند/مولتی/نامحدود/تست) روی مرزبان
        defaults_panels = [
            ("مرزبان (هلند)", PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, "holland"),
            ("مرزبان (مولتی)", PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, "multi"),
            ("مرزبان (نامحدود)", PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, "unlimited"),
            ("مرزبان (تست)", PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, "test"),
        ]
        async with db.execute("SELECT COUNT(*) FROM panels") as cur:
            pcount = (await cur.fetchone())[0]
        if pcount == 0:
            for pname, purl, puser, ppass, ptype in defaults_panels:
                await db.execute(
                    "INSERT INTO panels (name, url, username, password, panel_type) VALUES (?, ?, ?, ?, ?)",
                    (pname, purl, puser, ppass, ptype)
                )
            await db.commit()
        else:
            # مهاجرت: همه پنل‌های فعال را به مرزبان جدید یکسان کن
            try:
                await db.execute(
                    "UPDATE panels SET panel_type = 'holland' WHERE panel_type = 'main'"
                )
                await db.commit()
            except Exception:
                pass
            for ptype, pname in [
                ("holland", "مرزبان (هلند)"),
                ("multi", "مرزبان (مولتی)"),
                ("unlimited", "مرزبان (نامحدود)"),
                ("test", "مرزبان (تست)"),
            ]:
                async with db.execute(
                    "SELECT COUNT(*) FROM panels WHERE panel_type = ?", (ptype,)
                ) as cur:
                    cnt = (await cur.fetchone())[0]
                if cnt == 0:
                    await db.execute(
                        "INSERT INTO panels (name, url, username, password, panel_type) VALUES (?, ?, ?, ?, ?)",
                        (pname, PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, ptype)
                    )
                else:
                    # به‌روزرسانی آدرس و اطلاعات ورود به پنل مرزبان
                    await db.execute(
                        """UPDATE panels
                           SET url = ?, username = ?, password = ?, name = ?, is_active = 1
                           WHERE panel_type = ?""",
                        (PANEL_URL, PANEL_USERNAME, PANEL_PASSWORD, pname, ptype)
                    )
            await db.commit()

async def get_setting(key: str) -> str:
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""

async def set_setting(key: str, value: str):
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()

async def get_int_setting(key: str, default: int = 0) -> int:
    val = await get_setting(key)
    try:
        return int(val)
    except:
        return default

async def get_or_create_user(user_id: int, username: str = None, full_name: str = None):
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()
        if not user:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            await db.execute(
                """INSERT INTO users (user_id, username, full_name, referral_code, join_date)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, username, full_name, code, datetime.now().isoformat())
            )
            await db.commit()
            return True
        return False

async def is_banned(user_id: int) -> bool:
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])

async def is_admin(user_id: int) -> bool:
    """بررسی اینکه کاربر ادمین فعال است یا خیر (شامل ادمین اصلی)"""
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT is_active FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0])

async def can_add_admin(user_id: int) -> bool:
    """آیا کاربر مجاز به اضافه کردن ادمین جدید است؟ (مالک همیشه بله)"""
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT is_active, can_add_admin FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0] and row[1])

async def can_toggle_admin(user_id: int) -> bool:
    """آیا کاربر مجاز به فعال/غیرفعال کردن ادمین‌ها است؟ (مالک همیشه بله)"""
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT is_active, can_toggle_admin FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0] and row[1])


async def can_finance(user_id: int) -> bool:
    """دسترسی مالی: شارژ، موجودی، سفارش، تعرفه، پروکسی"""
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT is_active, can_finance FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row or not row[0]:
                return False
            # اگر ستون NULL باشد (دیتابیس قدیمی) دسترسی کامل در نظر بگیر
            return True if row[1] is None else bool(row[1])


async def can_support(user_id: int) -> bool:
    """دسترسی پشتیبانی: تیکت، بن، اخطار، پیام به کاربر، جستجو"""
    if user_id == ADMIN_ID:
        return True
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT is_active, can_support FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row or not row[0]:
                return False
            return True if row[1] is None else bool(row[1])


async def is_receipt_used(file_unique_id: str) -> bool:
    if not file_unique_id:
        return False
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT 1 FROM used_receipts WHERE file_unique_id = ?", (file_unique_id,)
        ) as cur:
            return bool(await cur.fetchone())


async def store_receipt_id(file_unique_id: str, user_id: int, context_label: str = "order"):
    if not file_unique_id:
        return
    async with aiosqlite.connect("bot.db") as db:
        try:
            await db.execute(
                "INSERT INTO used_receipts (file_unique_id, user_id, context, created_at) VALUES (?, ?, ?, ?)",
                (file_unique_id, user_id, context_label, datetime.now().isoformat())
            )
            await db.commit()
        except Exception:
            # UNIQUE violation = قبلاً ثبت شده
            pass



RECEIPT_RATE_LIMIT_COUNT = 3
RECEIPT_RATE_LIMIT_MINUTES = 10
PROXY_LOW_STOCK_THRESHOLD = 5
LOYALTY_EVERY_N = 5


async def log_admin_action(admin_id: int, action: str, target_id: int = None, detail: str = None):
    """ثبت لاگ اقدام ادمین در دیتابیس"""
    try:
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "INSERT INTO admin_logs (admin_id, action, target_id, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (admin_id, action, target_id, detail, datetime.now().isoformat())
            )
            await db.commit()
    except Exception as e:
        logger.error(f"log_admin_action: {e}")


async def notify_admin_sale(
    bot,
    *,
    kind: str,
    order_id: int,
    user_id: int,
    amount: int,
    plan: str,
    payment: str = "—",
    extra: str = None,
):
    """
    اعلان لحظه‌ای فروش موفق به ادمین اصلی.
    kind: service | renew | auto_renew | proxy | wallet
    """
    try:
        kind_map = {
            "service": "🛒 خرید سرویس",
            "renew": "🔄 تمدید سرویس",
            "auto_renew": "🤖 تمدید خودکار",
            "proxy": "🌐 خرید پروکسی",
            "wallet": "💳 شارژ کیف پول",
        }
        title = kind_map.get(kind, "💰 فروش")
        # نام کاربر
        uname = "—"
        full_name = "—"
        try:
            async with aiosqlite.connect("bot.db") as db:
                async with db.execute(
                    "SELECT full_name, username FROM users WHERE user_id = ?", (user_id,)
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    full_name = row[0] or "—"
                    uname = f"@{row[1]}" if row[1] else "—"
        except Exception:
            pass

        text = (
            f"{title}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 {plan}\n"
            f"💰 مبلغ: <b>{amount:,}</b> تومان\n"
            f"💳 پرداخت: {payment}\n"
            f"👤 {full_name} ({uname})\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🔢 سفارش: #{order_id}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        if extra:
            text += f"\n{extra}"

        await bot.send_message(ADMIN_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"notify_admin_sale: {e}")


async def check_receipt_rate_limit(user_id: int) -> bool:
    """True = مجاز است | False = بیش از حد ارسال کرده"""
    cutoff = (datetime.now() - timedelta(minutes=RECEIPT_RATE_LIMIT_MINUTES)).isoformat()
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM used_receipts WHERE user_id = ? AND created_at >= ?",
            (user_id, cutoff)
        ) as cur:
            count = (await cur.fetchone())[0]
    return count < RECEIPT_RATE_LIMIT_COUNT


async def get_loyalty_progress(user_id: int) -> tuple:
    """
    برمی‌گرداند: (تعداد_خرید_در_دور_فعلی, نیاز_برای_هدیه, کل_خریدهای_معتبر)
    مثلاً بعد از ۲ خرید: (2, 5, 2) → «۲ از ۵»
    """
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT COUNT(*) FROM orders
               WHERE user_id = ? AND status = 'paid'
                 AND final_price > 0
                 AND (config_data IS NULL OR (
                     config_data NOT LIKE '%"type": "renew"%'
                     AND config_data NOT LIKE '%"type":"renew"%'
                     AND config_data NOT LIKE '%"type": "loyalty_gift"%'
                     AND config_data NOT LIKE '%"type":"loyalty_gift"%'
                 ))""",
            (user_id,)
        ) as cur:
            paid_count = (await cur.fetchone())[0]
    current = paid_count % LOYALTY_EVERY_N
    # اگر دقیقاً مضرب ۵ باشد، دور جدید از ۰ شروع شده (هدیه داده شده)
    return current, LOYALTY_EVERY_N, paid_count


async def loyalty_progress_text(user_id: int) -> str:
    current, need, total = await get_loyalty_progress(user_id)
    if current == 0 and total > 0:
        # تازه هدیه گرفته یا هنوز شروع نکرده در دور جدید
        return (
            f"🎁 پیشرفت هدیه: <b>۰ از {need}</b> خرید تا سرویس رایگان بعدی\n"
            f"(مجموع خریدهای معتبر: {total})"
        )
    remain = need - current
    return (
        f"🎁 پیشرفت هدیه: <b>{current} از {need}</b> خرید تا سرویس ۱ گیگ رایگان\n"
        f"(با {remain} خرید دیگر هدیه می‌گیرید — مجموع: {total})"
    )


async def notify_proxy_low_stock(bot, location: str):
    """اگر موجودی لوکیشن زیر آستانه بود به ادمین خبر بده"""
    try:
        stock = await get_proxy_stock_count(location)
        if stock >= PROXY_LOW_STOCK_THRESHOLD:
            return
        loc_name = PROXY_LOCATIONS.get(location, {}).get("name", location)
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>موجودی کم پروکسی</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 لوکیشن: {loc_name}\n"
            f"📦 موجودی فعلی: <b>{stock}</b> عدد\n"
            f"(آستانه هشدار: {PROXY_LOW_STOCK_THRESHOLD})\n\n"
            f"لطفاً از پنل ادمین انبار را شارژ کنید.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"notify_proxy_low_stock: {e}")


def get_receipt_unique_id(message) -> Optional[str]:
    """استخراج file_unique_id از عکس یا فایل پیام"""
    if message.photo:
        return message.photo[-1].file_unique_id
    if message.document:
        return message.document.file_unique_id
    return None


async def maybe_grant_loyalty_gift(bot, user_id: int):
    """
    بعد از هر ۵ خرید سرویس واقعی (مبلغ > ۰ و نه هدیه/تمدید)،
    یک سرویس ۱ گیگ رایگان (هلند) بساز و برای کاربر بفرست.
    """
    try:
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT COUNT(*) FROM orders
                   WHERE user_id = ? AND status = 'paid'
                     AND final_price > 0
                     AND (config_data IS NULL OR (
                         config_data NOT LIKE '%"type": "renew"%'
                         AND config_data NOT LIKE '%"type":"renew"%'
                         AND config_data NOT LIKE '%"type": "loyalty_gift"%'
                         AND config_data NOT LIKE '%"type":"loyalty_gift"%'
                     ))""",
                (user_id,)
            ) as cur:
                paid_count = (await cur.fetchone())[0]

            async with db.execute(
                """SELECT COUNT(*) FROM orders
                   WHERE user_id = ? AND status = 'paid'
                     AND (config_data LIKE '%loyalty_gift%')""",
                (user_id,)
            ) as cur:
                gift_count = (await cur.fetchone())[0]

        # هر ۵ خرید → ۱ هدیه (هدیه شمارش نمی‌شود)
        expected_gifts = paid_count // 5
        if expected_gifts <= gift_count:
            return

        # ساخت کانفیگ رایگان ۱ گیگ
        gift_name = "gift_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        service_days = await get_int_setting("service_days", 30)
        config = await create_config_from_panel(
            gift_name, 1, days=service_days, is_unlimited=False, server_type="holland"
        )
        tracking = generate_tracking_code()
        async with aiosqlite.connect("bot.db") as db:
            cur = await db.execute(
                """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price,
                   config_name, status, created_at, panel_username, config_data, tracking_code)
                   VALUES (?, 'holland', 1, 0, 0, ?, 'paid', ?, ?, ?, ?)""",
                (
                    user_id,
                    config["username"],
                    datetime.now().isoformat(),
                    config["username"],
                    json.dumps({**config, "type": "loyalty_gift"}),
                    tracking,
                )
            )
            order_id = cur.lastrowid
            await db.commit()

        qr = generate_qr(config["subscription_url"])
        caption = (
            f"🎁 <b>هدیه خرید ۵ سرویس</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"تبریک! با خرید ۵ سرویس، یک سرویس <b>۱ گیگ رایگان</b> به شما تعلق گرفت.\n\n"
            f"👤 نام کاربری: <code>{config['username']}</code>\n"
            f"🔗 لینک اشتراک:\n<code>{config['subscription_url']}</code>\n\n"
            f"🔖 کد رهگیری: <code>{tracking}</code>\n"
            f"📦 سفارش هدیه: #{order_id}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⏳ زمان: {config['expire']}", callback_data="noop")],
            [InlineKeyboardButton(f"📊 حجم: {config['volume']}", callback_data="noop")],
            [
                InlineKeyboardButton("📷 QR CODE", callback_data=f"qr_{order_id}"),
                InlineKeyboardButton("📄 دانلود فایل", callback_data=f"dlcfg_{order_id}"),
            ],
            [InlineKeyboardButton("📖 آموزش استفاده", callback_data=f"guide_{order_id}")],
            [back_button()],
        ])
        await bot.send_photo(
            user_id,
            photo=InputFile(qr, "qr.png"),
            caption=caption,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Loyalty gift sent to {user_id} (order #{order_id})")
    except Exception as e:
        logger.error(f"maybe_grant_loyalty_gift error for {user_id}: {e}")


async def issue_warning(bot, user_id: int, reason: str = None, issued_by: int = None) -> tuple:
    """
    ثبت اخطار برای کاربر.
    برمی‌گرداند: (تعداد_اخطار_جدید, آیا_مسدود_شد)
    """
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT warnings, is_banned FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return 0, False
        warnings = (row[0] or 0) + 1
        banned = bool(row[1])
        await db.execute("UPDATE users SET warnings = ? WHERE user_id = ?", (warnings, user_id))
        if warnings >= 3 and not banned:
            await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            banned = True
        await db.commit()

    # پیام به کاربر
    if banned:
        user_msg = (
            "🚫 <b>مسدودیت حساب</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "به دلیل دریافت <b>۳ اخطار</b>، دسترسی شما به ربات به‌طور کامل مسدود شد.\n\n"
        )
        if reason:
            user_msg += f"📝 دلیل آخرین اخطار:\n{reason}\n\n"
        user_msg += (
            "در صورت اعتراض می‌توانید با پشتیبانی در ارتباط باشید.\n"
            f"💬 {SUPPORT_USERNAME}"
        )
    else:
        user_msg = (
            "⚠️ <b>اخطار رسمی</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"شما اخطار شماره <b>{warnings}</b> از ۳ را دریافت کردید.\n\n"
        )
        if reason:
            user_msg += f"📝 دلیل:\n{reason}\n\n"
        user_msg += (
            "❗ در صورت رسیدن به ۳ اخطار، حساب شما به‌صورت خودکار مسدود خواهد شد.\n"
            "لطفاً از تکرار رفتار نامناسب خودداری کنید."
        )
    try:
        await bot.send_message(user_id, user_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"send warning to {user_id}: {e}")

    return warnings, banned

async def is_maintenance() -> bool:
    """تعمیرات دستی یا زمان‌دار (maintenance_until) — بر اساس ساعت ایران"""
    if (await get_setting("maintenance")) == "1":
        until = await get_setting("maintenance_until")
        if until:
            try:
                end_dt = datetime.fromisoformat(until)
                # اگر tz داشت، به تهران تبدیل و naive کن
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
                if now_tehran() >= end_dt:
                    await set_setting("maintenance", "0")
                    await set_setting("maintenance_until", "")
                    return False
            except Exception:
                pass
        return True
    return False


async def get_maintenance_info() -> str:
    """متن وضعیت تعمیرات برای نمایش در تنظیمات (ساعت ایران)"""
    if not await is_maintenance():
        return "🟢 غیرفعال"
    until = await get_setting("maintenance_until")
    if until:
        try:
            end_dt = datetime.fromisoformat(until)
            if end_dt.tzinfo is not None:
                end_dt = end_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            remain = end_dt - now_tehran()
            mins = max(0, int(remain.total_seconds() // 60))
            if mins >= 60:
                t = f"{mins // 60} ساعت و {mins % 60} دقیقه"
            else:
                t = f"{mins} دقیقه"
            return (
                f"🔴 فعال تا {end_dt.strftime('%Y/%m/%d %H:%M')} "
                f"(ایران) — باقی‌مانده: {t}"
            )
        except Exception:
            return "🔴 فعال (زمان‌دار)"
    return "🔴 فعال (دستی)"

async def get_join_channels(active_only: bool = True) -> list:
    """لیست کانال‌های جوین اجباری"""
    async with aiosqlite.connect("bot.db") as db:
        if active_only:
            async with db.execute(
                "SELECT id, channel FROM join_channels WHERE is_active = 1 ORDER BY id"
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT id, channel, is_active FROM join_channels ORDER BY id"
            ) as cur:
                rows = await cur.fetchall()
    return rows

async def check_pending_limit(user_id: int) -> bool:
    """بررسی محدودیت تعداد سفارش در انتظار"""
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        ) as cur:
            count = (await cur.fetchone())[0]
    return count < MAX_PENDING_ORDERS

# ==================== توابع کمکی ====================
async def check_membership(bot, user_id: int) -> bool:
    """بررسی عضویت کاربر در همه کانال‌های فعال جوین اجباری"""
    channels = await get_join_channels(active_only=True)
    if not channels:
        return True  # هیچ کانال فعالی نیست → جوین اجباری غیرفعال
    for _, channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True

async def is_bot_admin_in_channel(bot, channel: str) -> bool:
    """بررسی اینکه ربات در کانال ادمین است یا نه"""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(channel, me.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def main_keyboard(is_admin: bool = False):
    buttons = [
        [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service")],
        [InlineKeyboardButton("🌐 پروکسی", callback_data="proxy_menu")],
        [
            InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services"),
            InlineKeyboardButton("🔄 تمدید سریع", callback_data="quick_renew"),
        ],
        [
            InlineKeyboardButton("📊 وضعیت سرویس‌ها", callback_data="service_status"),
            InlineKeyboardButton("📋 تاریخچه سفارشات", callback_data="order_history"),
        ],
        [
            InlineKeyboardButton("🧪 اکانت تست", callback_data="test_account"),
            InlineKeyboardButton("🔍 پیگیری سفارش", callback_data="track_order"),
        ],
        [
            InlineKeyboardButton("💰 کیف پول", callback_data="wallet"),
            InlineKeyboardButton("🎁 کد هدیه", callback_data="redeem_gift"),
        ],
        [
            InlineKeyboardButton("👤 حساب کاربری", callback_data="my_account"),
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
        ],
        [
            InlineKeyboardButton("❓ راهنما / سوالات متداول", callback_data="faq"),
            InlineKeyboardButton("👥 دعوت از دوستان", callback_data="referral"),
        ],
        [
            InlineKeyboardButton("📜 قوانین", callback_data="rules"),
            InlineKeyboardButton("📊 تعرفه اشتراک‌ها", callback_data="tariffs_menu"),
        ],
    ]

    if is_admin:
        buttons.append([
            InlineKeyboardButton("🛠 پنل مدیریت", callback_data="admin_panel")
        ])

    return InlineKeyboardMarkup(buttons)
def back_button(data="back_main"):
    return InlineKeyboardButton("🔙 بازگشت", callback_data=data)

# ==================== پنل ====================
def resolve_panel_type(server_type: str = None, is_test: bool = False) -> str:
    """
    نگاشت نوع سرور به نوع پنل:
    - هلند / دلخواه  → پاسارگاد (holland)
    - مولتی لوکیشن   → سنایی (multi)
    - نامحدود        → مرزبان (unlimited)
    - تست            → test
    """
    if is_test:
        return "test"
    mapping = {
        "holland": "holland",
        "custom": "holland",
        "multi": "multi",
        "unlimited": "unlimited",
        "test": "test",
        # سازگاری با پنل‌های قدیمی
        "main": "holland",
    }
    return mapping.get((server_type or "holland").lower(), "holland")


async def get_panel(panel_type: str = "holland"):
    """دریافت اطلاعات پنل فعال بر اساس نوع"""
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT url, username, password, name FROM panels WHERE panel_type = ? AND is_active = 1 LIMIT 1",
            (panel_type,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return {"url": row[0], "username": row[1], "password": row[2], "name": row[3], "panel_type": panel_type}
        # fallback: main قدیمی یا holland
        for fallback in ("holland", "main"):
            async with db.execute(
                "SELECT url, username, password, name FROM panels WHERE panel_type = ? AND is_active = 1 LIMIT 1",
                (fallback,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                return {"url": row[0], "username": row[1], "password": row[2], "name": row[3], "panel_type": fallback}
    return {"url": PANEL_URL, "username": PANEL_USERNAME, "password": PANEL_PASSWORD, "name": "پیش‌فرض", "panel_type": panel_type}


async def get_panel_for_server(server_type: str = None, is_test: bool = False) -> dict:
    """پنل مناسب برای نوع سرور را برمی‌گرداند"""
    ptype = resolve_panel_type(server_type, is_test=is_test)
    return await get_panel(ptype)


async def get_panel_token(panel: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        login_res = await client.post(
            f"{panel['url']}/api/admin/token",
            data={"username": panel["username"], "password": panel["password"]}
        )
        if login_res.status_code != 200:
            raise Exception(
                f"LOGIN FAILED [{panel.get('name', panel.get('panel_type', '?'))}] | "
                f"STATUS={login_res.status_code} | RESPONSE={login_res.text}"
            )
        return login_res.json().get("access_token")


async def list_users_from_panel(panel: dict, page_size: int = 100, max_users: int = 1000) -> list:
    """
    دریافت لیست کاربران از API مرزبان (/api/users).
    هر آیتم دیکشنری خام مرزبان است.
    """
    token = await get_panel_token(panel)
    headers = {"Authorization": f"Bearer {token}"}
    base = panel["url"].rstrip("/")
    users = []
    offset = 0
    async with httpx.AsyncClient(timeout=45.0, verify=False) as client:
        while offset < max_users:
            res = await client.get(
                f"{base}/api/users",
                headers=headers,
                params={"limit": page_size, "offset": offset},
            )
            if res.status_code != 200:
                raise Exception(
                    f"list users failed [{panel.get('name')}] "
                    f"HTTP {res.status_code}: {res.text[:200]}"
                )
            data = res.json()
            batch = data.get("users") if isinstance(data, dict) else data
            if not isinstance(batch, list) or not batch:
                break
            users.extend(batch)
            total = data.get("total") if isinstance(data, dict) else None
            offset += len(batch)
            if total is not None and offset >= total:
                break
            if len(batch) < page_size:
                break
    return users


def _format_panel_user_row(u: dict, panel_name: str, panel_type: str) -> dict:
    """استانداردسازی اطلاعات یک کاربر پنل برای نمایش"""
    username = u.get("username") or "—"
    status = (u.get("status") or "").lower()
    expire_ts = u.get("expire") or 0
    used = u.get("used_traffic") or 0
    limit = u.get("data_limit") or 0
    now_ts = int(datetime.now().timestamp())

    is_on = status == "active"
    if expire_ts and expire_ts > 0 and expire_ts < now_ts:
        is_on = False
    if status in ("expired", "disabled", "on_hold", "limited"):
        # limited ممکن است هنوز روشن باشد ولی حجم تمام شده
        if status in ("expired", "disabled"):
            is_on = False

    if expire_ts and expire_ts > 0:
        try:
            expire_txt = datetime.fromtimestamp(expire_ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            expire_txt = str(expire_ts)
    else:
        expire_txt = "بدون انقضا"

    if limit and limit > 0:
        used_gb = used / (1024 ** 3)
        limit_gb = limit / (1024 ** 3)
        vol_txt = f"{used_gb:.2f}/{limit_gb:.0f} GB"
        percent = min(100, int((used / limit) * 100)) if limit else 0
    elif limit == 0:
        used_gb = used / (1024 ** 3) if used else 0
        vol_txt = f"نامحدود (مصرف: {used_gb:.2f} GB)"
        percent = 0
    else:
        vol_txt = "—"
        percent = 0

    status_map = {
        "active": "🟢 فعال",
        "disabled": "🔴 غیرفعال",
        "expired": "⏰ منقضی",
        "limited": "🟡 اتمام حجم",
        "on_hold": "⏸ معلق",
    }
    status_fa = status_map.get(status, status or "—")

    return {
        "username": username,
        "status": status,
        "status_fa": status_fa,
        "is_on": is_on,
        "expire": expire_txt,
        "expire_ts": expire_ts or 0,
        "volume": vol_txt,
        "percent": percent,
        "used": used,
        "limit": limit,
        "panel_name": panel_name,
        "panel_type": panel_type,
        "note": (u.get("note") or "")[:80],
        "subscription_url": u.get("subscription_url") or "",
    }


async def collect_panel_users_snapshot() -> dict:
    """
    از همه پنل‌های فعال کاربران را می‌گیرد.
    اگر چند نوع پنل روی یک URL باشند فقط یک‌بار می‌خواند.
    """
    type_labels = {
        "holland": "🇳🇱 هلند",
        "multi": "🌐 مولتی",
        "unlimited": "💎 نامحدود",
        "test": "🧪 تست",
        "main": "🇳🇱 اصلی",
    }
    seen_urls = set()
    all_rows = []
    errors = []
    per_panel_stats = []

    for ptype in ("holland", "multi", "unlimited", "test"):
        try:
            panel = await get_panel(ptype)
        except Exception as e:
            errors.append(f"{ptype}: {e}")
            continue
        url = (panel.get("url") or "").rstrip("/")
        if not url:
            continue
        # جلوگیری از خواندن تکراری همان پنل فیزیکی
        key = (url, panel.get("username"), panel.get("password"))
        if key in seen_urls:
            continue
        seen_urls.add(key)

        pname = panel.get("name") or type_labels.get(ptype, ptype)
        try:
            raw_users = await list_users_from_panel(panel)
            rows = [_format_panel_user_row(u, pname, ptype) for u in raw_users]
            on_count = sum(1 for r in rows if r["is_on"])
            per_panel_stats.append({
                "name": pname,
                "type": ptype,
                "total": len(rows),
                "active": on_count,
                "error": None,
            })
            all_rows.extend(rows)
        except Exception as e:
            logger.error(f"collect panel users [{pname}]: {e}")
            errors.append(f"{pname}: {e}")
            per_panel_stats.append({
                "name": pname,
                "type": ptype,
                "total": 0,
                "active": 0,
                "error": str(e)[:120],
            })

    # یکتا بر اساس username+panel_name
    dedup = {}
    for r in all_rows:
        dedup[(r["username"], r["panel_name"])] = r
    all_rows = list(dedup.values())
    active_rows = [r for r in all_rows if r["is_on"]]
    active_rows.sort(key=lambda x: (x.get("panel_name") or "", x.get("username") or ""))
    all_rows.sort(key=lambda x: (x.get("panel_name") or "", x.get("username") or ""))

    return {
        "all": all_rows,
        "active": active_rows,
        "stats": per_panel_stats,
        "errors": errors,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


async def get_user_from_panel(username: str, is_test: bool = False, server_type: str = None) -> Optional[dict]:
    """
    دریافت اطلاعات کاربر از مرزبان.
    چند روش امتحان می‌شود تا اگر نام کمی فرق داشت باز هم پیدا شود.
    """
    if not username:
        return None
    username = str(username).strip()
    try:
        from urllib.parse import quote
        panel = await get_panel_for_server(server_type, is_test=is_test)
        token = await get_panel_token(panel)
        headers = {"Authorization": f"Bearer {token}"}
        base = panel["url"].rstrip("/")

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            # 1) دریافت مستقیم با URL-encode
            encoded = quote(username, safe="")
            res = await client.get(f"{base}/api/user/{encoded}", headers=headers)
            if res.status_code == 200:
                return res.json()

            # 2) جستجو در لیست کاربران (اگر نام دقیق match نشد)
            try:
                res2 = await client.get(
                    f"{base}/api/users",
                    headers=headers,
                    params={"username": username, "limit": 50},
                )
                if res2.status_code == 200:
                    data = res2.json()
                    users = data.get("users") if isinstance(data, dict) else data
                    if isinstance(users, list):
                        for u in users:
                            if (u.get("username") or "").lower() == username.lower():
                                return u
                        # اگر فقط یک نتیجه نزدیک بود
                        if len(users) == 1 and users[0].get("username"):
                            return users[0]
            except Exception as e:
                logger.warning(f"users search fallback: {e}")

            logger.warning(
                f"get_user_from_panel: user not found username={username!r} "
                f"status={res.status_code} body={res.text[:200]}"
            )
            return None
    except Exception as e:
        logger.error(f"get_user_from_panel error ({server_type}): {e}")
        return None


async def modify_user_in_panel(username: str, payload: dict, is_test: bool = False, server_type: str = None) -> dict:
    panel = await get_panel_for_server(server_type, is_test=is_test)
    token = await get_panel_token(panel)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        from urllib.parse import quote
        res = await client.put(
            f"{panel['url'].rstrip('/')}/api/user/{quote(str(username), safe='')}",
            json=payload,
            headers=headers
        )
        if res.status_code not in (200, 201):
            raise Exception(f"خطا در ویرایش کاربر: {res.text}")
        return res.json()


async def delete_user_from_panel(username: str, is_test: bool = False, server_type: str = None) -> bool:
    try:
        panel = await get_panel_for_server(server_type, is_test=is_test)
        token = await get_panel_token(panel)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            from urllib.parse import quote
            res = await client.delete(
                f"{panel['url'].rstrip('/')}/api/user/{quote(str(username), safe='')}",
                headers=headers
            )
            return res.status_code in (200, 204, 500)
    except Exception as e:
        logger.error(f"delete_user error ({server_type}): {e}")
        return False


async def _fetch_panel_proxies_inbounds(client, panel_url: str, headers: dict) -> tuple:
    """
    از API مرزبان inboundهای موجود را می‌گیرد و proxies/inbounds مناسب می‌سازد.
    اگر API در دسترس نبود، بدون inbounds اجباری (همه inboundهای پروتکل) تلاش می‌کند.
    """
    proxies = {}
    inbounds = {}

    # روش ۱: /api/inbounds (مرزبان)
    try:
        res = await client.get(f"{panel_url}/api/inbounds", headers=headers)
        if res.status_code == 200:
            data = res.json()
            # فرمت معمول: {"vless": [{"tag": "..."}, ...], "vmess": [...], ...}
            if isinstance(data, dict):
                for proto, items in data.items():
                    tags = []
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                tag = item.get("tag") or item.get("tag_name")
                                if tag:
                                    tags.append(tag)
                            elif isinstance(item, str):
                                tags.append(item)
                    elif isinstance(items, dict):
                        # بعضی نسخه‌ها tag را کلید می‌کنند
                        tags = list(items.keys())
                    if tags:
                        proto_l = str(proto).lower()
                        inbounds[proto_l] = tags
                        if proto_l == "vless":
                            proxies["vless"] = {}
                        elif proto_l == "vmess":
                            proxies["vmess"] = {}
                        elif proto_l == "trojan":
                            proxies["trojan"] = {}
                        elif proto_l == "shadowsocks":
                            proxies["shadowsocks"] = {"method": "chacha20-ietf-poly1305"}
            if proxies:
                return proxies, inbounds
    except Exception as e:
        logger.warning(f"fetch inbounds failed: {e}")

    # روش ۲: از /api/system یا core سعی در خواندن
    try:
        res = await client.get(f"{panel_url}/api/system", headers=headers)
        if res.status_code == 200:
            sysdata = res.json() if res.content else {}
            # بعضی نسخه‌ها لیست inbound ندارند؛ نادیده می‌گیریم
            _ = sysdata
    except Exception:
        pass

    # روش ۳: fallback — فقط vless بدون محدود کردن inbound
    # مرزبان معمولاً همه inboundهای آن پروتکل را اختصاص می‌دهد
    proxies = {"vless": {}}
    inbounds = {}
    return proxies, inbounds


async def create_config_from_panel(
    username: str,
    volume_gb: int,
    days: int = 30,
    is_test: bool = False,
    is_unlimited: bool = False,
    server_type: str = None,
):
    """
    ساخت کانفیگ از پنل مربوط به نوع سرور (همه روی مرزبان).
    """
    if is_test:
        server_type = "test"
    elif is_unlimited:
        server_type = "unlimited"
    elif not server_type:
        server_type = "holland"

    panel = await get_panel_for_server(server_type, is_test=is_test)
    panel_url = panel["url"]
    panel_user = panel["username"]
    panel_pass = panel["password"]
    panel_label = panel.get("name") or panel.get("panel_type") or server_type

    if is_test:
        test_mb = await get_int_setting("test_volume_mb", 30)
        data_limit = test_mb * 1024 * 1024
        expire_days = 1
    elif is_unlimited or server_type == "unlimited":
        data_limit = 0  # نامحدود
        expire_days = volume_gb * 30
    else:
        data_limit = volume_gb * 1024 * 1024 * 1024
        if days is None or days <= 0:
            days = await get_int_setting("service_days", 30)
        expire_days = days

    expire_timestamp = int(
        (datetime.now() + timedelta(days=expire_days)).timestamp()
    )

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        login_data = {"username": panel_user, "password": panel_pass}
        login_res = await client.post(f"{panel_url}/api/admin/token", data=login_data)

        if login_res.status_code != 200:
            raise Exception(
                f"LOGIN FAILED [{panel_label}] | STATUS={login_res.status_code} | "
                f"URL={login_res.url} | RESPONSE={login_res.text}"
            )

        token = login_res.json().get("access_token")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # دریافت inboundهای واقعی پنل (به‌جای نام ثابت که ممکن است وجود نداشته باشد)
        proxies, inbounds = await _fetch_panel_proxies_inbounds(client, panel_url, headers)
        logger.info(f"[{panel_label}] proxies={list(proxies.keys())} inbounds={inbounds}")

        user_payload = {
            "username": username,
            "proxies": proxies,
            "inbounds": inbounds,
            "expire": expire_timestamp,
            "data_limit": data_limit,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": f"ساخته شده توسط ربات | پنل: {panel_label} | سرور: {server_type}"
        }

        create_res = await client.post(
            f"{panel_url}/api/user",
            json=user_payload,
            headers=headers
        )

        if create_res.status_code not in [200, 201]:
            if "already exists" in create_res.text.lower() or create_res.status_code == 409:
                username = username + "_" + ''.join(random.choices(string.digits, k=3))
                user_payload["username"] = username
                create_res = await client.post(
                    f"{panel_url}/api/user",
                    json=user_payload,
                    headers=headers
                )

            if create_res.status_code not in [200, 201]:
                raise Exception(f"خطا در ساخت کاربر [{panel_label}]: {create_res.text}")

        user_data = create_res.json()
        subscription_url = user_data.get("subscription_url")

        if not subscription_url:
            subscription_url = f"{panel_url}/sub/{username}"
        elif not subscription_url.startswith("http"):
            subscription_url = f"{panel_url.rstrip('/')}/{subscription_url.lstrip('/')}"

        if is_test:
            test_mb = await get_int_setting("test_volume_mb", 30)
            vol_text = f"{test_mb} مگابایت"
        elif is_unlimited or server_type == "unlimited":
            vol_text = "نامحدود"
        else:
            vol_text = f"{volume_gb} گیگابایت"

        return {
            "username": username,
            "subscription_url": subscription_url,
            "config_link": user_data.get("links", [""])[0] if user_data.get("links") else subscription_url,
            "expire": f"{expire_days} روز",
            "volume": vol_text,
            "panel": panel_label,
            "server_type": server_type,
        }

def generate_qr(data: str) -> BytesIO:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio


def generate_tracking_code(length: int = 10) -> str:
    """کد رهگیری رندوم برای سفارش‌های تحویل‌شده"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ==================== جاب‌های پس‌زمینه ====================
async def _do_auto_renew(bot, order_id: int, user_id: int, username: str, vol: int, server_type: str) -> bool:
    """
    تلاش برای تمدید خودکار یک سرویس از کیف پول.
    True = موفق | False = ناموفق (موجودی کم یا خطا)
    """
    try:
        # قیمت تمدید از تعرفه
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                "SELECT price FROM tariffs WHERE server_type = ? AND volume_gb = ? AND is_active = 1 LIMIT 1",
                (server_type, vol)
            ) as cur:
                price_row = await cur.fetchone()
            price = price_row[0] if price_row else 0
            if price <= 0:
                # برای custom یا نامحدود از price_per_day تقریبی
                if server_type == "unlimited":
                    price = 0  # نامحدود معمولاً ماهانه است؛ اگر تعرفه نبود رد کن
                else:
                    logger.warning(f"auto_renew: no tariff for order #{order_id}")
                    return False

            async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
                bal_row = await cur.fetchone()
            balance = bal_row[0] if bal_row else 0

            if balance < price:
                # موجودی کافی نیست — اطلاع به کاربر
                try:
                    await bot.send_message(
                        user_id,
                        f"⚠️ <b>تمدید خودکار ناموفق</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"سرویس <code>{username}</code> نزدیک انقضاست و تمدید خودکار روشن است،\n"
                        f"اما موجودی کیف پول کافی نیست.\n\n"
                        f"💰 قیمت تمدید: <b>{price:,}</b> تومان\n"
                        f"💳 موجودی شما: <b>{balance:,}</b> تومان\n\n"
                        f"لطفاً کیف پول را شارژ کنید یا دستی تمدید کنید.",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💰 شارژ کیف پول", callback_data="wallet")],
                            [InlineKeyboardButton("🔄 تمدید دستی", callback_data=f"renew_{order_id}")],
                        ])
                    )
                except Exception:
                    pass
                return False

            # کسر موجودی
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
            await db.commit()

        # تمدید در پنل
        user_data = await get_user_from_panel(username, server_type=server_type)
        if not user_data:
            # برگرداندن موجودی
            async with aiosqlite.connect("bot.db") as db:
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (price, user_id))
                await db.commit()
            return False

        current_expire = user_data.get("expire") or 0
        current_limit = user_data.get("data_limit") or 0
        service_days = await get_int_setting("service_days", 30)
        add_bytes = vol * 1024 * 1024 * 1024 if server_type != "unlimited" else 0
        new_limit = (current_limit or 0) + add_bytes if server_type != "unlimited" else 0
        now_ts = int(datetime.now().timestamp())
        base_expire = max(current_expire or 0, now_ts)
        if server_type == "unlimited":
            # برای نامحدود معمولاً volume_gb = ماه
            new_expire = base_expire + (vol * 30 * 86400)
        else:
            new_expire = base_expire + (service_days * 86400)

        payload = {"expire": new_expire, "status": "active"}
        if server_type != "unlimited":
            payload["data_limit"] = new_limit
        await modify_user_in_panel(username, payload, server_type=server_type)

        # ثبت سفارش تمدید + ریست فلگ‌ها
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price,
                   config_name, status, created_at, panel_username, config_data)
                   VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)""",
                (user_id, server_type, vol, price, price, username,
                 datetime.now().isoformat(), username,
                 json.dumps({"renewed_from": order_id, "type": "auto_renew"}))
            )
            await db.execute(
                "UPDATE orders SET warned_85 = 0, expire_warned = 0, balance_warned = 0 WHERE id = ?",
                (order_id,),
            )
            await db.commit()

        try:
            await notify_admin_sale(
                bot,
                kind="auto_renew",
                order_id=order_id,
                user_id=user_id,
                amount=price,
                plan=f"{server_type} — {vol}G (تمدید خودکار)",
                payment="کیف پول",
            )
        except Exception:
            pass

        try:
            await bot.send_message(
                user_id,
                f"✅ <b>تمدید خودکار موفق</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"سرویس <code>{username}</code> به‌صورت خودکار تمدید شد.\n\n"
                f"📊 حجم اضافه: <b>{vol}</b> گیگ\n"
                f"⏳ اعتبار اضافه: <b>{service_days if server_type != 'unlimited' else vol * 30}</b> روز\n"
                f"💰 مبلغ کسرشده: <b>{price:,}</b> تومان\n"
                f"💳 موجودی جدید: <b>{balance - price:,}</b> تومان",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        logger.info(f"Auto-renew OK order=#{order_id} user={user_id} price={price}")
        return True
    except Exception as e:
        logger.error(f"_do_auto_renew error order={order_id}: {e}")
        return False


async def check_usage_and_expire(context: ContextTypes.DEFAULT_TYPE):
    """هر ساعت: هشدار ۸۵٪ مصرف + هشدار انقضا + تمدید خودکار + غیرفعال‌سازی کدهای منقضی"""
    try:
        # خاموش کردن خودکار تعمیرات زمان‌دار
        try:
            await is_maintenance()  # داخل خودش maintenance_until را چک و پاک می‌کند
        except Exception:
            pass

        # غیرفعال کردن خودکار کدهای تخفیف منقضی‌شده
        try:
            now_iso = datetime.now().isoformat()
            async with aiosqlite.connect("bot.db") as db:
                await db.execute(
                    """UPDATE discount_codes SET is_active = 0
                       WHERE is_active = 1 AND expires_at IS NOT NULL AND expires_at < ?""",
                    (now_iso,)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"deactivate expired discounts: {e}")

        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT id, user_id, config_name, panel_username, volume_gb, config_data,
                          warned_85, expire_warned, server_type, auto_renew, balance_warned
                   FROM orders WHERE status = 'paid' AND (config_name IS NOT NULL OR panel_username IS NOT NULL)"""
            ) as cur:
                orders = await cur.fetchall()

        for order_id, user_id, conf_name, panel_username, vol, conf_data, warned_85, expire_warned, server_type, auto_renew, balance_warned in orders:
            lookup_name = (panel_username or conf_name or "").strip()
            if not lookup_name:
                if conf_data:
                    try:
                        lookup_name = json.loads(conf_data).get("username") or ""
                    except Exception:
                        pass
            if not lookup_name:
                continue
            try:
                user_info = await get_user_from_panel(lookup_name, server_type=server_type)
                if not user_info:
                    continue

                used = user_info.get("used_traffic") or 0
                limit = user_info.get("data_limit") or 0
                expire_ts = user_info.get("expire") or 0

                # هشدار ۸۵٪
                if limit > 0 and not warned_85:
                    percent = (used / limit) * 100
                    if percent >= USAGE_WARNING_PERCENT:
                        try:
                            await context.bot.send_message(
                                user_id,
                                f"⚠️ <b>هشدار مصرف حجم</b>\n\n"
                                f"سرویس شما (<code>{conf_name}</code>) به {percent:.0f}٪ مصرف رسیده است.\n"
                                f"برای جلوگیری از قطع شدن، سرویس را تمدید کنید.",
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_{order_id}")],
                                    [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")]
                                ])
                            )
                            async with aiosqlite.connect("bot.db") as db:
                                await db.execute(
                                    "UPDATE orders SET warned_85 = 1 WHERE id = ?", (order_id,)
                                )
                                await db.commit()
                        except Exception as e:
                            logger.error(f"send 85% warn error: {e}")

                # هشدار کمبود موجودی برای تمدید خودکار (زودتر از لحظه تمدید)
                if expire_ts and (auto_renew or 0) and not (balance_warned or 0):
                    now_ts = int(datetime.now().timestamp())
                    hours_left = (expire_ts - now_ts) / 3600
                    if 0 < hours_left <= BALANCE_WARN_HOURS:
                        try:
                            async with aiosqlite.connect("bot.db") as db:
                                async with db.execute(
                                    "SELECT price FROM tariffs WHERE server_type = ? AND volume_gb = ? AND is_active = 1 LIMIT 1",
                                    (server_type, vol),
                                ) as cur:
                                    pr = await cur.fetchone()
                                renew_price = pr[0] if pr else 0
                                async with db.execute(
                                    "SELECT balance FROM users WHERE user_id = ?", (user_id,)
                                ) as cur:
                                    br = await cur.fetchone()
                                bal = br[0] if br else 0
                            if renew_price > 0 and bal < renew_price:
                                need = renew_price - bal
                                await context.bot.send_message(
                                    user_id,
                                    f"💳 <b>یادآوری شارژ کیف پول</b>\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"تمدید خودکار سرویس <code>{lookup_name}</code> روشن است،\n"
                                    f"اما موجودی برای تمدید کافی نیست.\n\n"
                                    f"⏳ حدود <b>{int(hours_left)}</b> ساعت تا انقضا\n"
                                    f"💰 هزینه تمدید: <b>{renew_price:,}</b> تومان\n"
                                    f"💳 موجودی فعلی: <b>{bal:,}</b> تومان\n"
                                    f"➕ کمبود: <b>{need:,}</b> تومان\n\n"
                                    f"قبل از انقضا کیف پول را شارژ کنید تا سرویس قطع نشود.",
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("💰 شارژ کیف پول", callback_data="wallet")],
                                        [InlineKeyboardButton("🔄 تمدید دستی", callback_data=f"renew_{order_id}")],
                                        [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")],
                                    ]),
                                )
                                async with aiosqlite.connect("bot.db") as db:
                                    await db.execute(
                                        "UPDATE orders SET balance_warned = 1 WHERE id = ?",
                                        (order_id,),
                                    )
                                    await db.commit()
                        except Exception as e:
                            logger.error(f"balance warn order {order_id}: {e}")

                # تمدید خودکار (قبل از هشدار انقضا)
                if expire_ts and (auto_renew or 0):
                    now_ts = int(datetime.now().timestamp())
                    hours_left = (expire_ts - now_ts) / 3600
                    if 0 < hours_left <= AUTO_RENEW_HOURS:
                        # جلوگیری از تمدید چندباره: اگر اخیراً auto_renew ثبت شده باشد رد کن
                        async with aiosqlite.connect("bot.db") as db:
                            cutoff = (datetime.now() - timedelta(hours=AUTO_RENEW_HOURS + 1)).isoformat()
                            async with db.execute(
                                """SELECT 1 FROM orders
                                   WHERE user_id = ? AND panel_username = ?
                                     AND status = 'paid'
                                     AND config_data LIKE '%"type": "auto_renew"%'
                                     AND created_at >= ?
                                   LIMIT 1""",
                                (user_id, lookup_name, cutoff)
                            ) as cur:
                                already = await cur.fetchone()
                        if not already:
                            await _do_auto_renew(
                                context.bot, order_id, user_id, lookup_name, vol, server_type
                            )
                            # بعد از تمدید موفق، فلگ‌ها ریست می‌شوند؛ ادامه نده
                            continue

                # هشدار انقضا (فقط اگر auto_renew خاموش باشد یا تمدید نشد)
                if expire_ts and not expire_warned:
                    now_ts = int(datetime.now().timestamp())
                    hours_left = (expire_ts - now_ts) / 3600
                    if 0 < hours_left <= EXPIRE_WARN_HOURS:
                        try:
                            await context.bot.send_message(
                                user_id,
                                f"⏰ <b>هشدار انقضای سرویس</b>\n\n"
                                f"سرویس شما (<code>{conf_name}</code>) کمتر از {EXPIRE_WARN_HOURS} ساعت دیگر منقضی می‌شود.\n"
                                f"برای ادامه استفاده، همین حالا تمدید کنید.",
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_{order_id}")],
                                    [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")]
                                ])
                            )
                            async with aiosqlite.connect("bot.db") as db:
                                await db.execute(
                                    "UPDATE orders SET expire_warned = 1 WHERE id = ?", (order_id,)
                                )
                                await db.commit()
                        except Exception as e:
                            logger.error(f"send expire warn error: {e}")

            except Exception as e:
                logger.error(f"check order {order_id} error: {e}")

    except Exception as e:
        logger.error(f"check_usage_and_expire job error: {e}")

async def cleanup_old_tests(context: ContextTypes.DEFAULT_TYPE):
    """حذف خودکار اکانت‌های تست قدیمی"""
    try:
        cutoff = (datetime.now() - timedelta(hours=TEST_DELETE_AFTER_HOURS)).isoformat()
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                "SELECT id, username FROM test_accounts WHERE created_at < ?", (cutoff,)
            ) as cur:
                old_tests = await cur.fetchall()

            for tid, username in old_tests:
                success = await delete_user_from_panel(username, is_test=True)
                if success:
                    await db.execute("DELETE FROM test_accounts WHERE id = ?", (tid,))
                    logger.info(f"Deleted old test user: {username}")
            await db.commit()
    except Exception as e:
        logger.error(f"cleanup_old_tests error: {e}")


async def cleanup_expired_configs(context: ContextTypes.DEFAULT_TYPE):
    """حذف خودکار کانفیگ‌های منقضی‌شده از پنل و به‌روزرسانی دیتابیس"""
    try:
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT id, user_id, config_name, panel_username, config_data, server_type
                   FROM orders WHERE status = 'paid' AND config_name IS NOT NULL"""
            ) as cur:
                orders = await cur.fetchall()

        deleted_count = 0
        for order_id, user_id, conf_name, panel_username, conf_data, server_type in orders:
            username = panel_username or conf_name
            if not username:
                continue
            try:
                user_info = await get_user_from_panel(username, server_type=server_type)
                if not user_info:
                    continue

                expire_ts = user_info.get("expire") or 0
                status = user_info.get("status", "")
                now_ts = int(datetime.now().timestamp())

                # اگر منقضی شده یا وضعیت expired/disabled
                is_expired = False
                if expire_ts and expire_ts > 0 and expire_ts < now_ts:
                    is_expired = True
                if status in ("expired", "disabled"):
                    is_expired = True

                if is_expired:
                    # حذف از پنل مربوطه
                    success = await delete_user_from_panel(username, is_test=False, server_type=server_type)
                    if success:
                        async with aiosqlite.connect("bot.db") as db:
                            await db.execute(
                                "UPDATE orders SET status = 'expired' WHERE id = ?", (order_id,)
                            )
                            await db.commit()
                        deleted_count += 1
                        logger.info(f"Expired config deleted: {username} (order #{order_id})")

                        # اطلاع به کاربر (اختیاری)
                        try:
                            await context.bot.send_message(
                                user_id,
                                f"⏰ <b>سرویس منقضی شد</b>\n\n"
                                f"سرویس شما (<code>{username}</code>) منقضی شده و از پنل حذف گردید.\n"
                                f"برای ادامه استفاده می‌توانید سرویس جدید خریداری کنید.",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"cleanup_expired order {order_id}: {e}")

        if deleted_count:
            logger.info(f"cleanup_expired_configs: {deleted_count} configs removed")
    except Exception as e:
        logger.error(f"cleanup_expired_configs job error: {e}")

# ==================== هندلرها ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args and args[0].startswith("ref_"):
        ref_code = args[0][4:]
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,)) as cur:
                row = await cur.fetchone()
            if row and row[0] != user.id:
                is_new = await get_or_create_user(user.id, user.username, user.full_name)
                if is_new:
                    bonus = await get_int_setting("referral_bonus", 5000)
                    await db.execute(
                        "UPDATE users SET referred_by = ? WHERE user_id = ?",
                        (row[0], user.id)
                    )
                    await db.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                        (bonus, row[0])
                    )
                    await db.commit()
                    try:
                        await context.bot.send_message(
                            row[0],
                            f"🎉 یک نفر با لینک دعوت شما وارد ربات شد!\n"
                            f"مبلغ {bonus:,} تومان به کیف پول شما اضافه شد."
                        )
                    except:
                        pass

    await get_or_create_user(user.id, user.username, user.full_name)

    if await is_banned(user.id):
        await update.message.reply_text("🚫 شما از استفاده از این ربات محروم شده‌اید.")
        return

    if await is_maintenance() and not await is_admin(user.id):
        await update.message.reply_text(
            "🔧 ربات در حال حاضر در حالت تعمیرات است.\n"
            "لطفاً کمی بعد دوباره تلاش کنید."
        )
        return

    if not await check_membership(context.bot, user.id):
        channels = await get_join_channels(active_only=True)
        buttons = []
        ch_lines = []
        for _, ch in channels:
            ch_clean = ch.lstrip("@")
            # لینک عمومی برای یوزرنیم؛ برای آیدی عددی لینک مستقیم ممکن نیست
            if ch.startswith("@") or (not ch.lstrip("-").isdigit()):
                url = f"https://t.me/{ch_clean}"
                buttons.append([InlineKeyboardButton(f"📢 عضویت در {ch}", url=url)])
            else:
                buttons.append([InlineKeyboardButton(f"📢 کانال {ch}", callback_data="noop")])
            ch_lines.append(f"👉 {ch}")
        buttons.append([InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join")])
        text = (
            "🔒 برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو شوید:\n\n"
            + "\n".join(ch_lines)
            + "\n\nپس از عضویت روی دکمه «تایید عضویت» بزنید."
        )
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    welcome = await get_setting("welcome")
    admin = await is_admin(user.id)
    await update.message.reply_text(welcome, reply_markup=main_keyboard(admin))

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if await is_banned(user.id):
        await query.edit_message_text("🚫 شما از استفاده از این ربات محروم شده‌اید.")
        return

    if await is_maintenance() and not await is_admin(user.id):
        await query.edit_message_text(
            "🔧 ربات در حال حاضر در حالت تعمیرات است.\n"
            "لطفاً کمی بعد دوباره تلاش کنید."
        )
        return

    if await check_membership(context.bot, user.id):
        welcome = await get_setting("welcome")
        admin = await is_admin(user.id)
        await query.edit_message_text(welcome, reply_markup=main_keyboard(admin))
    else:
        await query.answer("❌ شما هنوز داخل کانال عضو نشده‌اید!", show_alert=True)

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    welcome = await get_setting("welcome")
    admin = await is_admin(user.id)

    if query.message and query.message.photo:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user.id,
            text=welcome,
            reply_markup=main_keyboard(admin),
            parse_mode=ParseMode.HTML
        )
        return

    try:
        await query.edit_message_text(
            text=welcome,
            reply_markup=main_keyboard(admin),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            chat_id=user.id,
            text=welcome,
            reply_markup=main_keyboard(admin),
            parse_mode=ParseMode.HTML
        )

# ---------- خرید سرویس ----------
async def buy_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 سرور هلند", callback_data="server_holland")],
        [InlineKeyboardButton("🌐 سرویس مولتی لوکیشن (وبگردی)", callback_data="server_multi")],
        [InlineKeyboardButton("💎 سرویس نامحدود", callback_data="server_unlimited")],
        [InlineKeyboardButton("⚙️ پلن دلخواه (Custom)", callback_data="server_custom")],
        [back_button()]
    ])
    await query.edit_message_text(
        "🛒 سرویس مورد نظر را انتخاب کنید:",
        reply_markup=kb
    )

async def show_tariffs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "server_holland":
        server = "holland"
    elif query.data == "server_unlimited":
        server = "unlimited"
    else:
        server = "multi"
    context.user_data["server_type"] = server

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT id, volume_gb, price FROM tariffs WHERE server_type = ? AND is_active = 1 ORDER BY volume_gb",
            (server,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text("در حال حاضر تعرفه‌ای فعال نیست.", reply_markup=InlineKeyboardMarkup([[back_button("buy_service")]]))
        return

    buttons = []
    for tid, vol, price in rows:
        if server == "unlimited":
            label = f"💎 {vol} ماهه — {price:,} تومان"
        else:
            label = f"{vol} گیگ — {price:,} تومان"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"select_tariff_{tid}"
        )])
    buttons.append([back_button("buy_service")])

    if server == "holland":
        title = "🇳🇱 سرور هلند"
        subtitle = "حجم مورد نظر را انتخاب کنید:"
    elif server == "unlimited":
        title = "💎 سرویس نامحدود"
        subtitle = "مدت اعتبار مورد نظر را انتخاب کنید:"
    else:
        title = "🌐 مولتی لوکیشن"
        subtitle = "حجم مورد نظر را انتخاب کنید:"

    await query.edit_message_text(f"{title}\n\n{subtitle}", reply_markup=InlineKeyboardMarkup(buttons))


# ---------- پلن دلخواه (Custom) ----------
async def start_custom_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await check_pending_limit(query.from_user.id):
        await query.answer(
            f"❌ شما حداکثر {MAX_PENDING_ORDERS} سفارش در انتظار دارید.",
            show_alert=True
        )
        return

    min_gb = await get_int_setting("custom_min_gb", 5)
    max_gb = await get_int_setting("custom_max_gb", 200)
    price_gb = await get_int_setting("custom_price_per_gb", 12000)
    price_day = await get_int_setting("custom_price_per_day", 3000)

    context.user_data["server_type"] = "custom"
    context.user_data["discount_code"] = None

    await query.edit_message_text(
        f"⚙️ <b>پلن دلخواه</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت هر گیگ: <b>{price_gb:,}</b> تومان\n"
        f"💰 قیمت هر روز: <b>{price_day:,}</b> تومان\n\n"
        f"📦 محدوده حجم: {min_gb} تا {max_gb} گیگ\n\n"
        f"✏️ حجم مورد نظر خود را به گیگابایت وارد کنید (مثال: 25):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("buy_service")]])
    )
    return CUSTOM_WAITING_GB


async def custom_receive_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        gb = int(update.message.text.strip().replace(",", ""))
        min_gb = await get_int_setting("custom_min_gb", 5)
        max_gb = await get_int_setting("custom_max_gb", 200)
        if not (min_gb <= gb <= max_gb):
            await update.message.reply_text(
                f"❌ حجم باید بین {min_gb} تا {max_gb} گیگ باشد. دوباره وارد کنید:"
            )
            return CUSTOM_WAITING_GB
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید:")
        return CUSTOM_WAITING_GB

    context.user_data["volume"] = gb
    min_days = await get_int_setting("custom_min_days", 7)
    max_days = await get_int_setting("custom_max_days", 90)

    await update.message.reply_text(
        f"✅ حجم: <b>{gb}</b> گیگ ثبت شد.\n\n"
        f"⏱ محدوده روز: {min_days} تا {max_days} روز\n\n"
        f"✏️ تعداد روز اعتبار را وارد کنید (مثال: 30):",
        parse_mode=ParseMode.HTML
    )
    return CUSTOM_WAITING_DAYS


async def custom_receive_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip().replace(",", ""))
        min_days = await get_int_setting("custom_min_days", 7)
        max_days = await get_int_setting("custom_max_days", 90)
        if not (min_days <= days <= max_days):
            await update.message.reply_text(
                f"❌ تعداد روز باید بین {min_days} تا {max_days} باشد. دوباره وارد کنید:"
            )
            return CUSTOM_WAITING_DAYS
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید:")
        return CUSTOM_WAITING_DAYS

    context.user_data["custom_days"] = days
    gb = context.user_data["volume"]
    price_gb = await get_int_setting("custom_price_per_gb", 12000)
    price_day = await get_int_setting("custom_price_per_day", 3000)

    price = (gb * price_gb) + (days * price_day)
    context.user_data["price"] = price
    context.user_data["final_price"] = price
    context.user_data["server_type"] = "custom"

    # انتخاب نام کاربری
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ وارد کردن نام کاربری", callback_data="enter_username")],
        [InlineKeyboardButton("🎲 خودکار انتخاب کن", callback_data="auto_username")],
        [back_button("buy_service")]
    ])
    await update.message.reply_text(
        f"✅ پلن دلخواه شما:\n"
        f"📦 حجم: <b>{gb}</b> گیگ\n"
        f"⏱ اعتبار: <b>{days}</b> روز\n"
        f"💰 قیمت: <b>{price:,}</b> تومان\n\n"
        f"لطفاً نام کاربری را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )
    return WAITING_USERNAME


async def select_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # محدودیت خرید همزمان
    if not await check_pending_limit(query.from_user.id):
        await query.answer(
            f"❌ شما حداکثر {MAX_PENDING_ORDERS} سفارش در انتظار دارید.\nابتدا آن‌ها را تکمیل کنید یا منتظر بمانید.",
            show_alert=True
        )
        return

    tariff_id = int(query.data.split("_")[-1])

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT volume_gb, price, server_type FROM tariffs WHERE id = ?", (tariff_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        await query.answer("تعرفه یافت نشد", show_alert=True)
        return

    vol, price, server = row
    context.user_data["tariff_id"] = tariff_id
    context.user_data["volume"] = vol
    context.user_data["price"] = price
    context.user_data["server_type"] = server
    context.user_data["final_price"] = price
    context.user_data["discount_code"] = None

    # برای نامحدود همان جریان قبلی (ماهانه)
    if server == "unlimited":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ وارد کردن نام کاربری", callback_data="enter_username")],
            [InlineKeyboardButton("🎲 خودکار انتخاب کن", callback_data="auto_username")],
            [back_button("buy_service")]
        ])
        await query.edit_message_text(
            "🛒 سرویس مورد نظر انتخاب شد.\n\n"
            "لطفا یک نام کاربری با حروف لاتین به طول حداکثر ۲۰ کاراکتر وارد نمایید 👇",
            reply_markup=kb
        )
        return WAITING_USERNAME

    # هلند و مولتی → انتخاب مدت
    default_days = await get_int_setting("service_days", 30)
    context.user_data["selected_days"] = default_days
    return await show_duration_select(update, context)

async def show_duration_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش صفحه انتخاب مدت اعتبار با دکمه‌های +/-"""
    query = update.callback_query
    server = context.user_data.get("server_type", "holland")
    vol = context.user_data.get("volume", 0)
    base_price = context.user_data.get("price", 0)
    days = context.user_data.get("selected_days", 30)
    price_per_day = await get_int_setting("price_per_day", 1000)
    min_days = await get_int_setting("min_service_days", 7)
    max_days = await get_int_setting("max_service_days", 90)

    # محدود کردن روز
    days = max(min_days, min(max_days, days))
    context.user_data["selected_days"] = days

    days_cost = days * price_per_day
    final = base_price + days_cost
    context.user_data["final_price"] = final

    if server == "holland":
        server_name = "🇳🇱 سرور هلند"
    else:
        server_name = "🌐 مولتی لوکیشن"

    text = (
        f"⏱ <b>انتخاب مدت اعتبار</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 پلن: {server_name} — <b>{vol}</b> گیگ\n"
        f"💰 قیمت پایه حجم: <b>{base_price:,}</b> تومان\n"
        f"📅 مدت فعلی: <b>{days}</b> روز\n"
        f"💵 هزینه مدت ({days} × {price_per_day:,}): <b>{days_cost:,}</b> تومان\n"
        f"💰 <b>قیمت نهایی: {final:,} تومان</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"با دکمه‌های زیر مدت را تنظیم کنید:"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖ ۱ روز", callback_data="days_adj_-1"),
            InlineKeyboardButton("➕ ۱ روز", callback_data="days_adj_+1"),
        ],
        [
            InlineKeyboardButton("➖ ۱۰ روز", callback_data="days_adj_-10"),
            InlineKeyboardButton("➕ ۱۰ روز", callback_data="days_adj_+10"),
        ],
        [
            InlineKeyboardButton("➖ ۱۵ روز", callback_data="days_adj_-15"),
            InlineKeyboardButton("➕ ۱۵ روز", callback_data="days_adj_+15"),
        ],
        [InlineKeyboardButton("✅ تأیید و ادامه", callback_data="days_confirm")],
        [back_button("buy_service")],
    ])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return WAITING_DURATION


async def adjust_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "selected_days" not in context.user_data or "price" not in context.user_data:
        await query.edit_message_text(
            "❌ اطلاعات سفارش ناقص است. لطفاً دوباره خرید را شروع کنید.",
            reply_markup=InlineKeyboardMarkup([[back_button("buy_service")]])
        )
        return ConversationHandler.END

    try:
        delta = int(query.data.replace("days_adj_", ""))
    except:
        return WAITING_DURATION

    min_days = await get_int_setting("min_service_days", 7)
    max_days = await get_int_setting("max_service_days", 90)
    days = context.user_data.get("selected_days", 30) + delta
    days = max(min_days, min(max_days, days))
    context.user_data["selected_days"] = days

    return await show_duration_select(update, context)


async def confirm_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "selected_days" not in context.user_data:
        await query.edit_message_text(
            "❌ اطلاعات ناقص است. دوباره تلاش کنید.",
            reply_markup=InlineKeyboardMarkup([[back_button("buy_service")]])
        )
        return ConversationHandler.END

    # برای سازگاری با مسیرهای قبلی (approve و ...)
    context.user_data["custom_days"] = context.user_data["selected_days"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ وارد کردن نام کاربری", callback_data="enter_username")],
        [InlineKeyboardButton("🎲 خودکار انتخاب کن", callback_data="auto_username")],
        [back_button("buy_service")]
    ])
    days = context.user_data["selected_days"]
    await query.edit_message_text(
        f"✅ مدت اعتبار: <b>{days}</b> روز ثبت شد.\n\n"
        "لطفا یک نام کاربری با حروف لاتین به طول حداکثر ۲۰ کاراکتر وارد نمایید 👇",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return WAITING_USERNAME


async def enter_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ نام کاربری مورد نظر را ارسال کنید (فقط حروف لاتین و عدد، حداکثر ۲۰ کاراکتر):"
    )
    return WAITING_USERNAME

async def auto_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = "user_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    context.user_data["config_name"] = name
    return await show_invoice(update, context)

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isascii() or not text.replace("_", "").isalnum() or len(text) > 20 or len(text) < 3:
        await update.message.reply_text(
            "❌ نام کاربری نامعتبر است.\n"
            "فقط حروف لاتین، عدد و زیرخط (_) مجاز است و باید بین ۳ تا ۲۰ کاراکتر باشد."
        )
        return WAITING_USERNAME

    # اگر از مسیر اکانت تست آمده باشد
    if context.user_data.get("is_test"):
        context.user_data.pop("is_test", None)
        await deliver_test(update, context, text)
        return ConversationHandler.END

    context.user_data["config_name"] = text
    return await show_invoice(update, context)

async def show_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "price" not in context.user_data or "server_type" not in context.user_data or "volume" not in context.user_data:
        err = "❌ اطلاعات سفارش ناقص است. لطفاً دوباره خرید را شروع کنید."
        if update.callback_query:
            await update.callback_query.edit_message_text(err, reply_markup=InlineKeyboardMarkup([[back_button("buy_service")]]))
        else:
            await update.message.reply_text(err, reply_markup=main_keyboard(False))
        return ConversationHandler.END

    price = context.user_data["price"]
    final = context.user_data.get("final_price", price)
    discount = context.user_data.get("discount_code")
    server = context.user_data["server_type"]
    vol = context.user_data["volume"]
    name = context.user_data.get("config_name", "—")

    user = update.effective_user if update.effective_user else update.callback_query.from_user
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
    balance = row[0] if row else 0

    selected_days = context.user_data.get("selected_days") or context.user_data.get("custom_days")

    if server == "holland":
        server_name = "🇳🇱 سرور هلند"
        plan_text = f"{vol} گیگ / {selected_days} روز" if selected_days else f"{vol} گیگ"
    elif server == "unlimited":
        server_name = "💎 سرویس نامحدود"
        plan_text = f"{vol} ماهه"
    elif server == "custom":
        server_name = "⚙️ پلن دلخواه"
        custom_days = context.user_data.get("custom_days", 30)
        plan_text = f"{vol} گیگ / {custom_days} روز"
    else:
        server_name = "🌐 مولتی لوکیشن"
        plan_text = f"{vol} گیگ / {selected_days} روز" if selected_days else f"{vol} گیگ"

    if discount:
        text = (
            f"🧾 <b>فاکتور سفارش شما</b>\n"
            f"—————————————\n"
            f"📦 {server_name} — {plan_text}\n"
            f"👤 نام کاربری: <code>{name}</code>\n"
            f"💵 قیمت اصلی: {price:,} تومان\n"
            f"🎟 کد تخفیف: <code>{discount}</code>\n"
            f"💰 قیمت نهایی: <b>{final:,} تومان</b>\n"
            f"💳 موجودی کیف پول: <b>{balance:,}</b> تومان\n"
            f"—————————————\n"
            f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
            f"👤 به نام: {CARD_NAME}\n\n"
            f"ℹ️ پس از واریز وجه، روی دکمه «📤 ارسال رسید» بزنید."
        )
        buttons = [
            [InlineKeyboardButton("📤 ارسال رسید", callback_data="send_receipt")],
        ]
        if balance >= final:
            buttons.append([InlineKeyboardButton("💰 پرداخت با کیف پول", callback_data="pay_with_wallet")])
        buttons.append([
            InlineKeyboardButton("🔄 تغییر کد تخفیف", callback_data="change_discount"),
            InlineKeyboardButton("❌ حذف تخفیف", callback_data="remove_discount")
        ])
        buttons.append([back_button("buy_service")])
        kb = InlineKeyboardMarkup(buttons)
    else:
        text = (
            f"🧾 <b>فاکتور سفارش شما</b>\n"
            f"—————————————\n"
            f"📦 {server_name} — {plan_text}\n"
            f"👤 نام کاربری: <code>{name}</code>\n"
            f"💰 قیمت: <b>{final:,} تومان</b>\n"
            f"💳 موجودی کیف پول: <b>{balance:,}</b> تومان\n"
            f"—————————————\n"
            f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
            f"👤 به نام: {CARD_NAME}\n\n"
            f"ℹ️ پس از واریز وجه، روی دکمه «📤 ارسال رسید» بزنید."
        )
        buttons = [
            [InlineKeyboardButton("📤 ارسال رسید", callback_data="send_receipt")],
        ]
        if balance >= final:
            buttons.append([InlineKeyboardButton("💰 پرداخت با کیف پول", callback_data="pay_with_wallet")])
        buttons.append([InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data="apply_discount")])
        buttons.append([back_button("buy_service")])
        kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def apply_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎟 کد تخفیف را وارد کنید:")
    return WAITING_DISCOUNT
async def tariffs_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    server_map = {
        "holland": "🇳🇱 سرویس‌های لوکیشن هلند",
        "multi": "🌐 سرویس‌های مولتی لوکیشن",
        "unlimited": "💎 سرویس‌های نامحدود",
    }

    server = query.data.replace("tariff_list_", "")
    server_name = server_map.get(server, "نامشخص")

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT volume_gb, price FROM tariffs WHERE server_type = ? AND is_active = 1 ORDER BY volume_gb",
            (server,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        text_msg = f"در حال حاضر هیچ تعرفه فعالی برای {server_name} ثبت نشده."
    else:
        text_msg = f"📊 <b>تعرفه {server_name}</b>\n\n"
        for vol, price in rows:
            if server == "unlimited":
                text_msg += f"• {vol} ماهه — <b>{price:,}</b> تومان\n"
            else:
                text_msg += f"• {vol} گیگ — <b>{price:,}</b> تومان\n"

    kb = InlineKeyboardMarkup([[back_button("tariffs_menu")]])

    await query.edit_message_text(text_msg, reply_markup=kb, parse_mode=ParseMode.HTML)


async def receive_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        code = update.message.text.strip().upper()
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT percent, max_uses, used_count, is_active, expires_at, starts_at
                   FROM discount_codes WHERE code = ?""",
                (code,)
            ) as cur:
                row = await cur.fetchone()

        if not row or not row[3]:
            await update.message.reply_text("❌ کد تخفیف معتبر نیست یا غیرفعال است.")
            return WAITING_DISCOUNT

        percent, max_uses, used, _, expires_at, starts_at = row
        now = datetime.now()

        # بررسی شروع کمپین
        if starts_at:
            try:
                start_dt = datetime.fromisoformat(starts_at)
                if now < start_dt:
                    await update.message.reply_text(
                        f"❌ این کد هنوز فعال نشده است.\n"
                        f"🕐 شروع: {start_dt.strftime('%Y-%m-%d %H:%M')}"
                    )
                    return WAITING_DISCOUNT
            except Exception:
                pass

        # بررسی انقضا
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if now > exp_dt:
                    await update.message.reply_text(
                        "❌ مهلت استفاده از این کد تخفیف به پایان رسیده است."
                    )
                    return WAITING_DISCOUNT
            except Exception:
                pass

        if max_uses > 0 and used >= max_uses:
            await update.message.reply_text("❌ ظرفیت استفاده از این کد به پایان رسیده است.")
            return WAITING_DISCOUNT

        # بررسی وجود اطلاعات سفارش
        if "price" not in context.user_data or "server_type" not in context.user_data or "volume" not in context.user_data:
            await update.message.reply_text(
                "❌ اطلاعات سفارش یافت نشد.\n"
                "لطفاً دوباره از ابتدا خرید را شروع کنید.",
                reply_markup=main_keyboard(await is_admin(update.effective_user.id))
            )
            return ConversationHandler.END

        # تخفیف روی قیمت نهایی (پایه + هزینه روزها)
        base = context.user_data["price"]
        days = context.user_data.get("selected_days") or context.user_data.get("custom_days") or 0
        if days and context.user_data.get("server_type") in ("holland", "multi", "custom"):
            price_per_day = await get_int_setting("price_per_day", 1000)
            if context.user_data.get("server_type") == "custom":
                total_before = context.user_data.get("final_price", base)
            else:
                total_before = base + (days * price_per_day)
        else:
            total_before = context.user_data.get("final_price", base)

        final = int(total_before * (100 - percent) / 100)
        context.user_data["discount_code"] = code
        context.user_data["final_price"] = final
        context.user_data["discount_percent"] = percent

        expire_note = ""
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                remain = exp_dt - now
                if remain.total_seconds() > 0:
                    hours_left = int(remain.total_seconds() // 3600)
                    mins_left = int((remain.total_seconds() % 3600) // 60)
                    if hours_left >= 24:
                        expire_note = f"\n⏰ اعتبار باقی‌مانده: حدود <b>{hours_left // 24}</b> روز"
                    elif hours_left > 0:
                        expire_note = f"\n⏰ اعتبار باقی‌مانده: <b>{hours_left}</b> ساعت و {mins_left} دقیقه"
                    else:
                        expire_note = f"\n⏰ اعتبار باقی‌مانده: کمتر از ۱ ساعت"
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ کد تخفیف <code>{code}</code> با <b>{percent}٪</b> اعمال شد.{expire_note}",
            parse_mode=ParseMode.HTML
        )
        return await show_invoice(update, context)
    except Exception as e:
        logger.error(f"receive_discount error: {e}")
        await update.message.reply_text(
            f"❌ خطا در اعمال کد تخفیف.\nلطفاً دوباره تلاش کنید یا از پشتیبانی کمک بگیرید.",
            reply_markup=main_keyboard(await is_admin(update.effective_user.id))
        )
        return ConversationHandler.END

async def change_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await apply_discount(update, context)

async def remove_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["discount_code"] = None
    base = context.user_data.get("price", 0)
    days = context.user_data.get("selected_days") or context.user_data.get("custom_days")
    if days and context.user_data.get("server_type") in ("holland", "multi"):
        price_per_day = await get_int_setting("price_per_day", 1000)
        context.user_data["final_price"] = base + (days * price_per_day)
    elif context.user_data.get("server_type") == "custom":
        # قیمت پلن دلخواه از قبل محاسبه شده — دوباره از volume/days حساب نکن
        gb = context.user_data.get("volume", 0)
        d = context.user_data.get("custom_days", 30)
        price_gb = await get_int_setting("custom_price_per_gb", 12000)
        price_day = await get_int_setting("custom_price_per_day", 3000)
        context.user_data["final_price"] = (gb * price_gb) + (d * price_day)
    else:
        context.user_data["final_price"] = base
    return await show_invoice(update, context)

async def pay_with_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    final = context.user_data.get("final_price", context.user_data.get("price", 0))
    server = context.user_data.get("server_type")
    vol = context.user_data.get("volume")
    conf_name = context.user_data.get("config_name")
    discount = context.user_data.get("discount_code")
    price = context.user_data.get("price", final)

    if not all([server, vol, conf_name]):
        await query.edit_message_text("❌ اطلاعات سفارش ناقص است. دوباره خرید کنید.")
        return

    if not await check_pending_limit(user.id):
        await query.answer(f"❌ حداکثر {MAX_PENDING_ORDERS} سفارش در انتظار مجاز است.", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
        balance = row[0] if row else 0

        if balance < final:
            await query.answer("❌ موجودی کیف پول کافی نیست!", show_alert=True)
            return

        tracking = generate_tracking_code()
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (final, user.id))
        cur = await db.execute(
            """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price,
               discount_code, config_name, status, created_at, panel_username, tracking_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)""",
            (user.id, server, vol, price, final, discount, conf_name, datetime.now().isoformat(), conf_name, tracking)
        )
        order_id = cur.lastrowid
        if discount:
            await db.execute(
                "UPDATE discount_codes SET used_count = used_count + 1 WHERE code = ?",
                (discount,)
            )
        await db.commit()

    try:
        service_days = await get_int_setting("service_days", 30)
        is_unlim = (server == "unlimited")
        if server == "custom":
            service_days = context.user_data.get("custom_days", service_days)
        elif context.user_data.get("selected_days"):
            service_days = context.user_data["selected_days"]
        elif context.user_data.get("custom_days"):
            service_days = context.user_data["custom_days"]
        config = await create_config_from_panel(
            conf_name, vol, days=service_days, is_unlimited=is_unlim, server_type=server
        )
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                "UPDATE orders SET config_data = ?, panel_username = ? WHERE id = ?",
                (json.dumps(config), config["username"], order_id)
            )
            await db.commit()

        qr = generate_qr(config["subscription_url"])
        caption = (
            f"✅ سفارش #{order_id} با موفقیت از کیف پول پرداخت و تحویل شد!\n\n"
            f"👤 نام کاربری: <code>{config['username']}</code>\n"
            f"🔗 لینک اشتراک:\n<code>{config['subscription_url']}</code>\n\n"
            f"🔖 کد رهگیری: <code>{tracking}</code>\n"
            f"💰 مبلغ کسر شده: {final:,} تومان"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⏳ زمان: {config['expire']}", callback_data="noop")],
            [InlineKeyboardButton(f"📊 حجم: {config['volume']}", callback_data="noop")],
            [
                InlineKeyboardButton("📷 QR CODE", callback_data=f"qr_{order_id}"),
                InlineKeyboardButton("📄 دانلود فایل", callback_data=f"dlcfg_{order_id}"),
            ],
            [InlineKeyboardButton("📖 آموزش استفاده", callback_data=f"guide_{order_id}")],
            [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_{order_id}")],
            [back_button()]
        ])
        await query.message.reply_photo(
            photo=InputFile(qr, "qr.png"),
            caption=caption,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        await query.edit_message_text(
            f"✅ پرداخت با کیف پول موفق بود.\nسفارش #{order_id} تحویل داده شد.\n🔖 کد رهگیری: <code>{tracking}</code>",
            parse_mode=ParseMode.HTML
        )
        # اعلان فروش به ادمین
        sname = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود", "custom": "دلخواه"}.get(server, server)
        plan_txt = f"{sname} — {vol}G" if server != "unlimited" else f"{sname} — {vol} ماهه"
        await notify_admin_sale(
            context.bot,
            kind="service",
            order_id=order_id,
            user_id=user.id,
            amount=final,
            plan=plan_txt,
            payment="کیف پول",
        )
        # هدیه خرید ۵ سرویس
        await maybe_grant_loyalty_gift(context.bot, user.id)
    except Exception as e:
        logger.error(e)
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final, user.id))
            await db.execute("UPDATE orders SET status = 'pending' WHERE id = ?", (order_id,))
            await db.commit()
        await query.edit_message_text(
            f"❌ خطا در ساخت کانفیگ. موجودی برگردانده شد.\nخطا: {str(e)[:100]}"
        )

    context.user_data.clear()

async def send_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 لطفاً عکس یا فایل رسید پرداخت رو همینجا ارسال کنید.")
    return WAITING_RECEIPT

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document

    if not photo and not document:
        await update.message.reply_text("لطفاً فقط عکس یا فایل ارسال کنید.")
        return WAITING_RECEIPT

    # جلوگیری از رسید تکراری
    receipt_uid = get_receipt_unique_id(update.message)
    if receipt_uid and await is_receipt_used(receipt_uid):
        await update.message.reply_text(
            "❌ این رسید قبلاً استفاده شده است.\n"
            "لطفاً رسید پرداخت جدید ارسال کنید."
        )
        return WAITING_RECEIPT

    if not await check_receipt_rate_limit(user.id):
        await update.message.reply_text(
            f"❌ تعداد ارسال رسید بیش از حد مجاز است.\n"
            f"حداکثر {RECEIPT_RATE_LIMIT_COUNT} رسید در {RECEIPT_RATE_LIMIT_MINUTES} دقیقه.\n"
            f"لطفاً کمی بعد دوباره تلاش کنید."
        )
        return WAITING_RECEIPT

    if not await check_pending_limit(user.id):
        await update.message.reply_text(f"❌ حداکثر {MAX_PENDING_ORDERS} سفارش در انتظار مجاز است.")
        return ConversationHandler.END

    # ذخیره روزهای انتخاب‌شده برای تأیید بعدی ادمین
    temp_config = None
    st = context.user_data.get("server_type")
    if st == "custom":
        temp_config = json.dumps({"custom_days": context.user_data.get("custom_days", 30), "type": "custom"})
    elif context.user_data.get("selected_days") or context.user_data.get("custom_days"):
        days_val = context.user_data.get("selected_days") or context.user_data.get("custom_days")
        temp_config = json.dumps({"custom_days": days_val, "type": st})

    tracking = generate_tracking_code()
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price, 
               discount_code, config_name, status, created_at, panel_username, config_data, tracking_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (
                user.id,
                context.user_data["server_type"],
                context.user_data["volume"],
                context.user_data["price"],
                context.user_data.get("final_price", context.user_data["price"]),
                context.user_data.get("discount_code"),
                context.user_data.get("config_name"),
                datetime.now().isoformat(),
                context.user_data.get("config_name"),
                temp_config,
                tracking
            )
        )
        order_id = cur.lastrowid
        if context.user_data.get("discount_code"):
            await db.execute(
                "UPDATE discount_codes SET used_count = used_count + 1 WHERE code = ?",
                (context.user_data["discount_code"],)
            )
        await db.commit()

    if receipt_uid:
        await store_receipt_id(receipt_uid, user.id, "order")

    st = context.user_data["server_type"]
    vol = context.user_data["volume"]
    sel_days = context.user_data.get("selected_days") or context.user_data.get("custom_days")
    if st == "holland":
        server_name = "🇳🇱 هلند"
        plan = f"{vol} گیگ / {sel_days} روز" if sel_days else f"{vol} گیگ"
    elif st == "unlimited":
        server_name = "💎 نامحدود"
        plan = f"{vol} ماهه"
    elif st == "custom":
        server_name = "⚙️ دلخواه"
        plan = f"{vol} گیگ / {context.user_data.get('custom_days', 30)} روز"
    else:
        server_name = "🌐 مولتی"
        plan = f"{vol} گیگ / {sel_days} روز" if sel_days else f"{vol} گیگ"
    admin_text = (
        f"🆕 سفارش جدید #{order_id}\n"
        f"—————————————\n"
        f"👤 کاربر: {user.full_name} (@{user.username or '—'})\n"
        f"🆔 آیدی عددی: <code>{user.id}</code>\n"
        f"📦 پلن: {server_name} — {plan}\n"
        f"💰 مبلغ: {context.user_data.get('final_price', context.user_data['price']):,} تومان\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"🕐 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید", callback_data=f"approve_order_{order_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_order_{order_id}")]
    ])

    if photo:
        await context.bot.send_photo(ADMIN_ID, photo.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_document(ADMIN_ID, document.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)

    await update.message.reply_text(
        f"✅ رسید شما با موفقیت ثبت شد.\n"
        f"شماره سفارش: <b>#{order_id}</b>\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n\n"
        f"لطفاً منتظر بررسی ادمین بمانید.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(await is_admin(user.id))
    )
    context.user_data.clear()
    return ConversationHandler.END

# ---------- تأیید / رد سفارش ----------
async def approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, server_type, volume_gb, config_name, final_price FROM orders WHERE id = ? AND status = 'pending'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("این سفارش قبلاً بررسی شده", show_alert=True)
            return
        user_id, server, vol, conf_name, price = row

        service_days = await get_int_setting("service_days", 30)
        is_unlim = (server == "unlimited")

        # روزهای انتخاب‌شده را از config_data موقت بخوان (دلخواه / هلند / مولتی)
        async with db.execute("SELECT config_data FROM orders WHERE id = ?", (order_id,)) as cur2:
            conf_row = await cur2.fetchone()
        if conf_row and conf_row[0]:
            try:
                temp = json.loads(conf_row[0])
                if temp.get("custom_days"):
                    service_days = temp["custom_days"]
            except:
                pass

        config = await create_config_from_panel(
            conf_name, vol, days=service_days, is_unlimited=is_unlim, server_type=server
        )
        # اگر کد رهگیری از قبل وجود نداشت، بساز
        async with db.execute("SELECT tracking_code FROM orders WHERE id = ?", (order_id,)) as cur_t:
            tr_row = await cur_t.fetchone()
        tracking = (tr_row[0] if tr_row and tr_row[0] else None) or generate_tracking_code()
        await db.execute(
            "UPDATE orders SET status = 'paid', config_data = ?, panel_username = ?, tracking_code = ? WHERE id = ?",
            (json.dumps(config), config["username"], tracking, order_id)
        )
        await db.commit()

    try:
        qr = generate_qr(config["subscription_url"])
        caption = (
            f"✅ سفارش #{order_id} تأیید شد!\n\n"
            f"👤 نام کاربری: <code>{config['username']}</code>\n"
            f"🔗 لینک اشتراک:\n<code>{config['subscription_url']}</code>\n\n"
            f"🔖 کد رهگیری: <code>{tracking}</code>\n\n"
            f"از دکمه‌های زیر می‌تونید استفاده کنید 👇"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⏳ زمان: {config['expire']}", callback_data="noop")],
            [InlineKeyboardButton(f"📊 حجم: {config['volume']}", callback_data="noop")],
            [
                InlineKeyboardButton("📷 QR CODE", callback_data=f"qr_{order_id}"),
                InlineKeyboardButton("📄 دانلود فایل", callback_data=f"dlcfg_{order_id}"),
            ],
            [InlineKeyboardButton("📖 آموزش استفاده", callback_data=f"guide_{order_id}")],
            [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_{order_id}")],
            [back_button()]
        ])
        await context.bot.send_photo(user_id, photo=InputFile(qr, "qr.png"), caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
        await context.bot.send_message(
            user_id,
            f"🎉 سفارش #{order_id} با موفقیت تأیید و تحویل داده شد.\n🔖 کد رهگیری: <code>{tracking}</code>",
            parse_mode=ParseMode.HTML
        )
        # هدیه خرید ۵ سرویس
        await maybe_grant_loyalty_gift(context.bot, user_id)
        await log_admin_action(query.from_user.id, "approve_order", order_id, f"user={user_id}")
        sname = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود", "custom": "دلخواه"}.get(server, server)
        plan_txt = f"{sname} — {vol}G" if server != "unlimited" else f"{sname} — {vol} ماهه"
        await notify_admin_sale(
            context.bot,
            kind="service",
            order_id=order_id,
            user_id=user_id,
            amount=price or 0,
            plan=plan_txt,
            payment="رسید / تأیید ادمین",
        )
    except Exception as e:
        logger.error(e)

    try:
        await query.edit_message_caption(caption=query.message.caption + "\n\n✅ تأیید شد توسط ادمین")
    except Exception:
        try:
            await query.edit_message_text((query.message.text or "") + "\n\n✅ تأیید شد توسط ادمین")
        except Exception:
            pass

async def reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id FROM orders WHERE id = ? AND status = 'pending'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("این سفارش قبلاً بررسی شده", show_alert=True)
            return
        user_id = row[0]

    context.user_data["reject_order_id"] = order_id
    context.user_data["reject_user_id"] = user_id
    context.user_data["reject_msg_chat"] = query.message.chat_id
    context.user_data["reject_msg_id"] = query.message.message_id
    context.user_data["reject_has_caption"] = bool(query.message.caption is not None)
    context.user_data["reject_orig_caption"] = query.message.caption or (query.message.text or "")

    # order_id داخل callback تا بدون state هم کار کند
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 مبلغ ناقص / مغایرت", callback_data=f"reject_preset_amount_{order_id}")],
        [InlineKeyboardButton("🖼 رسید نامشخص / ناخوانا", callback_data=f"reject_preset_unclear_{order_id}")],
        [InlineKeyboardButton("🔁 واریز تکراری", callback_data=f"reject_preset_duplicate_{order_id}")],
        [InlineKeyboardButton("⏰ رسید قدیمی / منقضی", callback_data=f"reject_preset_old_{order_id}")],
        [InlineKeyboardButton("❌ کارت اشتباه / گیرنده نادرست", callback_data=f"reject_preset_card_{order_id}")],
        [InlineKeyboardButton("⏭ ادامه بدون توضیحات", callback_data=f"reject_no_note_{order_id}")],
    ])
    text_msg = (
        f"❌ <b>رد سفارش #{order_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"دلیل آماده را انتخاب کنید، یا دلیل دلخواه را بنویسید و ارسال کنید.\n\n"
        f"یا روی «ادامه بدون توضیحات» بزنید."
    )
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=text_msg,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                text=text_msg,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text_msg,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    return ADMIN_REJECT_REASON


REJECT_PRESET_REASONS = {
    "amount": "مبلغ واریزی ناقص است یا با مبلغ فاکتور مغایرت دارد. لطفاً مابه‌التفاوت را واریز کرده و رسید جدید ارسال کنید.",
    "unclear": "رسید ارسالی نامشخص یا ناخواناست. لطفاً عکس واضح‌تری از رسید ارسال کنید.",
    "duplicate": "این رسید قبلاً برای سفارش دیگری استفاده شده است. لطفاً رسید پرداخت جدید ارسال کنید.",
    "old": "رسید ارسالی قدیمی یا منقضی است. لطفاً رسید پرداخت جدید و معتبر ارسال کنید.",
    "card": "واریز به کارت/گیرنده اشتباه انجام شده است. لطفاً به شماره کارت اعلام‌شده در ربات واریز کنید.",
}


async def _finish_reject_order(update, context, order_id: int, reason: Optional[str]):
    """اجرای نهایی رد سفارش — مستقل از ConversationHandler"""
    query = update.callback_query

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, status FROM orders WHERE id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            if query:
                await query.answer("سفارش یافت نشد", show_alert=True)
            return ConversationHandler.END
        user_id, status = row
        if status != "pending":
            if query:
                await query.answer("این سفارش قبلاً بررسی شده", show_alert=True)
            return ConversationHandler.END
        await db.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (order_id,))
        await db.commit()

    if reason:
        user_msg = (
            f"❌ <b>رسید شما توسط ادمین رد شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"شماره سفارش: <b>#{order_id}</b>\n\n"
            f"📝 توضیحات ادمین:\n{reason}\n\n"
            f"در صورت مشکل به پشتیبانی پیام دهید: {SUPPORT_USERNAME}"
        )
    else:
        user_msg = (
            f"❌ <b>رسید شما توسط ادمین رد شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"شماره سفارش: <b>#{order_id}</b>\n\n"
            f"در صورت مشکل به پشتیبانی پیام دهید: {SUPPORT_USERNAME}"
        )
    try:
        await context.bot.send_message(user_id, user_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"reject notify user {user_id}: {e}")
    try:
        aid = update.callback_query.from_user.id if update.callback_query else (update.effective_user.id if update.effective_user else 0)
        await log_admin_action(aid, "reject_order", order_id, reason or "بدون توضیح")
    except Exception:
        pass

    admin_suffix = "\n\n❌ رد شد توسط ادمین"
    if reason:
        admin_suffix += f"\n📝 دلیل: {reason}"

    # سعی کن پیام اصلی (رسید) را آپدیت کن
    chat_id = context.user_data.get("reject_msg_chat")
    msg_id = context.user_data.get("reject_msg_id")
    has_caption = context.user_data.get("reject_has_caption")
    orig = context.user_data.get("reject_orig_caption", "")
    if query and query.message:
        # اگر همان پیام دکمه‌هاست
        if not chat_id:
            chat_id = query.message.chat_id
            msg_id = query.message.message_id
            has_caption = bool(query.message.caption is not None)
            # orig ممکن است متن انتخاب دلیل باشد؛ بهتر از context
            if not orig:
                orig = ""
    try:
        if chat_id and msg_id and orig:
            if has_caption:
                await context.bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id, caption=orig + admin_suffix, reply_markup=None
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=orig + admin_suffix, reply_markup=None
                )
    except Exception:
        pass

    confirm = f"✅ سفارش #{order_id} رد شد و به کاربر اطلاع داده شد."
    if reason:
        confirm += f"\n📝 دلیل:\n{reason}"

    if query:
        try:
            await query.answer()
        except Exception:
            pass
        try:
            # اگر پیام عکس است، caption را عوض کن؛ وگرنه متن
            if query.message and query.message.photo:
                await query.edit_message_caption(caption=confirm, reply_markup=None)
            else:
                await query.edit_message_text(confirm, reply_markup=main_keyboard(True))
        except Exception:
            try:
                await context.bot.send_message(
                    query.from_user.id, confirm, reply_markup=main_keyboard(True)
                )
            except Exception:
                pass
    elif update.message:
        await update.message.reply_text(confirm, reply_markup=main_keyboard(True))

    _clear_reject_data(context)
    return ConversationHandler.END


async def reject_order_with_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت دلیل متنی از ادمین"""
    order_id = context.user_data.get("reject_order_id")
    if not order_id:
        if update.message:
            await update.message.reply_text(
                "خطا: سفارش مشخص نیست. دوباره از دکمه رد شروع کنید.",
                reply_markup=main_keyboard(True),
            )
        return ConversationHandler.END

    reason = None
    if update.message and update.message.text:
        reason = update.message.text.strip() or None

    return await _finish_reject_order(update, context, int(order_id), reason)


def _clear_reject_data(context: ContextTypes.DEFAULT_TYPE):
    for k in (
        "reject_order_id", "reject_user_id", "reject_msg_chat",
        "reject_msg_id", "reject_has_caption", "reject_orig_caption"
    ):
        context.user_data.pop(k, None)


async def reject_order_no_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد بدون توضیح — از callback_data شناسه سفارش را می‌گیرد"""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("دسترسی ندارید", show_alert=True)
        return ConversationHandler.END

    # فرمت: reject_no_note_{order_id}  یا قدیمی: reject_no_note
    parts = query.data.split("_")
    order_id = None
    if parts[-1].isdigit():
        order_id = int(parts[-1])
    else:
        order_id = context.user_data.get("reject_order_id")

    if not order_id:
        await query.answer("سفارش مشخص نیست", show_alert=True)
        return ConversationHandler.END

    context.user_data["reject_order_id"] = order_id
    return await _finish_reject_order(update, context, int(order_id), None)


async def reject_order_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد با دلیل آماده — فرمت: reject_preset_{key}_{order_id}"""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("دسترسی ندارید", show_alert=True)
        return ConversationHandler.END

    # reject_preset_amount_12 → key=amount, order_id=12
    raw = query.data[len("reject_preset_"):]  # amount_12
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        # سازگاری با فرمت قدیمی بدون order_id
        key = raw
        order_id = context.user_data.get("reject_order_id")
    else:
        key, order_id = parts[0], int(parts[1])

    reason = REJECT_PRESET_REASONS.get(key)
    if not reason:
        await query.answer("دلیل نامعتبر", show_alert=True)
        return ADMIN_REJECT_REASON

    if not order_id:
        await query.answer("سفارش مشخص نیست. دوباره رد را بزنید.", show_alert=True)
        return ConversationHandler.END

    context.user_data["reject_order_id"] = order_id
    return await _finish_reject_order(update, context, int(order_id), reason)

# ---------- تمدید سرویس ----------
async def renew_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[1])
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT config_name, volume_gb, server_type, config_data FROM orders WHERE id = ? AND user_id = ? AND status = 'paid'",
            (order_id, user_id)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        await query.answer("سفارش معتبر نیست یا پرداخت نشده", show_alert=True)
        return

    conf_name, vol, server, conf_data = row
    context.user_data["renew_order_id"] = order_id
    context.user_data["renew_username"] = conf_name
    context.user_data["renew_volume"] = vol
    context.user_data["renew_server"] = server

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT price FROM tariffs WHERE server_type = ? AND volume_gb = ? AND is_active = 1 LIMIT 1",
            (server, vol)
        ) as cur:
            price_row = await cur.fetchone()
    price = price_row[0] if price_row else 0
    context.user_data["renew_price"] = price
    context.user_data["final_price"] = price

    # موجودی کاربر
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            bal_row = await cur.fetchone()
    balance = bal_row[0] if bal_row else 0

    buttons = []
    if balance >= price:
        buttons.append([InlineKeyboardButton("💰 پرداخت با کیف پول", callback_data="renew_pay_wallet")])
    buttons.append([InlineKeyboardButton("📤 ارسال رسید", callback_data="renew_send_receipt")])
    buttons.append([back_button(f"order_detail_{order_id}")])

    await query.edit_message_text(
        f"🔄 <b>تمدید سرویس #{order_id}</b>\n\n"
        f"👤 نام کاربری: <code>{conf_name}</code>\n"
        f"📊 حجم تمدید: {vol} گیگ\n"
        f"💰 قیمت: <b>{price:,}</b> تومان\n"
        f"💳 موجودی شما: <b>{balance:,}</b> تومان\n\n"
        f"با تمدید، هم حجم و هم زمان اعتبار به سرویس فعلی شما <b>اضافه</b> می‌شود.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

async def renew_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    final = context.user_data.get("renew_price", 0)
    username = context.user_data.get("renew_username")
    vol = context.user_data.get("renew_volume")
    order_id = context.user_data.get("renew_order_id")
    server = context.user_data.get("renew_server")

    if not all([username, vol, order_id]):
        await query.edit_message_text("❌ اطلاعات ناقص است.")
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,)) as cur:
            bal = (await cur.fetchone())[0] or 0
        if bal < final:
            await query.answer("❌ موجودی کافی نیست", show_alert=True)
            return
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (final, user.id))
        await db.commit()

    try:
        user_data = await get_user_from_panel(username, server_type=server)
        if not user_data:
            raise Exception("کاربر در پنل یافت نشد. با پشتیبانی تماس بگیرید.")

        current_expire = user_data.get("expire") or 0
        current_limit = user_data.get("data_limit") or 0

        service_days = await get_int_setting("service_days", 30)
        add_bytes = vol * 1024 * 1024 * 1024
        new_limit = (current_limit or 0) + add_bytes

        now_ts = int(datetime.now().timestamp())
        base_expire = max(current_expire or 0, now_ts)
        new_expire = base_expire + (service_days * 86400)

        await modify_user_in_panel(username, {
            "data_limit": new_limit,
            "expire": new_expire,
            "status": "active"
        }, server_type=server)

        # ثبت سفارش تمدید
        async with aiosqlite.connect("bot.db") as db:
            await db.execute(
                """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price, config_name, status, created_at, panel_username, config_data)
                   VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)""",
                (user.id, server, vol, final, final, username, datetime.now().isoformat(), username,
                 json.dumps({"renewed_from": order_id, "type": "renew"}))
            )
            # ریست فلگ‌های هشدار سفارش اصلی
            await db.execute(
                "UPDATE orders SET warned_85 = 0, expire_warned = 0, balance_warned = 0 WHERE id = ?",
                (order_id,),
            )
            await db.commit()

        await query.edit_message_text(
            f"✅ سرویس با موفقیت تمدید شد!\n\n"
            f"📊 {vol} گیگ حجم اضافه شد\n"
            f"⏳ {service_days} روز اعتبار اضافه شد\n"
            f"💰 مبلغ کسر شده: {final:,} تومان"
        )
        await notify_admin_sale(
            context.bot,
            kind="renew",
            order_id=order_id,
            user_id=user.id,
            amount=final,
            plan=f"{server or '—'} — {vol}G (تمدید)",
            payment="کیف پول",
        )
    except Exception as e:
        logger.error(e)
        async with aiosqlite.connect("bot.db") as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final, user.id))
            await db.commit()
        await query.edit_message_text(f"❌ خطا در تمدید:\n{str(e)[:200]}")

    context.user_data.clear()
async def show_tariffs_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 تعرفه سرویس‌های لوکیشن هلند", callback_data="tariff_list_holland")],
        [InlineKeyboardButton("🌐 تعرفه سرویس‌های مولتی لوکیشن", callback_data="tariff_list_multi")],
        [InlineKeyboardButton("💎 تعرفه سرویس‌های نامحدود", callback_data="tariff_list_unlimited")],
        [back_button()],
    ])

    await query.edit_message_text(
        "📊 <b>تعرفه اشتراک‌ها</b>\n\n"
        "نوع سرویس مورد نظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


async def renew_send_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 لطفاً عکس یا فایل رسید پرداخت تمدید را ارسال کنید.")
    return RENEW_WAITING_RECEIPT

async def receive_renew_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document

    if not photo and not document:
        await update.message.reply_text("لطفاً فقط عکس یا فایل ارسال کنید.")
        return RENEW_WAITING_RECEIPT

    receipt_uid = get_receipt_unique_id(update.message)
    if receipt_uid and await is_receipt_used(receipt_uid):
        await update.message.reply_text(
            "❌ این رسید قبلاً استفاده شده است.\n"
            "لطفاً رسید پرداخت جدید ارسال کنید."
        )
        return RENEW_WAITING_RECEIPT

    if not await check_receipt_rate_limit(user.id):
        await update.message.reply_text(
            f"❌ تعداد ارسال رسید بیش از حد مجاز است.\n"
            f"حداکثر {RECEIPT_RATE_LIMIT_COUNT} رسید در {RECEIPT_RATE_LIMIT_MINUTES} دقیقه.\n"
            f"لطفاً کمی بعد دوباره تلاش کنید."
        )
        return RENEW_WAITING_RECEIPT

    username = context.user_data.get("renew_username")
    vol = context.user_data.get("renew_volume")
    price = context.user_data.get("renew_price", 0)
    order_id = context.user_data.get("renew_order_id")
    server = context.user_data.get("renew_server")

    # ثبت به عنوان سفارش pending از نوع تمدید
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price, config_name, status, created_at, panel_username, config_data)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (user.id, server, vol, price, price, username, datetime.now().isoformat(), username,
             json.dumps({"renewed_from": order_id, "type": "renew"}))
        )
        new_order_id = cur.lastrowid
        await db.commit()

    if receipt_uid:
        await store_receipt_id(receipt_uid, user.id, "renew")

    admin_text = (
        f"🔄 درخواست تمدید #{new_order_id}\n"
        f"—————————————\n"
        f"👤 کاربر: {user.full_name} (@{user.username or '—'})\n"
        f"🆔 <code>{user.id}</code>\n"
        f"👤 کانفیگ: <code>{username}</code>\n"
        f"📦 حجم: {vol} گیگ\n"
        f"💰 مبلغ: {price:,} تومان\n"
        f"🔗 مرتبط با سفارش: #{order_id}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید تمدید", callback_data=f"approve_renew_{new_order_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_order_{new_order_id}")]
    ])

    if photo:
        await context.bot.send_photo(ADMIN_ID, photo.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_document(ADMIN_ID, document.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)

    await update.message.reply_text(
        f"✅ رسید تمدید ثبت شد.\nشماره پیگیری: #{new_order_id}\nمنتظر تأیید ادمین بمانید.",
        reply_markup=main_keyboard(await is_admin(user.id))
    )
    context.user_data.clear()
    return ConversationHandler.END

async def approve_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, volume_gb, config_name, config_data, server_type, final_price FROM orders WHERE id = ? AND status = 'pending'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("قبلاً بررسی شده", show_alert=True)
            return
        user_id, vol, username, conf_data_str, server_type, final_price = row

        try:
            conf_data = json.loads(conf_data_str) if conf_data_str else {}
            original_order = conf_data.get("renewed_from")
        except:
            original_order = None

        user_data = await get_user_from_panel(username, server_type=server_type)
        if not user_data:
            await query.answer("کاربر در پنل یافت نشد", show_alert=True)
            return

        current_expire = user_data.get("expire") or 0
        current_limit = user_data.get("data_limit") or 0
        service_days = await get_int_setting("service_days", 30)
        add_bytes = vol * 1024 * 1024 * 1024
        new_limit = (current_limit or 0) + add_bytes
        now_ts = int(datetime.now().timestamp())
        base_expire = max(current_expire or 0, now_ts)
        new_expire = base_expire + (service_days * 86400)

        await modify_user_in_panel(username, {
            "data_limit": new_limit,
            "expire": new_expire,
            "status": "active"
        }, server_type=server_type)

        await db.execute(
            "UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,)
        )
        if original_order:
            await db.execute(
                "UPDATE orders SET warned_85 = 0, expire_warned = 0, balance_warned = 0 WHERE id = ?",
                (original_order,),
            )
        await db.commit()

    try:
        await context.bot.send_message(
            user_id,
            f"✅ تمدید سرویس شما تأیید شد!\n\n"
            f"👤 نام کاربری: <code>{username}</code>\n"
            f"📊 {vol} گیگ حجم اضافه شد\n"
            f"⏳ اعتبار سرویس افزایش یافت.",
            parse_mode=ParseMode.HTML
        )
    except:
        pass

    await notify_admin_sale(
        context.bot,
        kind="renew",
        order_id=order_id,
        user_id=user_id,
        amount=final_price or 0,
        plan=f"{server_type or '—'} — {vol}G (تمدید)",
        payment="رسید / تأیید ادمین",
    )

    try:
        await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n✅ تمدید تأیید شد")
    except Exception:
        try:
            await query.edit_message_text((query.message.text or "") + "\n\n✅ تمدید تأیید شد")
        except Exception:
            pass

# ==================== پروکسی ====================
PROXY_LOCATIONS = {
    "holland": {"name": "🇳🇱 هلند", "key": "proxy_price_holland", "default": PROXY_PRICE_HOLLAND},
    "america": {"name": "🇺🇸 آمریکا", "key": "proxy_price_america", "default": PROXY_PRICE_AMERICA},
    "singapore": {"name": "🇸🇬 سنگاپور", "key": "proxy_price_singapore", "default": PROXY_PRICE_SINGAPORE},
}

async def get_proxy_unit_price(location: str) -> int:
    info = PROXY_LOCATIONS.get(location)
    if not info:
        return 0
    return await get_int_setting(info["key"], info["default"])

async def get_proxy_day_price() -> int:
    return await get_int_setting("proxy_price_per_day", PROXY_PRICE_PER_DAY)

async def get_proxy_stock_count(location: str) -> int:
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM proxy_stock WHERE location = ? AND is_sold = 0",
            (location,)
        ) as cur:
            return (await cur.fetchone())[0]

async def proxy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 پروکسی لوکیشن هلند", callback_data="proxy_loc_holland")],
        [InlineKeyboardButton("🇺🇸 پروکسی لوکیشن آمریکا", callback_data="proxy_loc_america")],
        [InlineKeyboardButton("🇸🇬 پروکسی لوکیشن سنگاپور", callback_data="proxy_loc_singapore")],
        [back_button()]
    ])
    await query.edit_message_text(
        "🌐 <b>خرید پروکسی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "لوکیشن مورد نظر را انتخاب کنید:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

async def proxy_select_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    location = query.data.replace("proxy_loc_", "")
    if location not in PROXY_LOCATIONS:
        await query.answer("لوکیشن نامعتبر", show_alert=True)
        return

    unit_price = await get_proxy_unit_price(location)
    context.user_data["proxy_location"] = location
    context.user_data["proxy_qty"] = 1
    context.user_data["proxy_days"] = 30
    context.user_data["proxy_unit_price"] = unit_price
    return await show_proxy_config(update, context)

async def show_proxy_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    location = context.user_data.get("proxy_location", "holland")
    qty = context.user_data.get("proxy_qty", 1)
    days = context.user_data.get("proxy_days", 30)
    unit_price = context.user_data.get("proxy_unit_price") or await get_proxy_unit_price(location)
    day_price = await get_proxy_day_price()

    qty = max(PROXY_MIN_QTY, min(PROXY_MAX_QTY, qty))
    days = max(PROXY_MIN_DAYS, min(PROXY_MAX_DAYS, days))
    context.user_data["proxy_qty"] = qty
    context.user_data["proxy_days"] = days

    base_cost = unit_price * qty
    days_cost = day_price * days
    final = base_cost + days_cost
    context.user_data["proxy_final_price"] = final

    loc_name = PROXY_LOCATIONS[location]["name"]
    stock = await get_proxy_stock_count(location)

    text = (
        f"🌐 <b>پیکربندی پروکسی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 لوکیشن: <b>{loc_name}</b>\n"
        f"📦 موجودی انبار: <b>{stock}</b> عدد\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔢 تعداد: <b>{qty}</b> عدد\n"
        f"💰 قیمت هر پروکسی: <b>{unit_price:,}</b> تومان\n"
        f"📅 مدت: <b>{days}</b> روز\n"
        f"💵 هزینه مدت ({days} × {day_price:,}): <b>{days_cost:,}</b> تومان\n"
        f"💰 <b>قیمت نهایی: {final:,} تومان</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"با دکمه‌های زیر تعداد و مدت را تنظیم کنید:"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 اضافه کردن پروکسی", callback_data="noop")],
        [
            InlineKeyboardButton("➖ ۱ عدد", callback_data="proxy_qty_-1"),
            InlineKeyboardButton(f"🔢 {qty}", callback_data="noop"),
            InlineKeyboardButton("➕ ۱ عدد", callback_data="proxy_qty_+1"),
        ],
        [InlineKeyboardButton("📅 زمان پروکسی", callback_data="noop")],
        [
            InlineKeyboardButton("➖ ۱ روز", callback_data="proxy_days_-1"),
            InlineKeyboardButton("➕ ۱ روز", callback_data="proxy_days_+1"),
        ],
        [
            InlineKeyboardButton("➖ ۱۰ روز", callback_data="proxy_days_-10"),
            InlineKeyboardButton("➕ ۱۰ روز", callback_data="proxy_days_+10"),
        ],
        [
            InlineKeyboardButton("➖ ۱۵ روز", callback_data="proxy_days_-15"),
            InlineKeyboardButton("➕ ۱۵ روز", callback_data="proxy_days_+15"),
        ],
        [InlineKeyboardButton("✅ خرید / مشاهده فاکتور", callback_data="proxy_show_invoice")],
        [back_button("proxy_menu")],
    ])

    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def proxy_adjust_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "proxy_location" not in context.user_data:
        await query.edit_message_text("❌ دوباره از منوی پروکسی شروع کنید.", reply_markup=InlineKeyboardMarkup([[back_button()]]))
        return
    try:
        delta = int(query.data.replace("proxy_qty_", ""))
    except:
        return
    context.user_data["proxy_qty"] = context.user_data.get("proxy_qty", 1) + delta
    return await show_proxy_config(update, context)

async def proxy_adjust_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "proxy_location" not in context.user_data:
        await query.edit_message_text("❌ دوباره از منوی پروکسی شروع کنید.", reply_markup=InlineKeyboardMarkup([[back_button()]]))
        return
    try:
        delta = int(query.data.replace("proxy_days_", ""))
    except:
        return
    context.user_data["proxy_days"] = context.user_data.get("proxy_days", 30) + delta
    return await show_proxy_config(update, context)

async def proxy_show_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    location = context.user_data.get("proxy_location")
    qty = context.user_data.get("proxy_qty", 1)
    days = context.user_data.get("proxy_days", 30)
    final = context.user_data.get("proxy_final_price", 0)
    unit_price = context.user_data.get("proxy_unit_price", 0)

    if not location:
        await query.edit_message_text("❌ اطلاعات ناقص است.", reply_markup=InlineKeyboardMarkup([[back_button("proxy_menu")]]))
        return

    stock = await get_proxy_stock_count(location)
    if stock < qty:
        if stock == 0:
            await query.answer("❌ پروکسی در انبار وجود ندارد.", show_alert=True)
        else:
            await query.answer(f"❌ موجودی کافی نیست!\nفقط {stock} عدد در انبار موجود است.", show_alert=True)
        return

    loc_name = PROXY_LOCATIONS[location]["name"]
    day_price = await get_proxy_day_price()
    user = query.from_user

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
    balance = row[0] if row else 0

    text = (
        f"🧾 <b>فاکتور پروکسی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 لوکیشن: <b>{loc_name}</b>\n"
        f"🔢 تعداد: <b>{qty}</b> عدد\n"
        f"📅 مدت: <b>{days}</b> روز\n"
        f"💰 قیمت هر پروکسی: {unit_price:,} تومان\n"
        f"💵 هزینه مدت: {days * day_price:,} تومان\n"
        f"💰 <b>مبلغ نهایی: {final:,} تومان</b>\n"
        f"💳 موجودی کیف پول: <b>{balance:,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
        f"👤 به نام: {CARD_NAME}\n\n"
        f"ℹ️ پس از واریز، روی «📤 ارسال رسید» بزنید."
    )

    buttons = [
        [InlineKeyboardButton("📤 ارسال رسید", callback_data="proxy_send_receipt")],
    ]
    if balance >= final:
        buttons.append([InlineKeyboardButton("💰 پرداخت با کیف پول", callback_data="proxy_pay_wallet")])
    buttons.append([back_button("proxy_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def proxy_send_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 لطفاً عکس یا فایل رسید پرداخت پروکسی را ارسال کنید.")
    return PROXY_WAITING_RECEIPT

async def receive_proxy_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document

    if not photo and not document:
        await update.message.reply_text("لطفاً فقط عکس یا فایل ارسال کنید.")
        return PROXY_WAITING_RECEIPT

    receipt_uid = get_receipt_unique_id(update.message)
    if receipt_uid and await is_receipt_used(receipt_uid):
        await update.message.reply_text(
            "❌ این رسید قبلاً استفاده شده است.\n"
            "لطفاً رسید پرداخت جدید ارسال کنید."
        )
        return PROXY_WAITING_RECEIPT

    if not await check_receipt_rate_limit(user.id):
        await update.message.reply_text(
            f"❌ تعداد ارسال رسید بیش از حد مجاز است.\n"
            f"حداکثر {RECEIPT_RATE_LIMIT_COUNT} رسید در {RECEIPT_RATE_LIMIT_MINUTES} دقیقه.\n"
            f"لطفاً کمی بعد دوباره تلاش کنید."
        )
        return PROXY_WAITING_RECEIPT

    location = context.user_data.get("proxy_location")
    qty = context.user_data.get("proxy_qty", 1)
    days = context.user_data.get("proxy_days", 30)
    final = context.user_data.get("proxy_final_price", 0)
    unit_price = context.user_data.get("proxy_unit_price", 0)
    day_price = await get_proxy_day_price()

    if not location:
        await update.message.reply_text("❌ اطلاعات سفارش ناقص است.", reply_markup=main_keyboard(False))
        return ConversationHandler.END

    stock = await get_proxy_stock_count(location)
    if stock < qty:
        await update.message.reply_text(
            f"❌ موجودی کافی نیست (فقط {stock} عدد). سفارش ثبت نشد.",
            reply_markup=main_keyboard(await is_admin(user.id))
        )
        context.user_data.clear()
        return ConversationHandler.END

    tracking = generate_tracking_code()
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            """INSERT INTO proxy_orders
               (user_id, location, quantity, days, unit_price, days_price, final_price, status, tracking_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (user.id, location, qty, days, unit_price, day_price * days, final, tracking, datetime.now().isoformat())
        )
        order_id = cur.lastrowid
        await db.commit()

    if receipt_uid:
        await store_receipt_id(receipt_uid, user.id, "proxy")

    loc_name = PROXY_LOCATIONS[location]["name"]
    admin_text = (
        f"🆕 سفارش پروکسی #{order_id}\n"
        f"—————————————\n"
        f"👤 کاربر: {user.full_name} (@{user.username or '—'})\n"
        f"🆔 آیدی: <code>{user.id}</code>\n"
        f"📍 لوکیشن: {loc_name}\n"
        f"🔢 تعداد: {qty}\n"
        f"📅 مدت: {days} روز\n"
        f"💰 مبلغ: {final:,} تومان\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و تحویل", callback_data=f"approve_proxy_{order_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_proxy_{order_id}")]
    ])

    if photo:
        await context.bot.send_photo(ADMIN_ID, photo.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_document(ADMIN_ID, document.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)

    await update.message.reply_text(
        f"✅ رسید پروکسی ثبت شد.\n"
        f"شماره سفارش: <b>#{order_id}</b>\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n\n"
        f"لطفاً منتظر بررسی ادمین بمانید.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(await is_admin(user.id))
    )
    context.user_data.clear()
    return ConversationHandler.END

async def proxy_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    location = context.user_data.get("proxy_location")
    qty = context.user_data.get("proxy_qty", 1)
    days = context.user_data.get("proxy_days", 30)
    final = context.user_data.get("proxy_final_price", 0)
    unit_price = context.user_data.get("proxy_unit_price", 0)
    day_price = await get_proxy_day_price()

    if not location:
        await query.edit_message_text("❌ اطلاعات ناقص است.")
        return

    stock = await get_proxy_stock_count(location)
    if stock < qty:
        await query.answer(f"❌ موجودی کافی نیست (فقط {stock} عدد).", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,)) as cur:
            bal = (await cur.fetchone())[0] or 0
        if bal < final:
            await query.answer("❌ موجودی کیف پول کافی نیست!", show_alert=True)
            return

        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (final, user.id))

        async with db.execute(
            "SELECT id, proxy_text FROM proxy_stock WHERE location = ? AND is_sold = 0 LIMIT ?",
            (location, qty)
        ) as cur:
            rows = await cur.fetchall()

        if len(rows) < qty:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (final, user.id))
            await db.commit()
            await query.answer("❌ موجودی در لحظه کافی نبود.", show_alert=True)
            return

        tracking = generate_tracking_code()
        proxies_list = [r[1] for r in rows]
        ids = [r[0] for r in rows]

        cur = await db.execute(
            """INSERT INTO proxy_orders
               (user_id, location, quantity, days, unit_price, days_price, final_price, status, proxies_data, tracking_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)""",
            (user.id, location, qty, days, unit_price, day_price * days, final,
             json.dumps(proxies_list, ensure_ascii=False), tracking, datetime.now().isoformat())
        )
        order_id = cur.lastrowid

        for sid in ids:
            await db.execute(
                "UPDATE proxy_stock SET is_sold = 1, order_id = ? WHERE id = ?",
                (order_id, sid)
            )
        await db.commit()

    loc_name = PROXY_LOCATIONS[location]["name"]
    proxies_text = "\n".join(f"<code>{p}</code>" for p in proxies_list)

    caption = (
        f"✅ سفارش پروکسی #{order_id} با موفقیت پرداخت و تحویل شد!\n\n"
        f"📍 لوکیشن: {loc_name}\n"
        f"🔢 تعداد: {qty}\n"
        f"📅 مدت: {days} روز\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"💰 مبلغ کسر شده: {final:,} تومان\n\n"
        f"📋 پروکسی‌های شما:\n{proxies_text}"
    )
    await query.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[back_button()]]))
    await query.edit_message_text(
        f"✅ پرداخت با کیف پول موفق بود.\nسفارش پروکسی #{order_id} تحویل داده شد.\n🔖 کد رهگیری: <code>{tracking}</code>",
        parse_mode=ParseMode.HTML
    )
    await notify_admin_sale(
        context.bot,
        kind="proxy",
        order_id=order_id,
        user_id=user.id,
        amount=final,
        plan=f"{loc_name} — {qty} عدد / {days} روز",
        payment="کیف پول",
    )
    context.user_data.clear()

async def approve_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, location, quantity, days, final_price FROM proxy_orders WHERE id = ? AND status = 'pending'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("این سفارش قبلاً بررسی شده", show_alert=True)
            return
        user_id, location, qty, days, price = row

        async with db.execute(
            "SELECT id, proxy_text FROM proxy_stock WHERE location = ? AND is_sold = 0 LIMIT ?",
            (location, qty)
        ) as cur:
            rows = await cur.fetchall()

        if len(rows) < qty:
            await query.answer(f"❌ موجودی کافی نیست! فقط {len(rows)} عدد باقی مانده.", show_alert=True)
            return

        proxies_list = [r[1] for r in rows]
        ids = [r[0] for r in rows]
        tracking = generate_tracking_code()

        await db.execute(
            "UPDATE proxy_orders SET status = 'paid', proxies_data = ?, tracking_code = ? WHERE id = ?",
            (json.dumps(proxies_list, ensure_ascii=False), tracking, order_id)
        )
        for sid in ids:
            await db.execute(
                "UPDATE proxy_stock SET is_sold = 1, order_id = ? WHERE id = ?",
                (order_id, sid)
            )
        await db.commit()

    loc_name = PROXY_LOCATIONS.get(location, {}).get("name", location)
    proxies_text = "\n".join(f"<code>{p}</code>" for p in proxies_list)

    try:
        await context.bot.send_message(
            user_id,
            f"✅ سفارش پروکسی #{order_id} تأیید و تحویل شد!\n\n"
            f"📍 لوکیشن: {loc_name}\n"
            f"🔢 تعداد: {qty}\n"
            f"📅 مدت: {days} روز\n"
            f"🔖 کد رهگیری: <code>{tracking}</code>\n\n"
            f"📋 پروکسی‌های شما:\n{proxies_text}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"approve_proxy notify: {e}")

    await log_admin_action(query.from_user.id, "approve_proxy", order_id)
    await notify_admin_sale(
        context.bot,
        kind="proxy",
        order_id=order_id,
        user_id=user_id,
        amount=price or 0,
        plan=f"{loc_name} — {qty} عدد / {days} روز",
        payment="رسید / تأیید ادمین",
    )
    try:
        await notify_proxy_low_stock(context.bot, location)
    except Exception:
        pass

    try:
        if query.message and query.message.caption is not None:
            await query.edit_message_caption(
                caption=(query.message.caption or "") + "\n\n✅ تأیید و تحویل شد"
            )
        else:
            await query.edit_message_text(
                (query.message.text or "") + "\n\n✅ تأیید و تحویل شد"
            )
    except Exception:
        pass

async def reject_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    order_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id FROM proxy_orders WHERE id = ? AND status = 'pending'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("قبلاً بررسی شده", show_alert=True)
            return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 مبلغ ناقص / مغایرت", callback_data=f"rejpx_preset_amount_{order_id}")],
        [InlineKeyboardButton("🖼 رسید نامشخص / ناخوانا", callback_data=f"rejpx_preset_unclear_{order_id}")],
        [InlineKeyboardButton("🔁 واریز تکراری", callback_data=f"rejpx_preset_duplicate_{order_id}")],
        [InlineKeyboardButton("⏰ رسید قدیمی / منقضی", callback_data=f"rejpx_preset_old_{order_id}")],
        [InlineKeyboardButton("❌ کارت اشتباه / گیرنده نادرست", callback_data=f"rejpx_preset_card_{order_id}")],
        [InlineKeyboardButton("⏭ ادامه بدون توضیحات", callback_data=f"rejpx_no_note_{order_id}")],
    ])
    msg = (
        f"❌ <b>رد سفارش پروکسی #{order_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"دلیل آماده را انتخاب کنید:"
    )
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(caption=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(query.from_user.id, msg, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _finish_reject_proxy(update, context, order_id: int, reason: Optional[str]):
    query = update.callback_query
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, status FROM proxy_orders WHERE id = ?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[1] != "pending":
            if query:
                await query.answer("قبلاً بررسی شده", show_alert=True)
            return
        user_id = row[0]
        await db.execute("UPDATE proxy_orders SET status = 'rejected' WHERE id = ?", (order_id,))
        await db.commit()

    if reason:
        user_msg = (
            f"❌ <b>سفارش پروکسی رد شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"شماره: <b>#{order_id}</b>\n\n"
            f"📝 توضیحات ادمین:\n{reason}\n\n"
            f"در صورت مشکل: {SUPPORT_USERNAME}"
        )
    else:
        user_msg = (
            f"❌ سفارش پروکسی #{order_id} توسط ادمین رد شد.\n"
            f"در صورت مشکل: {SUPPORT_USERNAME}"
        )
    try:
        await context.bot.send_message(user_id, user_msg, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    admin_id = query.from_user.id if query else 0
    await log_admin_action(admin_id, "reject_proxy", order_id, reason or "بدون توضیح")

    confirm = f"✅ پروکسی #{order_id} رد شد."
    if reason:
        confirm += f"\n📝 {reason}"
    try:
        if query.message and query.message.photo:
            await query.edit_message_caption(caption=confirm, reply_markup=None)
        else:
            await query.edit_message_text(confirm, reply_markup=main_keyboard(True))
    except Exception:
        try:
            await context.bot.send_message(query.from_user.id, confirm, reply_markup=main_keyboard(True))
        except Exception:
            pass


async def reject_proxy_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        return
    raw = query.data[len("rejpx_preset_"):]
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        await query.answer("نامعتبر", show_alert=True)
        return
    key, order_id = parts[0], int(parts[1])
    reason = REJECT_PRESET_REASONS.get(key)
    if not reason:
        await query.answer("دلیل نامعتبر", show_alert=True)
        return
    await query.answer()
    await _finish_reject_proxy(update, context, order_id, reason)


async def reject_proxy_no_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        return
    order_id = int(query.data.split("_")[-1])
    await query.answer()
    await _finish_reject_proxy(update, context, order_id, None)


# ---------- سرویس‌های من ----------
# ---------- سرویس‌های من ----------
async def my_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT id, server_type, volume_gb, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()

    loyalty = await loyalty_progress_text(user_id)

    if not rows:
        await query.edit_message_text(
            f"📦 شما هنوز هیچ سرویسی ندارید.\n\n{loyalty}",
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
            parse_mode=ParseMode.HTML,
        )
        return

    buttons = []
    for oid, server, vol, status, created in rows:
        emoji = {"paid": "✅", "rejected": "🚫", "pending": "⏳"}.get(status, "❓")
        if server == "holland":
            server_name = "هلند"
            plan = f"{vol}G"
        elif server == "unlimited":
            server_name = "نامحدود"
            plan = f"{vol}م"
        elif server == "custom":
            server_name = "دلخواه"
            plan = f"{vol}G"
        else:
            server_name = "مولتی"
            plan = f"{vol}G"
        buttons.append([InlineKeyboardButton(
            f"{emoji} #{oid} | {server_name} {plan} | {status}",
            callback_data=f"order_detail_{oid}"
        )])
    buttons.append([back_button()])
    await query.edit_message_text(
        f"📦 سرویس‌های شما:\n\n{loyalty}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def order_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تاریخچه فقط سفارش‌های پرداخت‌شده با کد رهگیری"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, server_type, volume_gb, final_price, tracking_code, created_at, config_name
               FROM orders
               WHERE user_id = ? AND status = 'paid'
               ORDER BY id DESC LIMIT 30""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "📋 تاریخچه سفارشات خالی است.\nهنوز سفارش پرداخت‌شده‌ای ندارید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service")],
                [back_button()],
            ]),
        )
        return

    lines = ["📋 <b>تاریخچه سفارشات پرداخت‌شده</b>", "━━━━━━━━━━━━━━━━━━"]
    buttons = []
    for oid, server, vol, price, tracking, created, conf_name in rows:
        server_name = {
            "holland": "هلند",
            "multi": "مولتی",
            "unlimited": "نامحدود",
            "custom": "دلخواه",
        }.get(server, server or "—")
        if server == "unlimited":
            plan = f"{vol} ماهه"
        else:
            plan = f"{vol}G"
        date_str = created[:16].replace("T", " ") if created else "—"
        track = tracking or "—"
        lines.append(
            f"#{oid} | {server_name} {plan}\n"
            f"💰 {price:,} ت | 🕐 {date_str}\n"
            f"🔖 <code>{track}</code>"
        )
        lines.append("—————————————")
        buttons.append([
            InlineKeyboardButton(
                f"#{oid} | {server_name} {plan}",
                callback_data=f"order_detail_{oid}",
            )
        ])

    buttons.append([back_button()])
    text_msg = "\n".join(lines)
    if len(text_msg) > 3900:
        text_msg = text_msg[:3890] + "…"
    try:
        await query.edit_message_text(
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await context.bot.send_message(
            user_id,
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )


async def quick_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست سرویس‌های در حال انقضا (کمتر از ۷ روز) با دکمه تمدید مستقیم"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    await query.edit_message_text("🔄 در حال بررسی سرویس‌های نزدیک به انقضا...")

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, server_type, volume_gb, config_name, panel_username, config_data
               FROM orders WHERE user_id = ? AND status = 'paid'
               ORDER BY id DESC LIMIT 20""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "🔄 سرویس فعالی برای تمدید یافت نشد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service")],
                [back_button()],
            ]),
        )
        return

    expiring = []
    now_ts = int(datetime.now().timestamp())
    seven_days = 7 * 86400

    for oid, server, vol, conf_name, panel_user, conf_data in rows:
        panel_name = panel_user or conf_name
        if not panel_name and conf_data:
            try:
                panel_name = json.loads(conf_data).get("username")
            except Exception:
                pass
        if not panel_name:
            continue
        try:
            user_info = await get_user_from_panel(panel_name, server_type=server)
            if not user_info:
                continue
            expire_ts = user_info.get("expire") or 0
            status = user_info.get("status", "")
            if status in ("expired", "disabled"):
                # منقضی‌شده هم قابل تمدید نشان داده شود
                days_left = 0
                hours_left = 0
                expiring.append((oid, server, vol, panel_name, days_left, hours_left, True))
                continue
            if not expire_ts or expire_ts <= 0:
                continue
            remaining = expire_ts - now_ts
            if remaining <= seven_days:
                days_left = max(0, remaining // 86400)
                hours_left = max(0, (remaining % 86400) // 3600)
                expiring.append((oid, server, vol, panel_name, days_left, hours_left, remaining <= 0))
        except Exception as e:
            logger.error(f"quick_renew check {oid}: {e}")

    if not expiring:
        await query.edit_message_text(
            "✅ هیچ سرویسی در ۷ روز آینده منقضی نمی‌شود.\n"
            "سرویس‌های شما هنوز اعتبار کافی دارند.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 وضعیت سرویس‌ها", callback_data="service_status")],
                [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")],
                [back_button()],
            ]),
        )
        return

    lines = [
        "🔄 <b>تمدید سریع</b>",
        "سرویس‌های نزدیک به انقضا (کمتر از ۷ روز):",
        "━━━━━━━━━━━━━━━━━━",
    ]
    buttons = []
    for oid, server, vol, panel_name, days_left, hours_left, is_expired in expiring:
        server_name = {
            "holland": "هلند",
            "multi": "مولتی",
            "unlimited": "نامحدود",
            "custom": "دلخواه",
        }.get(server, server or "—")
        if is_expired:
            time_txt = "⏰ <b>منقضی شده</b>"
        elif days_left == 0:
            time_txt = f"⏳ کمتر از {hours_left} ساعت"
        else:
            time_txt = f"⏳ {days_left} روز و {hours_left} ساعت"
        lines.append(
            f"#{oid} | {server_name} ({vol})\n"
            f"👤 <code>{panel_name}</code>\n"
            f"{time_txt}"
        )
        lines.append("—————————————")
        buttons.append([
            InlineKeyboardButton(
                f"🔄 تمدید #{oid}",
                callback_data=f"renew_{oid}",
            )
        ])

    buttons.append([InlineKeyboardButton("📊 وضعیت همه سرویس‌ها", callback_data="service_status")])
    buttons.append([back_button()])
    text_msg = "\n".join(lines)
    if len(text_msg) > 3900:
        text_msg = text_msg[:3890] + "…"
    try:
        await query.edit_message_text(
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await context.bot.send_message(
            user_id,
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )


async def order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT server_type, volume_gb, final_price, status, config_name, config_data,
                      created_at, panel_username, tracking_code, auto_renew
               FROM orders WHERE id = ? AND user_id = ?""",
            (order_id, query.from_user.id)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await query.answer("سفارش یافت نشد", show_alert=True)
        return

    server, vol, price, status, name, conf_data, created, panel_username, tracking_code, auto_renew = row
    auto_renew = auto_renew or 0
    if server == "holland":
        server_name = "🇳🇱 هلند"
        plan_text = f"{vol} گیگ"
    elif server == "unlimited":
        server_name = "💎 سرویس نامحدود"
        plan_text = f"{vol} ماهه"
    elif server == "custom":
        server_name = "⚙️ پلن دلخواه"
        plan_text = f"{vol} گیگ"
    else:
        server_name = "🌐 مولتی"
        plan_text = f"{vol} گیگ"
    status_text = {"paid": "✅ پرداخت شده", "rejected": "🚫 رد شده", "pending": "⏳ در انتظار رسید", "expired": "⏰ منقضی"}.get(status, status)

    text = (
        f"📦 جزئیات سفارش #{order_id}\n"
        f"—————————————\n"
        f"🖥 سرور: {server_name}\n"
        f"📊 پلن: {plan_text}\n"
        f"💰 مبلغ: {price:,} تومان\n"
        f"👤 نام: {name or '—'}\n"
        f"📌 وضعیت: {status_text}\n"
        f"🕐 تاریخ: {created[:16].replace('T', ' ') if created else '—'}"
    )
    if tracking_code:
        text += f"\n🔖 کد رهگیری: <code>{tracking_code}</code>"
    if status == "paid":
        ar_text = "🟢 فعال" if auto_renew else "🔴 غیرفعال"
        text += f"\n🔄 تمدید خودکار: <b>{ar_text}</b>"

    # نمایش مصرف واقعی از پنل
    if status == "paid":
        panel_user = panel_username or name
        if not panel_user and conf_data:
            try:
                panel_user = json.loads(conf_data).get("username")
            except Exception:
                pass
        if panel_user:
            try:
                user_info = await get_user_from_panel(panel_user, server_type=server)
                if user_info:
                    used = user_info.get("used_traffic") or 0
                    limit = user_info.get("data_limit") or 0
                    expire_ts = user_info.get("expire") or 0
                    panel_status = user_info.get("status", "")

                    used_gb = used / (1024 ** 3)
                    limit_gb = limit / (1024 ** 3) if limit > 0 else 0
                    remaining_gb = max(0, limit_gb - used_gb)
                    percent = (used / limit * 100) if limit > 0 else 0

                    text += (
                        f"\n\n📊 <b>وضعیت مصرف</b>\n"
                        f"—————————————\n"
                        f"📉 استفاده‌شده: <b>{used_gb:.2f}</b> گیگ\n"
                        f"📈 باقی‌مانده: <b>{remaining_gb:.2f}</b> گیگ\n"
                        f"📊 درصد مصرف: <b>{percent:.1f}٪</b>\n"
                    )
                    if expire_ts:
                        expire_dt = datetime.fromtimestamp(expire_ts)
                        now = datetime.now()
                        if expire_dt > now:
                            days_left = (expire_dt - now).days
                            hours_left = int((expire_dt - now).total_seconds() / 3600) % 24
                            text += f"⏳ زمان باقی‌مانده: <b>{days_left} روز و {hours_left} ساعت</b>\n"
                        else:
                            text += f"⏰ وضعیت: <b>منقضی شده</b>\n"
                    if panel_status:
                        status_map = {"active": "🟢 فعال", "disabled": "🔴 غیرفعال", "expired": "⏰ منقضی", "limited": "⚠️ محدود"}
                        text += f"📌 وضعیت پنل: {status_map.get(panel_status, panel_status)}\n"
                else:
                    text += "\n\n⚠️ اطلاعات مصرف از پنل دریافت نشد."
            except Exception as e:
                logger.error(f"order_detail usage error: {e}")
                text += "\n\n⚠️ خطا در دریافت اطلاعات مصرف."

    kb = [[back_button("my_services")]]
    if status == "paid" and conf_data:
        try:
            conf = json.loads(conf_data)
            text += f"\n\n🔗 لینک اشتراک:\n<code>{conf.get('subscription_url', '—')}</code>"
            kb.insert(0, [
                InlineKeyboardButton("📷 QR Code", callback_data=f"qr_{order_id}"),
                InlineKeyboardButton("📄 دانلود فایل", callback_data=f"dlcfg_{order_id}"),
            ])
            kb.insert(1, [InlineKeyboardButton("📖 آموزش", callback_data=f"guide_{order_id}")])
            kb.insert(2, [InlineKeyboardButton("🔄 تمدید سرویس", callback_data=f"renew_{order_id}")])
            toggle_label = "🔴 خاموش کردن تمدید خودکار" if auto_renew else "🟢 روشن کردن تمدید خودکار"
            kb.insert(3, [InlineKeyboardButton(toggle_label, callback_data=f"toggle_auto_renew_{order_id}")])
            kb.insert(4, [InlineKeyboardButton("🔀 انتقال سرویس", callback_data=f"transfer_{order_id}")])
        except Exception:
            pass

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)


async def toggle_auto_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """روشن/خاموش کردن تمدید خودکار برای یک سرویس"""
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT auto_renew, status FROM orders WHERE id = ? AND user_id = ?",
            (order_id, user_id)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[1] != "paid":
            await query.answer("سفارش معتبر نیست", show_alert=True)
            return
        new_val = 0 if (row[0] or 0) else 1
        await db.execute("UPDATE orders SET auto_renew = ? WHERE id = ?", (new_val, order_id))
        await db.commit()

    if new_val:
        await query.answer("✅ تمدید خودکار فعال شد. قبل از انقضا از کیف پول تمدید می‌شود.", show_alert=True)
    else:
        await query.answer("🔴 تمدید خودکار غیرفعال شد.", show_alert=True)
    # رفرش صفحه جزئیات
    return await order_detail(update, context)


# ---------- انتقال سرویس ----------
async def transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[1])
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT config_name, server_type, volume_gb, status FROM orders WHERE id = ? AND user_id = ? AND status = 'paid'",
            (order_id, user_id)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await query.answer("سفارش معتبر نیست یا پرداخت نشده", show_alert=True)
        return

    conf_name, server, vol, status = row
    context.user_data["transfer_order_id"] = order_id
    context.user_data["transfer_config_name"] = conf_name

    if server == "holland":
        plan = f"هلند {vol} گیگ"
    elif server == "unlimited":
        plan = f"نامحدود {vol} ماهه"
    elif server == "custom":
        plan = f"دلخواه {vol} گیگ"
    else:
        plan = f"مولتی {vol} گیگ"

    await query.edit_message_text(
        f"🔀 <b>انتقال سرویس</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 سرویس: <b>{plan}</b>\n"
        f"👤 نام کانفیگ: <code>{conf_name}</code>\n"
        f"🔢 شماره سفارش: #{order_id}\n\n"
        f"آیدی عددی یا نام کاربری (<code>@username</code>) کاربری که می‌خواهید سرویس را به او منتقل کنید وارد کنید:\n\n"
        f"⚠️ بعد از انتقال، دیگر به این سرویس دسترسی نخواهید داشت.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button(f"order_detail_{order_id}")]])
    )
    return TRANSFER_WAITING_TARGET


async def transfer_receive_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    from_user = update.effective_user
    order_id = context.user_data.get("transfer_order_id")
    conf_name = context.user_data.get("transfer_config_name")

    if not order_id:
        await update.message.reply_text("خطا. دوباره از ابتدا تلاش کنید.", reply_markup=main_keyboard(False))
        return ConversationHandler.END

    target_row = None
    async with aiosqlite.connect("bot.db") as db:
        if text.startswith("@"):
            uname = text[1:]
            async with db.execute(
                "SELECT user_id, full_name, username FROM users WHERE username = ?", (uname,)
            ) as cur:
                target_row = await cur.fetchone()
        else:
            try:
                tid = int(text)
                async with db.execute(
                    "SELECT user_id, full_name, username FROM users WHERE user_id = ?", (tid,)
                ) as cur:
                    target_row = await cur.fetchone()
            except:
                await update.message.reply_text(
                    "❌ ورودی نامعتبر است.\nآیدی عددی یا @username وارد کنید:"
                )
                return TRANSFER_WAITING_TARGET

    if not target_row:
        await update.message.reply_text(
            "❌ کاربر یافت نشد.\n"
            "کاربر باید حداقل یک بار ربات را استارت کرده باشد.\n"
            "آیدی یا یوزرنیم را دوباره وارد کنید:"
        )
        return TRANSFER_WAITING_TARGET

    target_id, target_name, target_username = target_row

    if target_id == from_user.id:
        await update.message.reply_text("❌ نمی‌توانید سرویس را به خودتان منتقل کنید.")
        return TRANSFER_WAITING_TARGET

    context.user_data["transfer_target_id"] = target_id
    context.user_data["transfer_target_name"] = target_name or "—"
    context.user_data["transfer_target_username"] = target_username

    uname_display = f"@{target_username}" if target_username else "بدون یوزرنیم"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید انتقال", callback_data="transfer_confirm")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"order_detail_{order_id}")]
    ])
    await update.message.reply_text(
        f"🔀 <b>تأیید انتقال سرویس</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 کانفیگ: <code>{conf_name}</code>\n"
        f"🔢 سفارش: #{order_id}\n\n"
        f"👤 گیرنده:\n"
        f"🆔 <code>{target_id}</code>\n"
        f"📛 {target_name or '—'}\n"
        f"🔗 {uname_display}\n\n"
        f"⚠️ با تأیید، مالکیت سرویس به طور کامل به این کاربر منتقل می‌شود و دیگر در لیست سرویس‌های شما نمایش داده نمی‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )
    return TRANSFER_CONFIRM


async def transfer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = context.user_data.get("transfer_order_id")
    target_id = context.user_data.get("transfer_target_id")
    conf_name = context.user_data.get("transfer_config_name")
    from_user = query.from_user

    if not order_id or not target_id:
        await query.edit_message_text("❌ اطلاعات ناقص است. دوباره تلاش کنید.")
        return ConversationHandler.END

    # بررسی مجدد مالکیت
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, server_type, volume_gb FROM orders WHERE id = ? AND status = 'paid'",
            (order_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row or row[0] != from_user.id:
            await query.edit_message_text("❌ شما مالک این سرویس نیستید یا سفارش معتبر نیست.")
            return ConversationHandler.END

        server, vol = row[1], row[2]

        # انتقال
        await db.execute(
            "UPDATE orders SET user_id = ? WHERE id = ?",
            (target_id, order_id)
        )
        await db.commit()

    # پیام به فرستنده
    await query.edit_message_text(
        f"✅ <b>انتقال با موفقیت انجام شد</b>\n\n"
        f"سرویس <code>{conf_name}</code> (سفارش #{order_id}) به کاربر <code>{target_id}</code> منتقل شد.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("my_services")]])
    )

    # پیام به گیرنده
    if server == "holland":
        plan = f"هلند {vol} گیگ"
    elif server == "unlimited":
        plan = f"نامحدود {vol} ماهه"
    elif server == "custom":
        plan = f"دلخواه {vol} گیگ"
    else:
        plan = f"مولتی {vol} گیگ"

    try:
        await context.bot.send_message(
            target_id,
            f"🎁 <b>سرویس جدید دریافت کردید!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"یک سرویس از طرف کاربر دیگر به شما منتقل شد.\n\n"
            f"📦 پلن: <b>{plan}</b>\n"
            f"👤 نام کانفیگ: <code>{conf_name}</code>\n"
            f"🔢 شماره سفارش: #{order_id}\n\n"
            f"از بخش «📦 سرویس‌های من» می‌توانید جزئیات و لینک اشتراک را مشاهده کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")]
            ])
        )
    except Exception as e:
        logger.error(f"notify transfer target {target_id}: {e}")

    # پاک کردن داده‌های موقت
    for key in ["transfer_order_id", "transfer_target_id", "transfer_config_name",
                "transfer_target_name", "transfer_target_username"]:
        context.user_data.pop(key, None)

    return ConversationHandler.END


# ---------- اکانت تست ----------
async def test_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT test_used, last_test_at FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

    if row and row[0]:
        when = ""
        if row[1]:
            try:
                when = "\n📅 تاریخ دریافت: " + row[1][:16].replace("T", " ")
            except Exception:
                when = ""
        await query.edit_message_text(
            "🧪 <b>اکانت تست</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "شما قبلاً اکانت تست خود را دریافت کرده‌اید.\n"
            "هر کاربر فقط <b>یک‌بار</b> می‌تواند اکانت تست بگیرد."
            + when + "\n\n"
            "برای سرویس بیشتر از بخش خرید استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
            parse_mode=ParseMode.HTML,
        )
        return

    test_mb = await get_int_setting("test_volume_mb", 30)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ وارد کردن نام کاربری", callback_data="test_enter_name")],
        [InlineKeyboardButton("🎲 خودکار انتخاب کن", callback_data="test_auto_name")],
        [back_button()]
    ])
    await query.edit_message_text(
        f"🧪 <b>اکانت تست {test_mb} مگابایتی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ هر کاربر فقط <b>یک‌بار</b> می‌تواند اکانت تست دریافت کند.\n\n"
        f"لطفاً نام کاربری را انتخاب کنید 👇",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def test_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["is_test"] = True
    await query.edit_message_text("✏️ نام کاربری مورد نظر را ارسال کنید:")
    return WAITING_USERNAME

async def test_auto_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = "test_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    await deliver_test(query, context, name)

async def deliver_test(update_or_query, context, name: str):
    user = update_or_query.from_user if hasattr(update_or_query, "from_user") else update_or_query.effective_user

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT test_used FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
        if row and row[0]:
            msg = "🧪 شما قبلاً اکانت تست گرفته‌اید. هر کاربر فقط یک‌بار مجاز است."
            try:
                if hasattr(update_or_query, "edit_message_text"):
                    await update_or_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[back_button()]]))
                else:
                    await update_or_query.message.reply_text(msg, reply_markup=main_keyboard(False))
            except Exception:
                pass
            return

    config = await create_config_from_panel(name, 0, days=1, is_test=True)

    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "UPDATE users SET test_used = 1, last_test_at = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user.id)
        )
        # ذخیره برای حذف خودکار
        await db.execute(
            "INSERT INTO test_accounts (user_id, username, created_at) VALUES (?, ?, ?)",
            (user.id, config["username"], datetime.now().isoformat())
        )
        await db.commit()

    qr = generate_qr(config["subscription_url"])
    tracking = generate_tracking_code()
    caption = (
        f"🧪 اکانت تست شما آماده است!\n\n"
        f"👤 نام کاربری: <code>{config['username']}</code>\n"
        f"🔗 لینک اشتراک:\n<code>{config['subscription_url']}</code>\n\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"📊 حجم: {config['volume']}\n"
        f"⏳ اعتبار: ۲۴ ساعت"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏳ زمان: ۲۴ ساعت", callback_data="noop")],
        [InlineKeyboardButton(f"📊 حجم: {config['volume']}", callback_data="noop")],
        [InlineKeyboardButton("📷 دریافت QR CODE", callback_data="qr_test")],
        [InlineKeyboardButton("📖 آموزش استفاده", callback_data="guide_test")],
        [back_button()]
    ])
    context.user_data["last_config"] = config

    if hasattr(update_or_query, "edit_message_text"):
        await update_or_query.message.reply_photo(photo=InputFile(qr, "qr.png"), caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
        await update_or_query.edit_message_text("✅ اکانت تست برای شما ساخته شد.")
    else:
        await update_or_query.message.reply_photo(photo=InputFile(qr, "qr.png"), caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)

# ---------- کیف پول ----------
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    balance = row[0] if row else 0
    loyalty = await loyalty_progress_text(user_id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="charge_wallet")],
        [InlineKeyboardButton("📜 تاریخچه کیف پول", callback_data="wallet_history")],
        [back_button()]
    ])
    msg = (
        "💰 کیف پول شما\n\n"
        f"موجودی فعلی: <b>{balance:,} تومان</b>\n\n"
        f"{loyalty}\n\n"
        f"🎁 با شارژ بالای {WALLET_BONUS_MIN:,} تومان، {WALLET_BONUS_PERCENT}% هدیه دریافت می‌کنید!"
    )
    await query.edit_message_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)


async def wallet_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تاریخچه شارژ و خریدهای مرتبط با کیف پول"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    items = []  # (iso_date, line)

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT amount, status, created_at FROM wallet_charges
               WHERE user_id = ? ORDER BY id DESC LIMIT 30""",
            (user_id,)
        ) as cur:
            for amount, status, created in await cur.fetchall():
                st_map = {
                    "pending": "⏳ در انتظار",
                    "paid": "✅ تأیید شده",
                    "approved": "✅ تأیید شده",
                    "rejected": "❌ رد شده",
                }
                st = st_map.get(status, status or "—")
                date = (created or "")[:16].replace("T", " ")
                items.append((created or "", f"💳 شارژ {amount:,} ت — {st}\n   🕐 {date}"))

        async with db.execute(
            """SELECT id, final_price, server_type, volume_gb, status, created_at, config_data
               FROM orders
               WHERE user_id = ? AND final_price > 0 AND status IN ('paid', 'rejected', 'pending')
               ORDER BY id DESC LIMIT 30""",
            (user_id,)
        ) as cur:
            for oid, price, server, vol, status, created, conf in await cur.fetchall():
                # رد شدن renew را جدا نشون بده
                is_renew = conf and "renew" in (conf or "")
                kind = "🔄 تمدید" if is_renew else "🛒 خرید"
                st_map = {"paid": "✅", "rejected": "❌", "pending": "⏳"}
                st = st_map.get(status, status)
                date = (created or "")[:16].replace("T", " ")
                items.append(
                    (created or "", f"{kind} #{oid} — {price:,} ت {st}\n   🕐 {date}")
                )

        async with db.execute(
            """SELECT id, final_price, created_at FROM proxy_orders
               WHERE user_id = ? AND final_price > 0
               ORDER BY id DESC LIMIT 20""",
            (user_id,)
        ) as cur:
            for oid, price, created in await cur.fetchall():
                date = (created or "")[:16].replace("T", " ")
                items.append((created or "", f"🌐 پروکسی #{oid} — {price:,} ت\n   🕐 {date}"))

    items.sort(key=lambda x: x[0] or "", reverse=True)
    items = items[:20]

    if not items:
        body = "هنوز تراکنشی ثبت نشده است."
    else:
        body = "\n\n".join(line for _, line in items)

    text = (
        f"📜 <b>تاریخچه کیف پول / تراکنش‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"آخرین {len(items)} مورد نمایش داده شد."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به کیف پول", callback_data="wallet")],
        [back_button()],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def charge_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💵 مبلغ مورد نظر برای شارژ را به تومان ارسال کنید.\n"
        "مثال: 50000"
    )
    return WAITING_WALLET_AMOUNT
async def receive_wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        min_charge = await get_int_setting("min_charge", 10000)
        if amount < min_charge:
            await update.message.reply_text(f"حداقل مبلغ شارژ {min_charge:,} تومان است.")
            return WAITING_WALLET_AMOUNT
    except:
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید.")
        return WAITING_WALLET_AMOUNT

    context.user_data["wallet_amount"] = amount
    text = (
        f"🧾 <b>شارژ کیف پول</b>\n"
        f"—————————————\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n"
        f"—————————————\n"
        f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
        f"👤 به نام: {CARD_NAME}\n\n"
        f"🎁 با شارژ بالای {WALLET_BONUS_MIN:,} تومان، {WALLET_BONUS_PERCENT}٪ هدیه می‌گیرید!\n\n"
        f"ℹ️ پس از واریز وجه، روی دکمه «📤 ارسال رسید» بزنید."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال رسید", callback_data="wallet_send_receipt")],
        [back_button("wallet")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def wallet_send_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📸 لطفاً عکس یا فایل رسید پرداخت رو همینجا ارسال کنید.")
    return WAITING_WALLET_RECEIPT

async def receive_wallet_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    amount = context.user_data.get("wallet_amount", 0)
    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document

    if not photo and not document:
        await update.message.reply_text("لطفاً فقط عکس یا فایل ارسال کنید.")
        return WAITING_WALLET_RECEIPT

    receipt_uid = get_receipt_unique_id(update.message)
    if receipt_uid and await is_receipt_used(receipt_uid):
        await update.message.reply_text(
            "❌ این رسید قبلاً استفاده شده است.\n"
            "لطفاً رسید پرداخت جدید ارسال کنید."
        )
        return WAITING_WALLET_RECEIPT

    if not await check_receipt_rate_limit(user.id):
        await update.message.reply_text(
            f"❌ تعداد ارسال رسید بیش از حد مجاز است.\n"
            f"حداکثر {RECEIPT_RATE_LIMIT_COUNT} رسید در {RECEIPT_RATE_LIMIT_MINUTES} دقیقه.\n"
            f"لطفاً کمی بعد دوباره تلاش کنید."
        )
        return WAITING_WALLET_RECEIPT

    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "INSERT INTO wallet_charges (user_id, amount, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user.id, amount, datetime.now().isoformat())
        )
        charge_id = cur.lastrowid
        await db.commit()

    if receipt_uid:
        await store_receipt_id(receipt_uid, user.id, "wallet")

    admin_text = (
        f"💳 درخواست شارژ کیف پول #{charge_id}\n"
        f"—————————————\n"
        f"👤 کاربر: {user.full_name}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"💰 مبلغ: {amount:,} تومان"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید شارژ", callback_data=f"approve_charge_{charge_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_charge_{charge_id}")]
    ])
    if photo:
        await context.bot.send_photo(ADMIN_ID, photo.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_document(ADMIN_ID, document.file_id, caption=admin_text, reply_markup=kb, parse_mode=ParseMode.HTML)

    await update.message.reply_text(
        f"✅ رسید شارژ ثبت شد.\nشماره پیگیری: #{charge_id}\nمنتظر تأیید ادمین بمانید.",
        reply_markup=main_keyboard(await is_admin(user.id))
    )
    return ConversationHandler.END

async def approve_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    charge_id = int(query.data.split("_")[-1])

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, amount, status FROM wallet_charges WHERE id = ?",
            (charge_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await query.answer("درخواست یافت نشد", show_alert=True)
            return

        user_id, amount, status = row
        if status != "pending":
            await query.answer("این درخواست قبلاً بررسی شده", show_alert=True)
            return

        # محاسبه هدیه
        bonus = 0
        if amount >= WALLET_BONUS_MIN:
            bonus = int(amount * WALLET_BONUS_PERCENT / 100)

        total_add = amount + bonus

        # افزایش موجودی (مبلغ اصلی + هدیه)
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (total_add, user_id)
        )
        # تغییر وضعیت
        await db.execute(
            "UPDATE wallet_charges SET status = 'approved' WHERE id = ?",
            (charge_id,)
        )
        await db.commit()

        # موجودی جدید
        async with db.execute(
            "SELECT balance FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            new_balance = (await cur.fetchone())[0]

    # پیام به کاربر
    if bonus > 0:
        user_msg = (
            f"✅ <b>شارژ کیف پول تأیید شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💳 مبلغ واریزی: <b>{amount:,}</b> تومان\n"
            f"🎁 هدیه شارژ ({WALLET_BONUS_PERCENT}٪): <b>{bonus:,}</b> تومان\n"
            f"💰 مجموع اضافه‌شده: <b>{total_add:,}</b> تومان\n"
            f"💳 موجودی جدید: <b>{new_balance:,}</b> تومان\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"از همراهی شما سپاسگزاریم 🌟"
        )
    else:
        user_msg = (
            f"✅ <b>شارژ کیف پول تأیید شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💳 مبلغ: <b>{amount:,}</b> تومان\n"
            f"💳 موجودی جدید: <b>{new_balance:,}</b> تومان\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"از همراهی شما سپاسگزاریم 🌟"
        )

    try:
        await context.bot.send_message(user_id, user_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"notify charge approve {user_id}: {e}")

    await log_admin_action(query.from_user.id, "approve_charge", charge_id)
    await notify_admin_sale(
        context.bot,
        kind="wallet",
        order_id=charge_id,
        user_id=user_id,
        amount=amount,
        plan="شارژ کیف پول" + (f" + هدیه {bonus:,}" if bonus else ""),
        payment="رسید / تأیید ادمین",
        extra=f"💳 موجودی جدید کاربر: <b>{new_balance:,}</b> تومان" if new_balance is not None else None,
    )
    # آپدیت پیام ادمین
    caption = (query.message.caption or query.message.text or "") + f"\n\n✅ تأیید شد"
    if bonus > 0:
        caption += f"\n🎁 هدیه {bonus:,} تومان نیز اضافه شد"
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(caption=caption)
        else:
            await query.edit_message_text(caption)
    except Exception:
        pass

async def reject_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    charge_id = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id FROM wallet_charges WHERE id = ? AND status = 'pending'",
            (charge_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("قبلاً بررسی شده", show_alert=True)
            return

    context.user_data["reject_charge_id"] = charge_id
    context.user_data["reject_charge_user"] = row[0]
    context.user_data["reject_charge_chat"] = query.message.chat_id
    context.user_data["reject_charge_msg"] = query.message.message_id
    context.user_data["reject_charge_caption"] = query.message.caption or ""

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 مبلغ ناقص / مغایرت", callback_data=f"rejch_preset_amount_{charge_id}")],
        [InlineKeyboardButton("🖼 رسید نامشخص / ناخوانا", callback_data=f"rejch_preset_unclear_{charge_id}")],
        [InlineKeyboardButton("🔁 واریز تکراری", callback_data=f"rejch_preset_duplicate_{charge_id}")],
        [InlineKeyboardButton("⏰ رسید قدیمی / منقضی", callback_data=f"rejch_preset_old_{charge_id}")],
        [InlineKeyboardButton("❌ کارت اشتباه / گیرنده نادرست", callback_data=f"rejch_preset_card_{charge_id}")],
        [InlineKeyboardButton("⏭ ادامه بدون توضیحات", callback_data=f"rejch_no_note_{charge_id}")],
    ])
    msg = (
        f"❌ <b>رد شارژ کیف پول #{charge_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"دلیل آماده را انتخاب کنید:"
    )
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(caption=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await query.edit_message_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(query.from_user.id, msg, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _finish_reject_charge(update, context, charge_id: int, reason: Optional[str]):
    query = update.callback_query
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, status FROM wallet_charges WHERE id = ?", (charge_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[1] != "pending":
            if query:
                await query.answer("قبلاً بررسی شده", show_alert=True)
            return
        user_id = row[0]
        await db.execute("UPDATE wallet_charges SET status = 'rejected' WHERE id = ?", (charge_id,))
        await db.commit()

    if reason:
        user_msg = (
            f"❌ <b>درخواست شارژ کیف پول رد شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"شماره: <b>#{charge_id}</b>\n\n"
            f"📝 توضیحات ادمین:\n{reason}\n\n"
            f"در صورت مشکل: {SUPPORT_USERNAME}"
        )
    else:
        user_msg = (
            f"❌ درخواست شارژ کیف پول شما توسط ادمین رد شد.\n"
            f"شماره: #{charge_id}\n"
            f"در صورت مشکل: {SUPPORT_USERNAME}"
        )
    try:
        await context.bot.send_message(user_id, user_msg, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    admin_id = query.from_user.id if query else 0
    await log_admin_action(admin_id, "reject_charge", charge_id, reason or "بدون توضیح")

    confirm = f"✅ شارژ #{charge_id} رد شد."
    if reason:
        confirm += f"\n📝 {reason}"
    try:
        if query.message and query.message.photo:
            await query.edit_message_caption(caption=confirm, reply_markup=None)
        else:
            await query.edit_message_text(confirm, reply_markup=main_keyboard(True))
    except Exception:
        try:
            await context.bot.send_message(query.from_user.id, confirm, reply_markup=main_keyboard(True))
        except Exception:
            pass


async def reject_charge_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        return
    raw = query.data[len("rejch_preset_"):]
    parts = raw.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        await query.answer("نامعتبر", show_alert=True)
        return
    key, charge_id = parts[0], int(parts[1])
    reason = REJECT_PRESET_REASONS.get(key)
    if not reason:
        await query.answer("دلیل نامعتبر", show_alert=True)
        return
    await query.answer()
    await _finish_reject_charge(update, context, charge_id, reason)


async def reject_charge_no_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        return
    charge_id = int(query.data.split("_")[-1])
    await query.answer()
    await _finish_reject_charge(update, context, charge_id, None)


# ---------- پشتیبانی + تیکت ----------
# ---------- پشتیبانی + تیکت ----------
# سوالات پرتکرار پشتیبانی (کلید → (عنوان دکمه، پاسخ خودکار پشتیبانی))
DEFAULT_SUPPORT_QUICK_QA = {
    "sqa_buy": (
        "🛒 چطور سرویس تهیه کنم؟",
        "سلام 👋\n"
        "برای تهیه سرویس از منوی اصلی گزینه «🛒 خرید سرویس» را انتخاب کنید، "
        "سپس دسته‌بندی (هلند / مولتی / نامحدود / دلخواه) و سرویس موردنظر را انتخاب کنید. "
        "بعد از انتخاب نام کاربری و پرداخت، سرویس برای شما فعال می‌شود."
    ),
    "sqa_receipt": (
        "📤 چطور رسید بفرستم؟",
        "سلام 👋\n"
        "بعد از واریز مبلغ به کارت، در فاکتور سفارش روی دکمه «📤 ارسال رسید» بزنید و "
        "عکس یا فایل رسید را ارسال کنید. سفارش شما در صف بررسی ادمین قرار می‌گیرد."
    ),
    "sqa_wallet": (
        "💰 کیف پول چطور کار می‌کند؟",
        "سلام 👋\n"
        "از منوی «💰 کیف پول» می‌توانید موجودی خود را ببینید و شارژ کنید. "
        "موجودی کیف پول فقط داخل ربات برای خرید/تمدید سرویس و پروکسی قابل استفاده است "
        "و قابل برداشت نقدی نیست."
    ),
    "sqa_renew": (
        "🔄 تمدید سرویس چطور است؟",
        "سلام 👋\n"
        "از «📦 سرویس‌های من» سرویس موردنظر را انتخاب کنید و دکمه تمدید را بزنید. "
        "همچنین می‌توانید از «🔄 تمدید سریع» استفاده کنید. "
        "در صورت فعال بودن تمدید خودکار، قبل از انقضا از موجودی کیف پول تمدید می‌شود."
    ),
    "sqa_test": (
        "🧪 اکانت تست چطور بگیرم؟",
        "سلام 👋\n"
        "از منوی اصلی «🧪 اکانت تست» را بزنید. هر کاربر معمولاً یک‌بار می‌تواند "
        "اکانت تست دریافت کند. در صورت نیاز به فعال‌سازی مجدد با پشتیبانی در ارتباط باشید."
    ),
    "sqa_config": (
        "📱 کانفیگ را چطور استفاده کنم؟",
        "سلام 👋\n"
        "بعد از تحویل سرویس، لینک اشتراک و QR برای شما ارسال می‌شود. "
        "از دکمه «📖 آموزش استفاده» کنار سرویس، راهنمای اپ‌هایی مثل V2Box / v2rayNG را ببینید. "
        "لینک اشتراک را در اپ کپی/اسکن کنید."
    ),
    "sqa_track": (
        "🔍 پیگیری سفارش چگونه است؟",
        "سلام 👋\n"
        "پس از ثبت/تحویل سفارش یک کد رهگیری دریافت می‌کنید. "
        "از منوی «🔍 پیگیری سفارش» کد را وارد کنید تا وضعیت سفارش نمایش داده شود."
    ),
    "sqa_proxy": (
        "🌐 خرید پروکسی چگونه است؟",
        "سلام 👋\n"
        "از منوی «🌐 پروکسی» لوکیشن، تعداد و روز را انتخاب کنید، فاکتور را ببینید و "
        "با کیف پول یا ارسال رسید پرداخت کنید. پس از تأیید، لیست پروکسی‌ها برای شما ارسال می‌شود."
    ),
}


async def get_support_quick_qa() -> dict:
    """سوالات آماده پشتیبانی از تنظیمات یا پیش‌فرض"""
    raw = await get_setting("support_quick_qa")
    if raw and raw.strip():
        try:
            data = json.loads(raw)
            # فرمت: {key: [title, answer]} یا {key: {"title":..., "answer":...}}
            result = {}
            for k, v in data.items():
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    result[k] = (str(v[0]), str(v[1]))
                elif isinstance(v, dict):
                    result[k] = (str(v.get("title") or k), str(v.get("answer") or ""))
            if result:
                return result
        except Exception as e:
            logger.error(f"get_support_quick_qa: {e}")
    return dict(DEFAULT_SUPPORT_QUICK_QA)


async def save_support_quick_qa(qa: dict):
    """ذخیره سوالات آماده در settings"""
    serializable = {k: [v[0], v[1]] for k, v in qa.items()}
    await set_setting("support_quick_qa", json.dumps(serializable, ensure_ascii=False))


# سازگاری با کد قدیمی که SUPPORT_QUICK_QA را مستقیم می‌خواند
SUPPORT_QUICK_QA = DEFAULT_SUPPORT_QUICK_QA


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 ارسال تیکت جدید", callback_data="new_ticket")],
        [InlineKeyboardButton("📋 تیکت‌های من", callback_data="my_tickets")],
        [InlineKeyboardButton("💬 ارتباط مستقیم با پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")],
        [back_button()],
    ])
    await query.edit_message_text(
        "💬 <b>پشتیبانی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "می‌توانید تیکت جدید ارسال کنید، تیکت‌های قبلی را ببینید "
        "یا مستقیماً با پشتیبانی در ارتباط باشید.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def support_quick_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ خودکار پشتیبانی برای سوالات آماده"""
    query = update.callback_query
    await query.answer()
    key = query.data
    qa = await get_support_quick_qa()
    item = qa.get(key)
    if not item:
        await query.answer("سوال یافت نشد", show_alert=True)
        return
    title, answer = item
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 سوالات پاسخ آماده", callback_data="support_ready_qa")],
        [InlineKeyboardButton("✍️ نوشتن متن تیکت", callback_data="write_ticket")],
        [InlineKeyboardButton("🔙 بازگشت به پشتیبانی", callback_data="support")],
        [back_button()],
    ])
    await query.edit_message_text(
        f"💬 <b>پاسخ پشتیبانی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ <b>{title}</b>\n\n"
        f"{answer}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"اگر مشکل برطرف نشد، متن تیکت بنویسید یا سوال دیگری انتخاب کنید.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات حساب کاربری"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT full_name, username, balance, referral_code, is_banned,
                      join_date, test_used, warnings, referred_by
               FROM users WHERE user_id = ?""",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await get_or_create_user(user_id, user.username, user.full_name)
            async with db.execute(
                """SELECT full_name, username, balance, referral_code, is_banned,
                          join_date, test_used, warnings, referred_by
                   FROM users WHERE user_id = ?""",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()

        full_name, username, balance, ref_code, is_banned, join_date, test_used, warnings, referred_by = row
        balance = balance or 0
        warnings = warnings or 0

        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'paid'",
            (user_id,),
        ) as cur:
            paid_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        ) as cur:
            pending_count = (await cur.fetchone())[0]

        async with db.execute(
            """SELECT COUNT(*) FROM orders
               WHERE user_id = ? AND status = 'paid'
                 AND config_name IS NOT NULL
                 AND status != 'expired'""",
            (user_id,),
        ) as cur:
            # تقریبی سرویس‌های فعال (بدون چک پنل)
            services_count = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COALESCE(SUM(final_price), 0) FROM orders WHERE user_id = ? AND status = 'paid'",
            (user_id,),
        ) as cur:
            total_spent = (await cur.fetchone())[0] or 0

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
        ) as cur:
            invited = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_id = ?", (user_id,)
        ) as cur:
            tickets_count = (await cur.fetchone())[0]

        is_adm = await is_admin(user_id)

    join_str = join_date[:16].replace("T", " ") if join_date else "—"
    status = "🚫 مسدود" if is_banned else "✅ فعال"
    test_text = "استفاده شده" if test_used else "در دسترس"
    uname = f"@{username}" if username else "—"
    role = "🛠 ادمین" if is_adm else "👤 کاربر"

    try:
        loyalty = await loyalty_progress_text(user_id)
    except Exception:
        loyalty = ""

    text = (
        f"👤 <b>حساب کاربری شما</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{user_id}</code>\n"
        f"📛 نام: {full_name or user.full_name or '—'}\n"
        f"🔗 یوزرنیم: {uname}\n"
        f"📌 نقش: {role}\n"
        f"📊 وضعیت: {status}\n"
        f"📅 عضویت: {join_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 موجودی کیف پول: <b>{balance:,}</b> تومان\n"
        f"🛒 سفارشات پرداخت‌شده: <b>{paid_count}</b>\n"
        f"⏳ سفارشات در انتظار: <b>{pending_count}</b>\n"
        f"📦 سرویس‌های ثبت‌شده: <b>{services_count}</b>\n"
        f"💵 مجموع خرید: <b>{total_spent:,}</b> تومان\n"
        f"🧪 اکانت تست: {test_text}\n"
        f"⚠️ اخطارها: <b>{warnings}</b> از ۳\n"
        f"🎁 کد دعوت: <code>{ref_code or '—'}</code>\n"
        f"👥 دعوت‌شدگان: <b>{invited}</b> نفر\n"
        f"🎫 تیکت‌ها: <b>{tickets_count}</b>\n"
    )
    if loyalty:
        text += f"━━━━━━━━━━━━━━━━━━\n{loyalty}\n"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 کیف پول", callback_data="wallet"),
            InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services"),
        ],
        [
            InlineKeyboardButton("📋 تاریخچه سفارشات", callback_data="order_history"),
            InlineKeyboardButton("👥 دعوت دوستان", callback_data="referral"),
        ],
        [back_button()],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def new_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی ارسال تیکت: سوالات آماده یا نوشتن متن آزاد"""
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ سوالات پاسخ آماده", callback_data="support_ready_qa")],
        [InlineKeyboardButton("✍️ نوشتن متن تیکت", callback_data="write_ticket")],
        [InlineKeyboardButton("🔙 بازگشت به پشتیبانی", callback_data="support")],
        [back_button()],
    ])
    await query.edit_message_text(
        "🎫 <b>ارسال تیکت</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "اگر سوالتان پرتکرار است، از «سوالات پاسخ آماده» استفاده کنید.\n"
        "در غیر این صورت «نوشتن متن تیکت» را بزنید و پیام خود را بنویسید.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def support_ready_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش دکمه‌های سوالات با پاسخ آماده"""
    query = update.callback_query
    await query.answer()
    qa = await get_support_quick_qa()
    qa_buttons = [
        [InlineKeyboardButton(title, callback_data=key)]
        for key, (title, _ans) in qa.items()
    ]
    qa_buttons.append([InlineKeyboardButton("✍️ نوشتن متن تیکت", callback_data="write_ticket")])
    qa_buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="new_ticket")])
    await query.edit_message_text(
        "❓ <b>سوالات پاسخ آماده</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "سوال موردنظر را انتخاب کنید تا پاسخ پشتیبانی نمایش داده شود:",
        reply_markup=InlineKeyboardMarkup(qa_buttons),
        parse_mode=ParseMode.HTML,
    )


async def write_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست متن آزاد تیکت"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎫 متن تیکت خود را بنویسید و ارسال کنید:\n\n"
        "(مشکل، سؤال یا درخواست خود را کامل توضیح دهید)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 انصراف", callback_data="new_ticket")],
        ]),
    )
    return WAITING_TICKET

async def receive_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 5:
        await update.message.reply_text("متن تیکت خیلی کوتاه است. لطفاً کامل‌تر بنویسید.")
        return WAITING_TICKET

    user = update.effective_user
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            "INSERT INTO tickets (user_id, message, created_at) VALUES (?, ?, ?)",
            (user.id, text, datetime.now().isoformat())
        )
        ticket_id = cur.lastrowid
        await db.commit()

    await context.bot.send_message(
        ADMIN_ID,
        f"🎫 <b>تیکت جدید #{ticket_id}</b>\n"
        f"—————————————\n"
        f"👤 {user.full_name} (@{user.username or '—'})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"{text}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ پاسخ به تیکت", callback_data=f"reply_ticket_{ticket_id}")]
        ])
    )
    await update.message.reply_text(
        f"✅ تیکت شما با شماره <b>#{ticket_id}</b> ثبت شد.\n"
        f"به زودی پاسخ داده می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(await is_admin(user.id))
    )
    return ConversationHandler.END

async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT id, message, status, created_at, admin_reply FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "📋 شما هنوز تیکتی ارسال نکرده‌اید.",
            reply_markup=InlineKeyboardMarkup([[back_button("support")]])
        )
        return

    text = "📋 <b>تیکت‌های شما</b>\n━━━━━━━━━━━━━━━━━━\n"
    for tid, msg, status, created, reply in rows:
        status_emoji = "🟢" if status == "closed" else "🟡"
        text += (
            f"{status_emoji} #{tid} | {status}\n"
            f"📅 {created[:16].replace('T', ' ') if created else '—'}\n"
            f"📝 {msg[:80]}{'...' if len(msg) > 80 else ''}\n"
        )
        if reply:
            text += f"💬 پاسخ ادمین: {reply[:100]}{'...' if len(reply) > 100 else ''}\n"
        text += "—————————————\n"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[back_button("support")]]),
        parse_mode=ParseMode.HTML
    )

async def reply_ticket_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    ticket_id = int(query.data.split("_")[-1])
    context.user_data["reply_ticket_id"] = ticket_id
    await query.edit_message_text(f"✍️ پاسخ تیکت #{ticket_id} را بنویسید:")
    return ADMIN_REPLY_TICKET

async def admin_reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_text = update.message.text.strip()
    ticket_id = context.user_data.get("reply_ticket_id")
    if not ticket_id:
        await update.message.reply_text("خطا. دوباره تلاش کنید.")
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT user_id, message FROM tickets WHERE id = ?", (ticket_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.message.reply_text("تیکت یافت نشد.")
            return ConversationHandler.END
        user_id, original_msg = row
        await db.execute(
            "UPDATE tickets SET status = 'closed', admin_reply = ?, replied_at = ? WHERE id = ?",
            (reply_text, datetime.now().isoformat(), ticket_id)
        )
        await db.commit()

    try:
        await context.bot.send_message(
            user_id,
            f"💬 <b>پاسخ به تیکت #{ticket_id}</b>\n\n"
            f"📝 تیکت شما:\n{original_msg}\n\n"
            f"✅ پاسخ پشتیبانی:\n{reply_text}",
            parse_mode=ParseMode.HTML
        )
    except:
        pass

    await update.message.reply_text(
        f"✅ پاسخ تیکت #{ticket_id} ارسال شد.",
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

# ---------- دعوت از دوستان ----------
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT referral_code FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        code = row[0] if row else "ERROR"

        # تعداد دعوت‌شدگان
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
        ) as cur:
            total_invited = (await cur.fetchone())[0]

        # تعداد کسانی که حداقل یک خرید موفق داشتن
        async with db.execute(
            """SELECT COUNT(DISTINCT u.user_id) FROM users u
               INNER JOIN orders o ON u.user_id = o.user_id
               WHERE u.referred_by = ? AND o.status = 'paid'""",
            (user_id,)
        ) as cur:
            total_buyers = (await cur.fetchone())[0]

        # مجموع درآمد از رفرال (تعداد دعوت‌شده × هدیه فعلی — تقریبی، چون هدیه ممکنه تغییر کرده باشه)
        # بهتر: اگر جدول تراکنش نداریم، از تعداد دعوت‌شده × هدیه فعلی استفاده می‌کنیم
        bonus = await get_int_setting("referral_bonus", 5000)
        estimated_earnings = total_invited * bonus

        # آخرین ۵ دعوت‌شده
        async with db.execute(
            """SELECT full_name, username, join_date FROM users
               WHERE referred_by = ? ORDER BY join_date DESC LIMIT 5""",
            (user_id,)
        ) as cur:
            recent = await cur.fetchall()

    bot_user = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_user}?start=ref_{code}"

    text = (
        f"👥 <b>دعوت از دوستان</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"با دعوت هر دوست، مبلغ <b>{bonus:,} تومان</b> به کیف پول شما اضافه می‌شود.\n\n"
        f"🔗 <b>لینک اختصاصی شما:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📊 <b>آمار دقیق شما:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 تعداد دعوت‌شدگان: <b>{total_invited}</b> نفر\n"
        f"🛒 تعداد خریداران: <b>{total_buyers}</b> نفر\n"
        f"💰 درآمد تقریبی: <b>{estimated_earnings:,}</b> تومان\n"
    )

    if recent:
        text += "\n📋 <b>آخرین دعوت‌شدگان:</b>\n"
        for full_name, username, join_date in recent:
            name = full_name or "—"
            uname = f"@{username}" if username else "بدون یوزرنیم"
            date = join_date[:10] if join_date else "—"
            text += f"• {name} ({uname}) — {date}\n"

    text += "\n💡 لینک را برای دوستانتان بفرستید و درآمد کسب کنید!"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[back_button()]]),
        parse_mode=ParseMode.HTML
    )

# ---------- قوانین ----------
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules_text = await get_setting("rules")
    await query.edit_message_text(
        rules_text,
        reply_markup=InlineKeyboardMarkup([[back_button()]])
    )


DEFAULT_FAQ_TEXT = """❓ سوالات متداول

۱. چطور سرویس بخرم؟
از منو «🛒 خرید سرویس» را بزنید، پلن را انتخاب کنید و پرداخت کنید.

۲. چطور رسید بفرستم؟
بعد از واریز، روی «ارسال رسید» بزنید و عکس رسید را بفرستید.

۳. کد رهگیری چیست؟
بعد از ثبت سفارش یک کد به شما داده می‌شود. با «🔍 پیگیری سفارش» وضعیت را ببینید.

۴. اکانت تست چند بار است؟
هر کاربر فقط یک‌بار می‌تواند اکانت تست بگیرد.

۵. تمدید سرویس چطور است؟
از «📦 سرویس‌های من» سرویس را انتخاب و «تمدید» را بزنید.

۶. مشکل فنی داشتم چه کنم؟
از «💬 پشتیبانی» تیکت بزنید یا با پشتیبانی در ارتباط باشید."""


async def get_faq_text() -> str:
    text = await get_setting("faq")
    if not text or not text.strip():
        return DEFAULT_FAQ_TEXT
    return text


async def faq_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    faq = await get_faq_text()
    # تلگرام محدودیت طول دارد
    if len(faq) > 4000:
        faq = faq[:3990] + "…"
    await query.edit_message_text(
        faq,
        reply_markup=InlineKeyboardMarkup([[back_button()]]),
        parse_mode=ParseMode.HTML,
    )


async def track_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 <b>پیگیری سفارش</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد رهگیری سفارش را ارسال کنید.\n"
        "(مثال: کدهایی که بعد از خرید به شما داده شده)",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button()]]),
    )
    return TRACK_ORDER_CODE


async def track_order_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = (update.message.text or "").strip()
    if not code or len(code) < 4:
        await update.message.reply_text(
            "کد رهگیری نامعتبر است. دوباره ارسال کنید یا بازگشت بزنید.",
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
        )
        return TRACK_ORDER_CODE

    user_id = update.effective_user.id
    found = None
    kind = None

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, server_type, volume_gb, final_price, status, created_at, tracking_code
               FROM orders WHERE tracking_code = ? AND user_id = ?""",
            (code, user_id),
        ) as cur:
            found = await cur.fetchone()
            if found:
                kind = "order"
        if not found:
            async with db.execute(
                """SELECT id, location, quantity, days, final_price, status, created_at, tracking_code
                   FROM proxy_orders WHERE tracking_code = ? AND user_id = ?""",
                (code, user_id),
            ) as cur:
                found = await cur.fetchone()
                if found:
                    kind = "proxy"
        if not found:
            # جستجو بدون محدود user فقط برای اینکه بگوییم مال شما نیست
            async with db.execute(
                "SELECT id FROM orders WHERE tracking_code = ?", (code,)
            ) as cur:
                other = await cur.fetchone()
            if not other:
                async with db.execute(
                    "SELECT id FROM proxy_orders WHERE tracking_code = ?", (code,)
                ) as cur:
                    other = await cur.fetchone()
            if other:
                await update.message.reply_text(
                    "❌ این کد رهگیری متعلق به حساب شما نیست.",
                    reply_markup=main_keyboard(await is_admin(user_id)),
                )
                return ConversationHandler.END

    if not found:
        await update.message.reply_text(
            "❌ سفارشی با این کد رهگیری پیدا نشد.\nکد را بررسی و دوباره تلاش کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 تلاش مجدد", callback_data="track_order")],
                [back_button()],
            ]),
        )
        return ConversationHandler.END

    status_map = {
        "paid": "✅ پرداخت / تحویل شده",
        "pending": "⏳ در انتظار بررسی ادمین",
        "rejected": "🚫 رد شده",
        "expired": "⏰ منقضی",
    }

    if kind == "order":
        oid, server, vol, price, status, created, tracking = found
        server_name = {"holland": "🇳🇱 هلند", "multi": "🌐 مولتی", "unlimited": "💎 نامحدود", "custom": "⚙️ دلخواه"}.get(server, server)
        text_msg = (
            f"🔍 <b>نتیجه پیگیری</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔖 کد: <code>{tracking}</code>\n"
            f"📦 سفارش سرویس: <b>#{oid}</b>\n"
            f"🖥 سرور: {server_name}\n"
            f"📊 حجم/پلن: {vol}\n"
            f"💰 مبلغ: {price:,} تومان\n"
            f"📌 وضعیت: {status_map.get(status, status)}\n"
            f"🕐 تاریخ: {(created or '')[:16].replace('T', ' ')}\n"
        )
        kb = []
        if status == "paid":
            kb.append([InlineKeyboardButton("📦 جزئیات سرویس", callback_data=f"order_detail_{oid}")])
        kb.append([InlineKeyboardButton("🔍 پیگیری دیگر", callback_data="track_order")])
        kb.append([back_button()])
    else:
        oid, location, qty, days, price, status, created, tracking = found
        loc_name = PROXY_LOCATIONS.get(location, {}).get("name", location)
        text_msg = (
            f"🔍 <b>نتیجه پیگیری</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔖 کد: <code>{tracking}</code>\n"
            f"🌐 سفارش پروکسی: <b>#{oid}</b>\n"
            f"📍 لوکیشن: {loc_name}\n"
            f"🔢 تعداد: {qty}\n"
            f"📅 مدت: {days} روز\n"
            f"💰 مبلغ: {price:,} تومان\n"
            f"📌 وضعیت: {status_map.get(status, status)}\n"
            f"🕐 تاریخ: {(created or '')[:16].replace('T', ' ')}\n"
        )
        kb = [
            [InlineKeyboardButton("🔍 پیگیری دیگر", callback_data="track_order")],
            [back_button()],
        ]

    await update.message.reply_text(
        text_msg,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def service_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش خلاصه حجم و روز باقی‌مانده همه سرویس‌های فعال"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    await query.edit_message_text("🔄 در حال دریافت وضعیت سرویس‌ها از پنل...")

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, server_type, volume_gb, config_name, panel_username, config_data
               FROM orders WHERE user_id = ? AND status = 'paid'
               ORDER BY id DESC LIMIT 10""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "📊 شما سرویس فعالی ندارید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy_service")],
                [back_button()],
            ]),
        )
        return

    lines = ["📊 <b>وضعیت سرویس‌های شما</b>", "━━━━━━━━━━━━━━━━━━"]
    buttons = []
    for oid, server, vol, conf_name, panel_user, conf_data in rows:
        server_name = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود", "custom": "دلخواه"}.get(server, server)
        panel_name = panel_user or conf_name
        if not panel_name and conf_data:
            try:
                panel_name = json.loads(conf_data).get("username")
            except Exception:
                pass
        line = f"📦 <b>#{oid}</b> | {server_name} ({vol})"
        if not panel_name:
            line += "\n   ⚠️ نام کاربری پنل موجود نیست"
            lines.append(line)
            lines.append("—————————————")
            buttons.append([InlineKeyboardButton(f"#{oid} جزئیات", callback_data=f"order_detail_{oid}")])
            continue
        try:
            user_info = await get_user_from_panel(panel_name, server_type=server)
            if not user_info:
                line += "\n   ⚠️ دریافت از پنل ناموفق"
            else:
                used = user_info.get("used_traffic") or 0
                limit = user_info.get("data_limit") or 0
                expire_ts = user_info.get("expire") or 0
                used_gb = used / (1024 ** 3)
                limit_gb = limit / (1024 ** 3) if limit > 0 else 0
                remain_gb = max(0, limit_gb - used_gb)
                if limit > 0:
                    line += f"\n   📶 باقی‌مانده: <b>{remain_gb:.2f}</b> / {limit_gb:.2f} گیگ"
                else:
                    line += f"\n   📶 مصرف: <b>{used_gb:.2f}</b> گیگ (نامحدود)"
                if expire_ts:
                    expire_dt = datetime.fromtimestamp(expire_ts)
                    now = datetime.now()
                    if expire_dt > now:
                        delta = expire_dt - now
                        days_left = delta.days
                        hours_left = int(delta.total_seconds() // 3600) % 24
                        line += f"\n   ⏳ مانده: <b>{days_left} روز و {hours_left} ساعت</b>"
                    else:
                        line += "\n   ⏰ <b>منقضی شده</b>"
                st = user_info.get("status", "")
                if st:
                    sm = {"active": "🟢 فعال", "disabled": "🔴 خاموش", "expired": "⏰ منقضی", "limited": "⚠️ محدود"}
                    line += f"\n   {sm.get(st, st)}"
        except Exception as e:
            logger.error(f"service_status {oid}: {e}")
            line += "\n   ⚠️ خطا در دریافت وضعیت"
        lines.append(line)
        lines.append("—————————————")
        buttons.append([InlineKeyboardButton(f"#{oid} جزئیات / تمدید", callback_data=f"order_detail_{oid}")])

    buttons.append([back_button()])
    text_msg = "\n".join(lines)
    if len(text_msg) > 4000:
        text_msg = text_msg[:3990] + "…"
    try:
        await query.edit_message_text(
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await context.bot.send_message(
            user_id, text_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )


async def admin_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    current = await get_faq_text()
    preview = current if len(current) < 3000 else current[:3000] + "…"
    await query.edit_message_text(
        f"❓ <b>سوالات متداول فعلی:</b>\n\n{preview}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"متن کامل جدید را در یک پیام بفرستید تا جایگزین شود.",
        parse_mode=ParseMode.HTML,
    )
    return ADMIN_FAQ


async def admin_set_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = (update.message.text or "").strip()
    if len(new_text) < 10:
        await update.message.reply_text("متن خیلی کوتاه است. دوباره ارسال کنید.")
        return ADMIN_FAQ
    await set_setting("faq", new_text)
    await update.message.reply_text(
        "✅ سوالات متداول به‌روزرسانی شد.",
        reply_markup=main_keyboard(True),
    )
    return ConversationHandler.END

# ---------- QR و آموزش ----------
async def send_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conf = context.user_data.get("last_config")
    if conf:
        qr = generate_qr(conf["subscription_url"])
        await query.message.reply_photo(photo=InputFile(qr, "qr.png"), caption="📷 QR Code کانفیگ شما")
    else:
        # تلاش از دیتابیس
        data = query.data
        if data.startswith("qr_") and data != "qr_test":
            try:
                order_id = int(data.split("_")[1])
                async with aiosqlite.connect("bot.db") as db:
                    async with db.execute(
                        "SELECT config_data FROM orders WHERE id = ? AND user_id = ?",
                        (order_id, query.from_user.id)
                    ) as cur:
                        row = await cur.fetchone()
                if row and row[0]:
                    conf = json.loads(row[0])
                    qr = generate_qr(conf.get("subscription_url", ""))
                    await query.message.reply_photo(photo=InputFile(qr, "qr.png"), caption="📷 QR Code کانفیگ شما")
                    return
            except:
                pass
        await query.answer("اطلاعات یافت نشد", show_alert=True)


async def send_config_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال فایل .txt کانفیگ (لینک ساب + لینک مستقیم)"""
    query = update.callback_query
    await query.answer()
    data = query.data  # dlcfg_123
    try:
        order_id = int(data.split("_")[1])
    except Exception:
        await query.answer("سفارش نامعتبر", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT config_data, config_name, panel_username, server_type, volume_gb
               FROM orders WHERE id = ? AND user_id = ? AND status = 'paid'""",
            (order_id, query.from_user.id)
        ) as cur:
            row = await cur.fetchone()

    if not row or not row[0]:
        await query.answer("اطلاعات کانفیگ یافت نشد", show_alert=True)
        return

    conf_data_str, conf_name, panel_username, server_type, vol = row
    try:
        conf = json.loads(conf_data_str)
    except Exception:
        await query.answer("خطا در خواندن کانفیگ", show_alert=True)
        return

    username = conf.get("username") or panel_username or conf_name or "user"
    sub_url = conf.get("subscription_url") or ""
    config_link = conf.get("config_link") or ""
    expire = conf.get("expire") or "—"
    volume = conf.get("volume") or (f"{vol} گیگ" if vol else "—")
    server_label = {
        "holland": "هلند",
        "multi": "مولتی",
        "unlimited": "نامحدود",
        "custom": "دلخواه",
    }.get(server_type or "", server_type or "—")

    lines = [
        f"# Nexro Config — Order #{order_id}",
        f"# Username: {username}",
        f"# Server: {server_label}",
        f"# Volume: {volume}",
        f"# Expire: {expire}",
        f"#",
        f"# Subscription URL:",
        sub_url,
    ]
    if config_link and config_link != sub_url:
        lines.append("#")
        lines.append("# Direct config link:")
        lines.append(config_link)
    lines.append("")
    content = "\n".join(lines)

    bio = BytesIO(content.encode("utf-8"))
    bio.name = f"config_{username}.txt"
    bio.seek(0)

    await query.message.reply_document(
        document=InputFile(bio, filename=f"config_{username}.txt"),
        caption=(
            f"📄 <b>فایل کانفیگ</b>\n"
            f"👤 <code>{username}</code>\n"
            f"🔗 لینک داخل فایل ذخیره شده است.\n"
            f"می‌توانید فایل را در کلاینت Import کنید یا لینک را کپی کنید."
        ),
        parse_mode=ParseMode.HTML,
    )


async def guide_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 آموزش V2BOX", callback_data="guide_v2box")],
        [InlineKeyboardButton("📱 آموزش V2RAY", callback_data="guide_v2ray")],
        [InlineKeyboardButton("📱 آموزش NPV", callback_data="guide_npv")],
        [back_button()]
    ])
    await query.edit_message_text("📖 برنامه مورد نظر را انتخاب کنید:", reply_markup=kb)

async def guide_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    app = query.data.split("_")[1]

    guides = {
        "v2box": (
            "🔴 <b>V2Box</b>\n\n"
            "1️⃣ 📋 لینک کانفیگ را کپی کن\n"
            "2️⃣ 📱 وارد برنامه V2Box شو\n"
            "3️⃣ ⚙️ برو به بخش Config\n"
            "4️⃣ ➕ روی علامت + بزن\n"
            "5️⃣ 📥 گزینه Import V2Ray config from clipboard را انتخاب کن\n"
            "6️⃣ ✅ کانفیگ اضافه می‌شود\n"
            "7️⃣ 🚀 اسلاید اتصال را روشن کن و وصل شو"
        ),
        "v2ray": (
            "🔵 <b>V2Ray(اندروید)</b>\n\n"
            "1️⃣ 📋 لینک کانفیگ را کپی کن\n"
            "2️⃣ 🔵 برنامه V2RayNG را باز کن\n"
            "3️⃣ ➕ بالا سمت راست روی + بزن\n"
            "4️⃣ 📥 گزینه Import config from clipboard را بزن\n"
            "5️⃣ ✅ کانفیگ اضافه می‌شود\n"
            "6️⃣ ⚡ روی کانفیگ بزن و دکمه اتصال را بزن 🚀"
        ),
        "npv": (
            "📱 <b>NPV</b>\n\n"
            "1️⃣ 📋 لینک ساب (Subscription) را کپی کن\n"
            "2️⃣ 📱 وارد برنامه NPV شو\n"
            "3️⃣ ➕ روی علامت + بزن\n"
            "4️⃣ 🔗 گزینه Add Subscription یا Import Subscription را انتخاب کن\n"
            "5️⃣ 📥 لینک ساب را در کادر مربوطه Paste کن\n"
            "6️⃣ 💾 روی Save / OK بزن تا ساب اضافه شود\n"
            "7️⃣ 🔄 لیست سرورها به‌صورت خودکار نمایش داده می‌شود\n"
            "8️⃣ 🚀 یک سرور را انتخاب کن و دکمه اتصال را روشن کن تا متصل شوی"
        )
    }

    await query.edit_message_text(
        guides.get(app, "آموزش یافت نشد"),
        reply_markup=InlineKeyboardMarkup([
            [back_button("guide_menu")]
        ]),
        parse_mode=ParseMode.HTML
    )

# ==================== پنل مدیریت ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if not await is_admin(uid):
        return

    is_owner = uid == ADMIN_ID
    finance = await can_finance(uid)
    support = await can_support(uid)
    # اگر هر دو خاموش باشد (ادمین قدیمی) دسترسی کامل بده
    if not finance and not support and not is_owner:
        finance = support = True

    buttons = []

    if finance:
        buttons.append([
            InlineKeyboardButton("🇳🇱 تعرفه هلند", callback_data="admin_tariff_holland"),
            InlineKeyboardButton("🌐 تعرفه مولتی", callback_data="admin_tariff_multi"),
            InlineKeyboardButton("💎 تعرفه نامحدود", callback_data="admin_tariff_unlimited")
        ])
        buttons.append([
            InlineKeyboardButton("🎟 کد تخفیف", callback_data="admin_discounts"),
            InlineKeyboardButton("🎁 کد هدیه", callback_data="admin_gift_codes"),
        ])
        buttons.append([
            InlineKeyboardButton("💰 افزایش موجودی", callback_data="admin_add_balance"),
            InlineKeyboardButton("💰 افزایش همه", callback_data="admin_all_balance")
        ])
        buttons.append([
            InlineKeyboardButton("📉 کسر موجودی", callback_data="admin_deduct_balance"),
            InlineKeyboardButton("📉 کسر همه", callback_data="admin_deduct_all")
        ])
        buttons.append([
            InlineKeyboardButton("📊 گزارش مالی", callback_data="admin_stats"),
            InlineKeyboardButton("⏳ سفارشات در انتظار", callback_data="admin_pending_orders")
        ])
        buttons.append([
            InlineKeyboardButton("💳 شارژهای در انتظار", callback_data="admin_pending_charges"),
            InlineKeyboardButton("🔖 جستجوی کد رهگیری", callback_data="admin_search_tracking")
        ])
        buttons.append([
            InlineKeyboardButton("🌐 شارژ پروکسی", callback_data="admin_proxy_charge"),
            InlineKeyboardButton("🗑 مدیریت انبار پروکسی", callback_data="admin_proxy_stock"),
        ])
        buttons.append([
            InlineKeyboardButton("💰 تعرفه پروکسی‌ها", callback_data="admin_proxy_tariffs"),
            InlineKeyboardButton("🔖 جستجوی کد رهگیری پروکسی", callback_data="admin_search_proxy_tracking"),
        ])

    if support:
        buttons.append([
            InlineKeyboardButton("🚫 مسدود کردن", callback_data="admin_ban"),
            InlineKeyboardButton("✅ رفع مسدودیت", callback_data="admin_unban")
        ])
        buttons.append([
            InlineKeyboardButton("⚠️ اخطار به کاربر", callback_data="admin_warn_user"),
            InlineKeyboardButton("🗑 حذف اخطار", callback_data="admin_clear_warn")
        ])
        buttons.append([
            InlineKeyboardButton("✉️ پیام به کاربر", callback_data="admin_msg_user"),
            InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user")
        ])
        buttons.append([
            InlineKeyboardButton("👥 نمایش تمام کاربران", callback_data="admin_all_users"),
            InlineKeyboardButton("🎫 تیکت‌های باز", callback_data="admin_open_tickets")
        ])
        buttons.append([
            InlineKeyboardButton("🟢 کاربران فعال", callback_data="admin_active_users"),
            InlineKeyboardButton("🧪 شارژ تست", callback_data="admin_test_recharge")
        ])
        buttons.append([
            InlineKeyboardButton("🔎 جستجوی کانفیگ پنل", callback_data="admin_panel_cfg_search"),
            InlineKeyboardButton("🗑 حذف کانفیگ پنل", callback_data="admin_panel_cfg_delete"),
        ])
        buttons.append([
            InlineKeyboardButton("🧩 سوالات آماده پشتیبانی", callback_data="admin_manage_sqa"),
        ])

    # تنظیمات عمومی / پیام همگانی — برای مالی یا مالک
    if finance or is_owner:
        buttons.append([
            InlineKeyboardButton("✉️ خوش‌آمدگویی", callback_data="admin_welcome"),
            InlineKeyboardButton("📜 قوانین", callback_data="admin_rules")
        ])
        buttons.append([
            InlineKeyboardButton("❓ تغییر سوالات متداول", callback_data="admin_faq")
        ])
        buttons.append([
            InlineKeyboardButton("📢 پیام به همه", callback_data="admin_broadcast"),
            InlineKeyboardButton("📣 پیام به تمام ادمین‌ها", callback_data="admin_broadcast_admins")
        ])
        buttons.append([InlineKeyboardButton("✉️ پیام به ادمین", callback_data="admin_msg_admin")])
        buttons.append([
            InlineKeyboardButton("💾 بک‌آپ دیتابیس", callback_data="admin_backup"),
            InlineKeyboardButton("⚙️ تنظیمات عمومی", callback_data="admin_settings")
        ])
        buttons.append([InlineKeyboardButton("🧪 تغییر حجم اکانت تست", callback_data="admin_set_test_volume")])

    if is_owner or await can_add_admin(uid) or await can_toggle_admin(uid):
        buttons.append([
            InlineKeyboardButton("🛡 مدیریت ادمین‌ها", callback_data="admin_manage_admins"),
            InlineKeyboardButton("🔑 دسترسی دادن به ادمین", callback_data="admin_grant_perms")
        ])

    buttons.append([back_button()])
    role_hint = ""
    if is_owner:
        role_hint = "\n🔒 نقش: مالک (دسترسی کامل)"
    elif finance and support:
        role_hint = "\n🔑 نقش: ادمین کامل"
    elif finance:
        role_hint = "\n💰 نقش: فقط مالی"
    elif support:
        role_hint = "\n💬 نقش: فقط پشتیبانی"

    # موجودی کل کیف پول + انبار پروکسی
    total_balance = 0
    users_with_balance = 0
    try:
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute("SELECT COALESCE(SUM(balance), 0) FROM users") as cur:
                total_balance = (await cur.fetchone())[0] or 0
            async with db.execute("SELECT COUNT(*) FROM users WHERE balance > 0") as cur:
                users_with_balance = (await cur.fetchone())[0] or 0
    except Exception as e:
        logger.error(f"admin_panel total_balance: {e}")

    stock_lines = []
    try:
        for loc_key, loc_info in PROXY_LOCATIONS.items():
            cnt = await get_proxy_stock_count(loc_key)
            warn = " ⚠️ کم" if cnt < PROXY_LOW_STOCK_THRESHOLD else ""
            stock_lines.append(f"  {loc_info['name']}: <b>{cnt}</b>{warn}")
    except Exception as e:
        logger.error(f"admin_panel proxy stock: {e}")
        stock_lines = ["  —"]

    stock_text = "\n".join(stock_lines) if stock_lines else "  —"
    await query.edit_message_text(
        f"🛠 پنل مدیریت{role_hint}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>موجودی کل کیف پول‌ها:</b> <b>{total_balance:,}</b> تومان\n"
        f"👥 کاربران دارای موجودی: <b>{users_with_balance:,}</b> نفر\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>موجودی انبار پروکسی</b>\n"
        f"{stock_text}\n"
        f"(آستانه هشدار: {PROXY_LOW_STOCK_THRESHOLD})",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def admin_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست تمام کاربران با اطلاعات کامل (صفحه‌بندی‌شده)"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    page = 0
    if query.data and query.data.startswith("admin_all_users_page_"):
        try:
            page = int(query.data.split("_")[-1])
        except Exception:
            page = 0
    if page < 0:
        page = 0

    PAGE_SIZE = 15
    offset = page * PAGE_SIZE

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]

        async with db.execute(
            """SELECT user_id, username, full_name, balance, is_banned, join_date,
                      test_used, referral_code, warnings
               FROM users
               ORDER BY join_date DESC
               LIMIT ? OFFSET ?""",
            (PAGE_SIZE, offset)
        ) as cur:
            rows = await cur.fetchall()

    if total == 0:
        await query.edit_message_text(
            "👥 هیچ کاربری ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
        offset = page * PAGE_SIZE
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT user_id, username, full_name, balance, is_banned, join_date,
                          test_used, referral_code, warnings
                   FROM users ORDER BY join_date DESC LIMIT ? OFFSET ?""",
                (PAGE_SIZE, offset)
            ) as cur:
                rows = await cur.fetchall()

    text_msg = (
        f"👥 <b>لیست تمام کاربران</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 تعداد کل: <b>{total:,}</b> نفر\n"
        f"📄 صفحه <b>{page + 1}</b> از <b>{total_pages}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"روی هر کاربر بزنید تا خریدها و کد رهگیری را ببینید.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    buttons = []
    for uid, username, full_name, balance, is_banned, join_date, test_used, ref_code, warnings in rows:
        status = "🚫" if is_banned else "✅"
        join = (join_date[:10] if join_date else "—")
        warn = warnings or 0
        uname = f"@{username}" if username else "—"
        name = (full_name or "—")[:20]
        text_msg += (
            f"{status} <code>{uid}</code> | {name}\n"
            f"   {uname} | 💰 {balance:,} | ⚠️ {warn}/3 | 📅 {join}\n"
            f"—————————————\n"
        )
        label = f"{status} {name} | {uid}"[:40]
        buttons.append([InlineKeyboardButton(label, callback_data=f"admin_user_orders_{uid}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_all_users_page_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"admin_all_users_page_{page + 1}"))
    buttons.append(nav)

    # پرش سریع به صفحات
    jump = []
    if total_pages > 2:
        jump.append(InlineKeyboardButton("⏮ اول", callback_data="admin_all_users_page_0"))
        jump.append(InlineKeyboardButton("آخر ⏭", callback_data=f"admin_all_users_page_{total_pages - 1}"))
        buttons.append(jump)

    buttons.append([InlineKeyboardButton("📥 دانلود لیست کامل همه کاربران", callback_data="admin_export_all_users")])
    buttons.append([back_button("admin_panel")])

    if len(text_msg) > 3500:
        text_msg = text_msg[:3400] + "\n\n... (ادامه در صفحات بعدی)"

    try:
        await query.edit_message_text(
            text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text_msg,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )


async def admin_export_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال فایل متنی شامل همه کاربران ربات"""
    query = update.callback_query
    await query.answer("در حال آماده‌سازی فایل...")
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT user_id, username, full_name, balance, is_banned, join_date,
                      test_used, referral_code, warnings
               FROM users
               ORDER BY join_date DESC"""
        ) as cur:
            rows = await cur.fetchall()

    lines = [
        "لیست تمام کاربران ربات",
        f"تاریخ خروجی: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"تعداد کل: {len(rows)}",
        "=" * 60,
    ]
    for i, (uid, username, full_name, balance, is_banned, join_date, test_used, ref_code, warnings) in enumerate(rows, 1):
        status = "BANNED" if is_banned else "OK"
        uname = f"@{username}" if username else "-"
        join = (join_date or "")[:19].replace("T", " ")
        lines.append(
            f"{i}. ID={uid} | {full_name or '-'} | {uname} | "
            f"balance={balance} | status={status} | warn={warnings or 0} | "
            f"test={test_used or 0} | join={join} | ref={ref_code or '-'}"
        )

    content = "\n".join(lines)
    bio = io.BytesIO(content.encode("utf-8"))
    bio.name = f"users_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    try:
        await context.bot.send_document(
            chat_id=query.from_user.id,
            document=InputFile(bio, filename=bio.name),
            caption=f"📥 لیست کامل کاربران\n👥 تعداد: {len(rows):,} نفر",
        )
        await query.answer("فایل ارسال شد", show_alert=False)
    except Exception as e:
        logger.error(f"export users: {e}")
        await query.answer(f"خطا در ارسال فایل: {e}", show_alert=True)


async def admin_user_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تمام خریدهای یک کاربر همراه با کد رهگیری"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    try:
        uid = int(query.data.split("_")[-1])
    except:
        await query.answer("خطا در شناسه کاربر", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT full_name, username, balance FROM users WHERE user_id = ?", (uid,)
        ) as cur:
            user_row = await cur.fetchone()

        async with db.execute(
            """SELECT id, server_type, volume_gb, final_price, status, config_name,
                      tracking_code, created_at
               FROM orders
               WHERE user_id = ?
               ORDER BY id DESC
               LIMIT 30""",
            (uid,)
        ) as cur:
            orders = await cur.fetchall()

        # برای سفارش‌هایی که کد رهگیری ندارند، الان بساز و ذخیره کن
        fixed_orders = []
        for row in orders:
            oid, server, vol, price, status, conf_name, tracking, created = row
            if not tracking:
                tracking = generate_tracking_code()
                await db.execute(
                    "UPDATE orders SET tracking_code = ? WHERE id = ?",
                    (tracking, oid)
                )
            fixed_orders.append((oid, server, vol, price, status, conf_name, tracking, created))
        if orders:
            await db.commit()
        orders = fixed_orders

    if not user_row:
        await query.edit_message_text(
            "❌ کاربر یافت نشد.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_all_users")]])
        )
        return

    full_name, username, balance = user_row
    uname = f"@{username}" if username else "—"
    price_safe = balance if balance is not None else 0

    text = (
        f"📦 <b>خریدهای کاربر</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{uid}</code>\n"
        f"📛 {full_name or '—'}\n"
        f"🔗 {uname}\n"
        f"💰 موجودی: <b>{price_safe:,}</b> تومان\n"
        f"📊 تعداد سفارش: <b>{len(orders)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    if not orders:
        text += "\nاین کاربر هنوز هیچ سفارشی ثبت نکرده است."
    else:
        for oid, server, vol, price, status, conf_name, tracking, created in orders:
            if server == "holland":
                plan = f"هلند {vol} گیگ"
            elif server == "unlimited":
                plan = f"نامحدود {vol} ماهه"
            elif server == "custom":
                plan = f"دلخواه {vol} گیگ"
            else:
                plan = f"مولتی {vol} گیگ"
            st_map = {
                "paid": "✅ پرداخت‌شده",
                "pending": "⏳ در انتظار",
                "rejected": "🚫 رد شده",
                "expired": "⏰ منقضی",
            }
            st = st_map.get(status, f"❓ {status}")
            date = created[:16].replace("T", " ") if created else "—"
            amount = price if price is not None else 0
            text += (
                f"\n{st}\n"
                f"🔢 سفارش: <b>#{oid}</b>\n"
                f"📦 پلن: {plan}\n"
                f"💰 مبلغ: <b>{amount:,}</b> تومان\n"
                f"👤 کانفیگ: <code>{conf_name or '—'}</code>\n"
                f"🔖 کد رهگیری: <code>{tracking or 'ندارد'}</code>\n"
                f"🕐 تاریخ: {date}\n"
                f"—————————————"
            )

    if len(text) > 4000:
        text = text[:3900] + "\n\n... (فقط ۳۰ سفارش اخیر نمایش داده شد)"

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت به لیست کاربران", callback_data="admin_all_users")],
                [back_button("admin_panel")]
            ]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"admin_user_orders display error: {e}")
        # fallback بدون HTML در صورت خطا
        await query.edit_message_text(
            text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت به لیست کاربران", callback_data="admin_all_users")],
                [back_button("admin_panel")]
            ])
        )


async def admin_search_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجوی سفارش با کد رهگیری"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🔖 <b>جستجوی کد رهگیری</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد رهگیری سفارش را وارد کنید:\n"
        "مثال: <code>A7K9M2X4P1</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
    )
    return ADMIN_TRACKING_SEARCH


async def admin_do_search_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش کد رهگیری و نمایش وضعیت سفارش (یا پروکسی اگر فلگ ست شده)"""
    if context.user_data.pop("search_proxy_tracking", False):
        return await admin_do_search_proxy_tracking(update, context)
    code = update.message.text.strip().upper()
    if len(code) < 4:
        await update.message.reply_text(
            "❌ کد رهگیری نامعتبر است. دوباره وارد کنید:",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return ADMIN_TRACKING_SEARCH

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT o.id, o.user_id, o.server_type, o.volume_gb, o.final_price, o.status,
                      o.config_name, o.tracking_code, o.created_at,
                      u.full_name, u.username
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.user_id
               WHERE o.tracking_code = ?
               LIMIT 1""",
            (code,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await update.message.reply_text(
            f"❌ سفارشی با کد رهگیری <code>{code}</code> یافت نشد.\n"
            f"کد را دوباره وارد کنید یا از پنل خارج شوید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔖 جستجوی مجدد", callback_data="admin_search_tracking")],
                [back_button("admin_panel")]
            ])
        )
        return ConversationHandler.END

    oid, uid, server, vol, price, status, conf_name, tracking, created, full_name, username = row

    if server == "holland":
        plan = f"هلند {vol} گیگ"
    elif server == "unlimited":
        plan = f"نامحدود {vol} ماهه"
    elif server == "custom":
        plan = f"دلخواه {vol} گیگ"
    else:
        plan = f"مولتی {vol} گیگ"

    date = created[:16].replace("T", " ") if created else "—"
    uname = f"@{username}" if username else "—"

    text = (
        f"🔖 <b>نتیجه جستجوی کد رهگیری</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔖 کد: <code>{tracking}</code>\n"
        f"🔢 شماره سفارش: <b>#{oid}</b>\n"
        f"📦 پلن: {plan}\n"
        f"💰 مبلغ: <b>{price:,}</b> تومان\n"
        f"👤 کانفیگ: <code>{conf_name or '—'}</code>\n"
        f"🕐 تاریخ: {date}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 کاربر: <code>{uid}</code>\n"
        f"📛 {full_name or '—'}\n"
        f"🔗 {uname}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    buttons = []

    if status == "paid":
        text += "📌 وضعیت: <b>✅ پرداخت / تحویل شده</b>\nاین سفارش قبلاً تأیید و تحویل داده شده است."
        buttons.append([InlineKeyboardButton("🔖 جستجوی کد دیگر", callback_data="admin_search_tracking")])
        buttons.append([back_button("admin_panel")])
    elif status == "rejected":
        text += "📌 وضعیت: <b>🚫 رد شده</b>\nاین سفارش توسط ادمین رد شده است."
        buttons.append([InlineKeyboardButton("🔖 جستجوی کد دیگر", callback_data="admin_search_tracking")])
        buttons.append([back_button("admin_panel")])
    elif status == "expired":
        text += "📌 وضعیت: <b>⏰ منقضی شده</b>"
        buttons.append([InlineKeyboardButton("🔖 جستجوی کد دیگر", callback_data="admin_search_tracking")])
        buttons.append([back_button("admin_panel")])
    elif status == "pending":
        text += (
            "📌 وضعیت: <b>⏳ در انتظار تأیید</b>\n\n"
            "می‌توانید سفارش را تأیید یا رد کنید:"
        )
        buttons.append([
            InlineKeyboardButton("✅ تأیید سفارش", callback_data=f"approve_order_{oid}"),
            InlineKeyboardButton("❌ رد سفارش", callback_data=f"reject_order_{oid}")
        ])
        buttons.append([InlineKeyboardButton("🔖 جستجوی کد دیگر", callback_data="admin_search_tracking")])
        buttons.append([back_button("admin_panel")])
    else:
        text += f"📌 وضعیت: <b>{status}</b>"
        buttons.append([back_button("admin_panel")])

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END


async def admin_open_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT t.id, t.user_id, t.message, t.created_at, u.full_name, u.username
               FROM tickets t
               LEFT JOIN users u ON t.user_id = u.user_id
               WHERE t.status = 'open'
               ORDER BY t.id DESC LIMIT 20"""
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "✅ هیچ تیکت بازی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return

    text = "🎫 <b>تیکت‌های باز</b>\n━━━━━━━━━━━━━━━━━━\n"
    buttons = []
    for tid, uid, msg, created, full_name, username in rows:
        text += (
            f"#{tid} | {full_name or '—'} (@{username or '—'})\n"
            f"<code>{uid}</code>\n"
            f"📝 {msg[:60]}{'...' if len(msg) > 60 else ''}\n"
            f"🕐 {created[:16].replace('T', ' ') if created else '—'}\n"
            f"—————————————\n"
        )
        buttons.append([InlineKeyboardButton(f"✍️ پاسخ #{tid}", callback_data=f"reply_ticket_{tid}")])

    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

# ---------- مدیریت ادمین‌ها ----------
async def admin_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    actor_id = query.from_user.id
    has_toggle = await can_toggle_admin(actor_id)
    has_add = await can_add_admin(actor_id)

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT a.user_id, a.is_active, a.added_at, u.full_name, u.username
               FROM admins a
               LEFT JOIN users u ON a.user_id = u.user_id
               ORDER BY a.added_at"""
        ) as cur:
            rows = await cur.fetchall()

    buttons = []
    if not rows:
        text = (
            "🛡 <b>مدیریت ادمین‌ها</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ادمینی وجود ندارد.\n"
        )
        if has_add:
            text += "برای افزودن ادمین از دکمه «اضافه کردن ادمین جدید» استفاده کنید."
    else:
        text = "🛡 <b>لیست ادمین‌ها</b>\n━━━━━━━━━━━━━━━━━━\n"
        for uid, active, added_at, full_name, username in rows:
            status = "🟢 فعال" if active else "🔴 غیرفعال"
            name = full_name or "—"
            uname = f"@{username}" if username else "—"
            is_main = " (اصلی)" if uid == ADMIN_ID else ""
            text += (
                f"👤 {name}{is_main}\n"
                f"🔗 {uname} | <code>{uid}</code>\n"
                f"📌 {status}\n"
                f"—————————————\n"
            )
            if uid == ADMIN_ID:
                buttons.append([
                    InlineKeyboardButton(
                        f"🔒 ادمین اصلی — {name}",
                        callback_data=f"toggle_admin_{uid}"
                    )
                ])
            else:
                if has_toggle:
                    btn_label = "✅ فعال" if active else "❌ غیرفعال"
                    buttons.append([
                        InlineKeyboardButton(
                            f"{btn_label} — {name or uid}",
                            callback_data=f"toggle_admin_{uid}"
                        )
                    ])
                else:
                    buttons.append([
                        InlineKeyboardButton(
                            f"📌 {status} — {name or uid}",
                            callback_data="noop"
                        )
                    ])

    if has_add:
        buttons.append([InlineKeyboardButton("➕ اضافه کردن ادمین جدید", callback_data="admin_add_admin")])
    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    if not await can_add_admin(query.from_user.id):
        await query.answer("❌ شما اجازه اضافه کردن ادمین جدید را ندارید.", show_alert=True)
        return
    await query.edit_message_text(
        "🛡 <b>افزودن ادمین جدید</b>\n\n"
        "آیدی عددی کاربر را بفرستید:",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_ADD_ADMIN_ID

async def admin_receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ آیدی معتبر نیست. فقط عدد وارد کنید:")
        return ADMIN_ADD_ADMIN_ID

    if uid == ADMIN_ID:
        await update.message.reply_text(
            "این کاربر ادمین اصلی است و از قبل دسترسی دارد.",
            reply_markup=main_keyboard(True)
        )
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        # بررسی وجود در جدول admins
        async with db.execute("SELECT is_active FROM admins WHERE user_id = ?", (uid,)) as cur:
            existing = await cur.fetchone()

        # اطلاعات کاربر از جدول users
        async with db.execute(
            "SELECT full_name, username, balance, is_banned, join_date FROM users WHERE user_id = ?",
            (uid,)
        ) as cur:
            user_row = await cur.fetchone()

    if not user_row:
        await update.message.reply_text(
            "❌ کاربر مورد نظر در ربات یافت نشد.\n"
            "کاربر باید حداقل یک بار ربات را استارت کرده باشد.\n"
            "آیدی را دوباره وارد کنید یا /start بزنید:",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_manage_admins")]])
        )
        return ADMIN_ADD_ADMIN_ID

    full_name, username, balance, is_banned, join_date = user_row
    if existing:
        status = "فعال" if existing[0] else "غیرفعال"
        await update.message.reply_text(
            f"این کاربر از قبل در لیست ادمین‌ها است (وضعیت: {status}).",
            reply_markup=main_keyboard(True)
        )
        return ConversationHandler.END

    # اضافه کردن به عنوان ادمین فعال
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO admins (user_id, is_active, added_at, added_by) VALUES (?, 1, ?, ?)",
            (uid, datetime.now().isoformat(), update.effective_user.id)
        )
        await db.commit()

    join = join_date[:16].replace("T", " ") if join_date else "—"
    banned_text = "🚫 مسدود" if is_banned else "✅ فعال"

    info_text = (
        f"✅ <b>کاربر مورد نظر یافت شد و به عنوان ادمین اضافه شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"📛 نام: {full_name or '—'}\n"
        f"🔗 یوزرنیم: @{username or '—'}\n"
        f"💰 موجودی: {balance:,} تومان\n"
        f"📌 وضعیت حساب: {banned_text}\n"
        f"📅 عضویت: {join}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛡 دسترسی ادمین برای این کاربر <b>فعال</b> شد."
    )
    await update.message.reply_text(
        info_text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )

    # پیام قشنگ به کاربر جدید
    nice_msg = (
        "🎉 <b>تبریک!</b>\n\n"
        "مدیریت ربات شما را به عنوان <b>ادمین</b> انتخاب کرد.\n\n"
        "از این لحظه می‌توانید از طریق منوی اصلی وارد "
        "<b>🛠 پنل مدیریت</b> شوید و به امکانات مدیریتی دسترسی داشته باشید.\n\n"
        "با مسئولیت‌پذیری و دقت از این دسترسی استفاده کنید.\n"
        "موفق باشید 🌟"
    )
    try:
        await context.bot.send_message(uid, nice_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Failed to notify new admin {uid}: {e}")

    return ConversationHandler.END

async def toggle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    uid = int(query.data.split("_")[-1])
    actor = query.from_user

    # فقط مالک ربات اجازه فعال/غیرفعال کردن ادمین را دارد
    if actor.id != ADMIN_ID:
        await query.answer(
            "⛔ فقط مالک می‌تواند ادمین را تغییر دهد.\nبرای این تلاش یک اخطار برای شما ارسال شد.",
            show_alert=True,
        )
        uname = f"@{actor.username}" if actor.username else "بدون یوزرنیم"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # اطلاعات هدف
        target_name = "—"
        target_uname = "—"
        try:
            async with aiosqlite.connect("bot.db") as db:
                async with db.execute(
                    "SELECT full_name, username FROM users WHERE user_id = ?", (uid,)
                ) as cur:
                    trow = await cur.fetchone()
                if trow:
                    target_name = trow[0] or "—"
                    target_uname = f"@{trow[1]}" if trow[1] else "بدون یوزرنیم"
        except Exception:
            pass

        if uid == ADMIN_ID:
            target_label = "ادمین اصلی (مالک)"
        else:
            target_label = f"ادمین {uid} — {target_name} ({target_uname})"

        # ثبت اخطار رسمی (هر تلاش = ۱ اخطار؛ با ۳ اخطار مسدود می‌شود)
        reason = (
            "تلاش برای فعال/غیرفعال کردن ادمین بدون مجوز مالک.\n"
            f"هدف: {target_label}\n"
            f"زمان: {now_str}\n\n"
            "⛔️ فقط مالک ربات اجازه تغییر وضعیت ادمین‌ها را دارد.\n"
            "لطفاً از تکرار این کار خودداری کنید."
        )
        warnings_count, was_banned = await issue_warning(
            context.bot, actor.id, reason=reason, issued_by=ADMIN_ID
        )

        # پیام تکمیلی قشنگ به ادمین متخلف
        try:
            extra = (
                "⚠️ <b>توضیح اخطار</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "شما تلاش کردید وضعیت یک ادمین را تغییر دهید.\n\n"
                "این دسترسی <b>فقط مخصوص مالک ربات</b> است.\n"
                f"🎯 هدف تلاش: <b>{target_label}</b>\n"
                f"🕐 زمان: <b>{now_str}</b>\n"
                f"📊 اخطارهای شما: <b>{warnings_count}</b> از ۳\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            if was_banned:
                extra += (
                    "🚫 به دلیل رسیدن به <b>۳ اخطار</b>، حساب شما طبق قوانین مسدود شد.\n"
                    "در صورت اعتراض با پشتیبانی در ارتباط باشید."
                )
            else:
                remain = 3 - warnings_count
                extra += (
                    f"❗ با <b>{remain}</b> اخطار دیگر حساب شما به‌طور کامل مسدود می‌شود.\n"
                    "لطفاً حدود دسترسی خود را رعایت کنید 🙏"
                )
            await context.bot.send_message(actor.id, extra, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"send detail warn to admin {actor.id}: {e}")

        # اعلان کامل به مالک
        try:
            ban_line = (
                "🚫 <b>حساب متخلف به‌خاطر ۳ اخطار مسدود شد.</b>"
                if was_banned
                else f"📊 اخطار فعلی متخلف: <b>{warnings_count}</b> از ۳"
            )
            await context.bot.send_message(
                ADMIN_ID,
                f"⚠️ <b>هشدار امنیتی — تلاش برای تغییر ادمین</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"یک ادمین (غیر از مالک) سعی کرد وضعیت ادمین دیگری را تغییر دهد.\n\n"
                f"👤 <b>ادمین متخلف:</b>\n"
                f"• نام: {actor.full_name or '—'}\n"
                f"• یوزرنیم: {uname}\n"
                f"• آیدی: <code>{actor.id}</code>\n\n"
                f"🎯 <b>هدف:</b> {target_label}\n"
                f"🕐 تاریخ و ساعت: <b>{now_str}</b>\n"
                f"{ban_line}\n\n"
                f"❌ عملیات متوقف شد و اخطار رسمی ثبت گردید.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"notify main admin error: {e}")

        await log_admin_action(
            actor.id,
            "unauthorized_toggle_admin",
            target_id=uid,
            detail=f"at={now_str}, warnings={warnings_count}, banned={int(was_banned)}",
        )
        return

    if uid == ADMIN_ID:
        await query.answer("🔒 ادمین اصلی (مالک) قابل تغییر نیست.", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("ادمین یافت نشد", show_alert=True)
            return
        new_status = 0 if row[0] else 1
        await db.execute("UPDATE admins SET is_active = ? WHERE user_id = ?", (new_status, uid))
        await db.commit()

    if new_status:
        await query.answer("✅ ادمین فعال شد", show_alert=True)
    else:
        await query.answer("❌ ادمین غیرفعال شد", show_alert=True)

    await log_admin_action(
        actor.id,
        "toggle_admin",
        target_id=uid,
        detail=f"new_status={new_status}",
    )
    # رفرش لیست
    await admin_manage_admins(update, context)


# ---------- دسترسی دادن به ادمین ----------
async def admin_grant_perms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فقط مالک می‌تواند دسترسی‌ها را تنظیم کند"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک ربات می‌تواند دسترسی ادمین‌ها را تنظیم کند.", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT a.user_id, a.is_active, a.can_add_admin, a.can_toggle_admin,
                      a.can_finance, a.can_support, u.full_name, u.username
               FROM admins a
               LEFT JOIN users u ON a.user_id = u.user_id
               WHERE a.user_id != ?
               ORDER BY a.added_at""",
            (ADMIN_ID,)
        ) as cur:
            rows = await cur.fetchall()

    buttons = []
    if not rows:
        text = (
            "🔑 <b>دسترسی دادن به ادمین</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ادمینی (به جز مالک) وجود ندارد.\n"
            "ابتدا از بخش مدیریت ادمین‌ها، ادمین جدید اضافه کنید."
        )
    else:
        text = (
            "🔑 <b>دسترسی دادن به ادمین</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ادمین مورد نظر را انتخاب کنید تا دسترسی‌های او را تنظیم کنید:\n\n"
            "💰 مالی = سفارش، شارژ، موجودی، تعرفه، پروکسی\n"
            "💬 پشتیبانی = بن، اخطار، تیکت، جستجو، پیام"
        )
        for row in rows:
            uid, active = row[0], row[1]
            full_name, username = row[6], row[7]
            name = full_name or str(uid)
            status = "🟢" if active else "🔴"
            buttons.append([
                InlineKeyboardButton(
                    f"{status} {name} | {uid}",
                    callback_data=f"grant_perm_user_{uid}"
                )
            ])

    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def admin_grant_perm_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not context.user_data.get("_skip_answer"):
        await query.answer()
    context.user_data.pop("_skip_answer", None)

    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک.", show_alert=True)
        return

    uid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT a.is_active, a.can_add_admin, a.can_toggle_admin,
                      a.can_finance, a.can_support, u.full_name, u.username
               FROM admins a
               LEFT JOIN users u ON a.user_id = u.user_id
               WHERE a.user_id = ?""",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await query.answer("ادمین یافت نشد", show_alert=True)
        return

    is_active, can_add, can_toggle, can_fin, can_sup, full_name, username = row
    name = full_name or str(uid)
    uname = f"@{username}" if username else "—"

    can_add = bool(can_add)
    can_toggle = bool(can_toggle)
    can_fin = True if can_fin is None else bool(can_fin)
    can_sup = True if can_sup is None else bool(can_sup)

    add_label = "✅ فعال" if can_add else "❌ غیرفعال"
    toggle_label = "✅ فعال" if can_toggle else "❌ غیرفعال"
    fin_label = "✅ فعال" if can_fin else "❌ غیرفعال"
    sup_label = "✅ فعال" if can_sup else "❌ غیرفعال"

    text = (
        f"🔑 <b>تنظیم دسترسی ادمین</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 {name}\n"
        f"🔗 {uname} | <code>{uid}</code>\n"
        f"📌 وضعیت ادمین: {'🟢 فعال' if is_active else '🔴 غیرفعال'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"با دکمه‌های زیر دسترسی‌ها را فعال/غیرفعال کنید:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"💰 دسترسی مالی: {fin_label}",
            callback_data=f"toggle_perm_finance_{uid}"
        )],
        [InlineKeyboardButton(
            f"💬 دسترسی پشتیبانی: {sup_label}",
            callback_data=f"toggle_perm_support_{uid}"
        )],
        [InlineKeyboardButton(
            f"➕ اضافه کردن ادمین جدید: {add_label}",
            callback_data=f"toggle_perm_add_{uid}"
        )],
        [InlineKeyboardButton(
            f"🔄 فعال/غیرفعال کردن ادمین: {toggle_label}",
            callback_data=f"toggle_perm_toggle_{uid}"
        )],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_grant_perms")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def toggle_perm_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک.", show_alert=True)
        return

    uid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT can_add_admin FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("یافت نشد", show_alert=True)
            return
        new_val = 0 if row[0] else 1
        await db.execute("UPDATE admins SET can_add_admin = ? WHERE user_id = ?", (new_val, uid))
        await db.commit()

    await query.answer("✅ فعال شد" if new_val else "❌ غیرفعال شد", show_alert=True)
    context.user_data["_skip_answer"] = True
    query.data = f"grant_perm_user_{uid}"
    await admin_grant_perm_user(update, context)


async def toggle_perm_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک.", show_alert=True)
        return

    uid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT can_toggle_admin FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("یافت نشد", show_alert=True)
            return
        new_val = 0 if row[0] else 1
        await db.execute("UPDATE admins SET can_toggle_admin = ? WHERE user_id = ?", (new_val, uid))
        await db.commit()

    await query.answer("✅ فعال شد" if new_val else "❌ غیرفعال شد", show_alert=True)
    context.user_data["_skip_answer"] = True
    query.data = f"grant_perm_user_{uid}"
    await admin_grant_perm_user(update, context)


async def toggle_perm_finance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک.", show_alert=True)
        return
    uid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT can_finance FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("یافت نشد", show_alert=True)
            return
        current = 1 if row[0] is None else row[0]
        new_val = 0 if current else 1
        await db.execute("UPDATE admins SET can_finance = ? WHERE user_id = ?", (new_val, uid))
        await db.commit()
    await query.answer("✅ فعال شد" if new_val else "❌ غیرفعال شد", show_alert=True)
    context.user_data["_skip_answer"] = True
    query.data = f"grant_perm_user_{uid}"
    await admin_grant_perm_user(update, context)


async def toggle_perm_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ فقط مالک.", show_alert=True)
        return
    uid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT can_support FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("یافت نشد", show_alert=True)
            return
        current = 1 if row[0] is None else row[0]
        new_val = 0 if current else 1
        await db.execute("UPDATE admins SET can_support = ? WHERE user_id = ?", (new_val, uid))
        await db.commit()
    await query.answer("✅ فعال شد" if new_val else "❌ غیرفعال شد", show_alert=True)
    context.user_data["_skip_answer"] = True
    query.data = f"grant_perm_user_{uid}"
    await admin_grant_perm_user(update, context)



# ---------- جستجوی کد رهگیری پروکسی ----------
async def admin_search_proxy_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🔖 <b>جستجوی کد رهگیری پروکسی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد رهگیری پروکسی را وارد کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
    )
    context.user_data["search_proxy_tracking"] = True
    return ADMIN_TRACKING_SEARCH


async def admin_do_search_proxy_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجو در جدول proxy_orders بر اساس tracking_code"""
    code = update.message.text.strip().upper()
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, user_id, location, quantity, days, unit_price, days_price, final_price,
                      status, proxies_data, tracking_code, created_at
               FROM proxy_orders WHERE tracking_code = ?""",
            (code,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await update.message.reply_text(
            f"❌ کد رهگیری <code>{code}</code> یافت نشد.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔖 جستجوی مجدد", callback_data="admin_search_proxy_tracking")],
                [back_button("admin_panel")]
            ])
        )
        return ConversationHandler.END

    (oid, uid, loc, qty, days, unit_p, days_p, final, status, proxies_data, tracking, created) = row
    loc_name = PROXY_LOCATIONS.get(loc, {}).get("name", loc)
    status_map = {"pending": "⏳ در انتظار", "paid": "✅ تحویل‌شده", "rejected": "❌ رد شده"}
    status_text = status_map.get(status, status)

    # اطلاعات کاربر
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT full_name, username FROM users WHERE user_id = ?", (uid,)
        ) as cur:
            urow = await cur.fetchone()
    full_name = urow[0] if urow else "—"
    username = urow[1] if urow else None

    proxies_preview = ""
    if proxies_data:
        try:
            plist = json.loads(proxies_data) if isinstance(proxies_data, str) else proxies_data
            if isinstance(plist, list):
                proxies_preview = "\n".join([f"<code>{p}</code>" for p in plist[:5]])
                if len(plist) > 5:
                    proxies_preview += f"\n... و {len(plist)-5} مورد دیگر"
            else:
                proxies_preview = f"<code>{proxies_data[:200]}</code>"
        except:
            proxies_preview = str(proxies_data)[:200]

    text = (
        f"🔖 <b>نتیجه جستجوی کد رهگیری پروکسی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔢 شماره سفارش: <b>#{oid}</b>\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"📌 وضعیت: {status_text}\n"
        f"📍 لوکیشن: {loc_name}\n"
        f"🔢 تعداد: <b>{qty}</b>\n"
        f"📅 مدت: <b>{days}</b> روز\n"
        f"💰 مبلغ نهایی: <b>{final:,}</b> تومان\n"
        f"🕐 زمان: {created[:16].replace('T', ' ') if created else '—'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 کاربر: {full_name or '—'} (@{username or '—'})\n"
        f"🆔 <code>{uid}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 پروکسی‌ها:\n{proxies_preview or '—'}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔖 جستجوی کد دیگر", callback_data="admin_search_proxy_tracking")],
        [back_button("admin_panel")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ConversationHandler.END



async def admin_view_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آخرین لاگ اقدامات ادمین"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT admin_id, action, target_id, detail, created_at
               FROM admin_logs ORDER BY id DESC LIMIT 25"""
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        body = "هنوز لاگی ثبت نشده است."
    else:
        lines = []
        for admin_id, action, target_id, detail, created in rows:
            date = (created or "")[:16].replace("T", " ")
            det = (detail or "")[:60]
            lines.append(
                f"• <code>{date}</code> | ادمین <code>{admin_id}</code>\n"
                f"  {action} → {target_id or '—'} {det}"
            )
        body = "\n".join(lines)

    text_msg = (
        f"📋 <b>لاگ اقدامات ادمین</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"آخرین {len(rows)} مورد"
    )
    await query.edit_message_text(
        text_msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 گزارش مالی", callback_data="admin_stats")],
            [back_button("admin_panel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def build_finance_report(period: str = "today") -> str:
    """
    ساخت متن گزارش مالی.
    period: today | yesterday | week | month | all
    """
    now = datetime.now()
    today_start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_dt.isoformat()
    yesterday_start = (today_start_dt - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    if period == "today":
        period_start = today_start
        period_end = None
        period_label = f"امروز ({now.strftime('%Y-%m-%d')})"
    elif period == "yesterday":
        period_start = yesterday_start
        period_end = today_start
        period_label = f"دیروز ({(today_start_dt - timedelta(days=1)).strftime('%Y-%m-%d')})"
    elif period == "week":
        period_start = week_ago
        period_end = None
        period_label = "۷ روز اخیر"
    elif period == "month":
        period_start = month_ago
        period_end = None
        period_label = "۳۰ روز اخیر"
    else:
        period_start = None
        period_end = None
        period_label = "کل دوره"

    def _range_sql(col="created_at"):
        if period_start and period_end:
            return f" AND {col} >= ? AND {col} < ?", (period_start, period_end)
        if period_start:
            return f" AND {col} >= ?", (period_start,)
        return "", ()

    async with aiosqlite.connect("bot.db") as db:
        # کاربران
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            banned_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(balance), 0) FROM users") as cur:
            total_balance = (await cur.fetchone())[0]

        # سفارش سرویس در بازه
        extra, params = _range_sql()
        async with db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(final_price), 0) FROM orders WHERE status = 'paid'{extra}",
            params,
        ) as cur:
            paid_count, paid_rev = await cur.fetchone()

        # تمدید خودکار در بازه
        auto_extra = extra
        auto_params = params
        async with db.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(final_price), 0) FROM orders
                WHERE status = 'paid'
                  AND (config_data LIKE '%"type": "auto_renew"%' OR config_data LIKE '%"type":"auto_renew"%')
                  {auto_extra}""",
            auto_params,
        ) as cur:
            auto_count, auto_rev = await cur.fetchone()

        # هدیه کد در بازه
        async with db.execute(
            f"""SELECT COUNT(*) FROM orders
                WHERE status = 'paid'
                  AND (config_data LIKE '%"type": "gift_code"%' OR config_data LIKE '%"type":"gift_code"%')
                  {extra}""",
            params,
        ) as cur:
            gift_count = (await cur.fetchone())[0]

        # پروکسی
        px_extra, px_params = _range_sql()
        async with db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(final_price), 0) FROM proxy_orders WHERE status = 'paid'{px_extra}",
            px_params,
        ) as cur:
            proxy_count, proxy_rev = await cur.fetchone()

        # شارژ کیف پول
        # وضعیت‌های رایج: paid / approved
        w_extra, w_params = _range_sql()
        async with db.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM wallet_charges
                WHERE status IN ('paid', 'approved'){w_extra}""",
            w_params,
        ) as cur:
            wallet_count, wallet_sum = await cur.fetchone()

        # در انتظار
        async with db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'") as cur:
            pending_orders = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM proxy_orders WHERE status = 'pending'") as cur:
            pending_proxy = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM wallet_charges WHERE status = 'pending'") as cur:
            pending_charges = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'") as cur:
            open_tickets = (await cur.fetchone())[0]

        # انبار پروکسی
        async with db.execute("SELECT COUNT(*) FROM proxy_stock WHERE is_sold = 0") as cur:
            proxy_stock = (await cur.fetchone())[0]

        # کل (برای مقایسه)
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(final_price), 0) FROM orders WHERE status = 'paid'"
        ) as cur:
            all_paid_count, all_paid_rev = await cur.fetchone()
        async with db.execute(
            "SELECT COALESCE(SUM(final_price), 0) FROM proxy_orders WHERE status = 'paid'"
        ) as cur:
            all_proxy_rev = (await cur.fetchone())[0]

        # کاربران جدید در بازه
        u_extra, u_params = _range_sql("join_date")
        async with db.execute(
            f"SELECT COUNT(*) FROM users WHERE 1=1{u_extra}",
            u_params,
        ) as cur:
            new_users = (await cur.fetchone())[0]

        # کد تخفیف فعال
        async with db.execute(
            "SELECT COUNT(*) FROM discount_codes WHERE is_active = 1"
        ) as cur:
            active_discounts = (await cur.fetchone())[0]

    period_total = (paid_rev or 0) + (proxy_rev or 0)
    all_total = (all_paid_rev or 0) + (all_proxy_rev or 0)

    text = (
        f"📊 <b>گزارش مالی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 بازه: <b>{period_label}</b>\n"
        f"🕐 زمان گزارش: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>فروش سرویس</b>\n"
        f"   تعداد: <b>{paid_count:,}</b>\n"
        f"   مبلغ: <b>{(paid_rev or 0):,}</b> تومان\n"
        f"🔄 تمدید خودکار: <b>{auto_count:,}</b> ({(auto_rev or 0):,} ت)\n"
        f"🎁 کد هدیه استفاده‌شده: <b>{gift_count:,}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>فروش پروکسی</b>\n"
        f"   تعداد: <b>{proxy_count:,}</b>\n"
        f"   مبلغ: <b>{(proxy_rev or 0):,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>شارژ کیف پول</b>\n"
        f"   تعداد: <b>{wallet_count:,}</b>\n"
        f"   مبلغ: <b>{(wallet_sum or 0):,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>جمع فروش این بازه</b>\n"
        f"   سرویس + پروکسی: <b>{period_total:,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 کاربران جدید: <b>{new_users:,}</b>\n"
        f"👥 کل کاربران: <b>{total_users:,}</b> | 🚫 بن: <b>{banned_users:,}</b>\n"
        f"💰 موجودی کل کیف پول‌ها: <b>{total_balance:,}</b> ت\n"
        f"📦 انبار پروکسی: <b>{proxy_stock:,}</b>\n"
        f"🎟 کد تخفیف فعال: <b>{active_discounts:,}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏳ در انتظار — سرویس: {pending_orders} | پروکسی: {pending_proxy} | شارژ: {pending_charges}\n"
        f"🎫 تیکت باز: {open_tickets}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 کل سفارشات پرداخت‌شده: <b>{all_paid_count:,}</b>\n"
        f"💵 درآمد کل (سرویس+پروکسی): <b>{all_total:,}</b> تومان"
    )
    return text



async def admin_active_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار + لیست کاربران/کانفیگ‌های روشن مستقیماً از پنل مرزبان"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    try:
        await query.edit_message_text(
            "⏳ در حال دریافت لیست کاربران از پنل مرزبان...\nلطفاً صبر کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin_active_users")],
                [back_button("admin_panel")],
            ]),
        )
    except Exception:
        pass

    # آمار ربات از دیتابیس
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0") as cur:
            bot_active_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            banned_users = (await cur.fetchone())[0]
        # مپ یوزرنیم پنل → کاربر ربات (از سفارش‌ها)
        async with db.execute(
            """SELECT panel_username, config_name, user_id FROM orders
               WHERE status = 'paid' AND (panel_username IS NOT NULL OR config_name IS NOT NULL)"""
        ) as cur:
            order_map_rows = await cur.fetchall()

    panel_to_bot = {}
    for panel_u, conf_name, uid in order_map_rows:
        for key in (panel_u, conf_name):
            if key:
                panel_to_bot[str(key).strip().lower()] = uid

    try:
        snap = await collect_panel_users_snapshot()
    except Exception as e:
        logger.error(f"admin_active_users snapshot: {e}")
        await query.edit_message_text(
            f"❌ خطا در دریافت اطلاعات از پنل:\n<code>{str(e)[:300]}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="admin_active_users")],
                [back_button("admin_panel")],
            ]),
        )
        return

    active_cfgs = snap["active"]
    all_cfgs = snap["all"]
    # اتصال به آیدی کاربر ربات در صورت وجود
    for r in all_cfgs:
        bot_uid = panel_to_bot.get((r.get("username") or "").lower())
        r["bot_user_id"] = bot_uid

    context.user_data["panel_users_all"] = all_cfgs
    context.user_data["panel_users_active"] = active_cfgs
    context.user_data["panel_users_fetched_at"] = snap["fetched_at"]

    # آمار هر پنل
    stats_lines = []
    for s in snap["stats"]:
        if s.get("error"):
            stats_lines.append(f"• {s['name']}: ❌ {s['error']}")
        else:
            stats_lines.append(
                f"• {s['name']}: کل <b>{s['total']}</b> | روشن <b>{s['active']}</b>"
            )
    stats_block = "\n".join(stats_lines) if stats_lines else "— پنلی یافت نشد —"

    # پیش‌نمایش کانفیگ‌های روشن
    preview_lines = []
    for i, c in enumerate(active_cfgs[:8], 1):
        bot_part = f" | 🆔 <code>{c['bot_user_id']}</code>" if c.get("bot_user_id") else ""
        preview_lines.append(
            f"{i}. <code>{c['username']}</code> — {c['status_fa']}\n"
            f"   🖥 {c['panel_name']} | 📊 {c['volume']} | ⏳ {c['expire']}{bot_part}"
        )
    if len(active_cfgs) > 8:
        preview_lines.append(f"... و {len(active_cfgs) - 8} کانفیگ روشن دیگر")
    preview = "\n".join(preview_lines) if preview_lines else "هیچ کانفیگ روشنی روی پنل یافت نشد."

    err_note = ""
    if snap["errors"]:
        err_note = "\n⚠️ خطاها:\n" + "\n".join(f"• {e}" for e in snap["errors"][:3])

    text_msg = (
        f"🟢 <b>کاربران و کانفیگ‌های پنل</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 کانفیگ‌های روشن روی پنل: <b>{len(active_cfgs):,}</b>\n"
        f"📋 کل کاربران ثبت‌شده در پنل: <b>{len(all_cfgs):,}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🖥 <b>وضعیت هر پنل</b>\n"
        f"{stats_block}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>آمار ربات</b>\n"
        f"• کاربران فعال ربات: <b>{bot_active_users:,}</b>\n"
        f"• کل ثبت‌نام: <b>{total_users:,}</b> | مسدود: <b>{banned_users:,}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>پیش‌نمایش کانفیگ‌های روشن</b>\n"
        f"{preview}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 آخرین بروزرسانی: <code>{snap['fetched_at']}</code>"
        f"{err_note}"
    )
    if len(text_msg) > 3900:
        text_msg = text_msg[:3890] + "…"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 کانفیگ‌های روشن", callback_data="admin_active_configs_page_0"),
            InlineKeyboardButton("📋 همه کاربران پنل", callback_data="admin_active_users_page_0"),
        ],
        [InlineKeyboardButton("🔄 بروزرسانی از پنل", callback_data="admin_active_users")],
        [back_button("admin_panel")],
    ])
    try:
        await query.edit_message_text(text_msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        try:
            await context.bot.send_message(
                query.from_user.id, text_msg, reply_markup=kb, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"admin_active_users send: {e}")


async def admin_active_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """صفحات لیست همه کاربران پنل (فعال + غیرفعال)"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    try:
        page = int(query.data.replace("admin_active_users_page_", ""))
    except Exception:
        page = 0

    rows = context.user_data.get("panel_users_all")
    if rows is None:
        # اگر کش نبود، دوباره از پنل بگیر
        try:
            snap = await collect_panel_users_snapshot()
            rows = snap["all"]
            context.user_data["panel_users_all"] = rows
            context.user_data["panel_users_active"] = snap["active"]
            context.user_data["panel_users_fetched_at"] = snap["fetched_at"]
        except Exception as e:
            await query.edit_message_text(
                f"❌ خطا در دریافت از پنل:\n{str(e)[:200]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="admin_active_users")],
                    [back_button("admin_panel")],
                ]),
            )
            return

    per_page = 10
    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page * per_page:(page + 1) * per_page]
    fetched_at = context.user_data.get("panel_users_fetched_at", "—")

    lines = [
        f"📋 <b>همه کاربران پنل</b>",
        f"صفحه {page + 1} از {total_pages} | مجموع: <b>{total:,}</b>",
        f"🕐 {fetched_at}",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for i, c in enumerate(chunk, page * per_page + 1):
        bot_part = f"\n   🆔 ربات: <code>{c['bot_user_id']}</code>" if c.get("bot_user_id") else ""
        lines.append(
            f"{i}. <code>{c['username']}</code> — {c['status_fa']}\n"
            f"   🖥 {c['panel_name']} | 📊 {c['volume']}\n"
            f"   ⏳ {c['expire']}{bot_part}"
        )
    if not chunk:
        lines.append("کاربری در پنل یافت نشد.")

    text_msg = "\n".join(lines)
    if len(text_msg) > 4000:
        text_msg = text_msg[:3990] + "…"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"admin_active_users_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"admin_active_users_page_{page + 1}"))

    buttons = []
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🟢 فقط کانفیگ‌های روشن", callback_data="admin_active_configs_page_0")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی از پنل", callback_data="admin_active_users")])
    buttons.append([back_button("admin_panel")])

    try:
        await query.edit_message_text(
            text_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            query.from_user.id, text_msg,
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )


async def admin_active_configs_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """صفحات لیست کانفیگ‌های روشن روی پنل"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    try:
        page = int(query.data.replace("admin_active_configs_page_", ""))
    except Exception:
        page = 0

    rows = context.user_data.get("panel_users_active")
    if rows is None:
        try:
            snap = await collect_panel_users_snapshot()
            rows = snap["active"]
            context.user_data["panel_users_all"] = snap["all"]
            context.user_data["panel_users_active"] = rows
            context.user_data["panel_users_fetched_at"] = snap["fetched_at"]
        except Exception as e:
            await query.edit_message_text(
                f"❌ خطا در دریافت از پنل:\n{str(e)[:200]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="admin_active_users")],
                    [back_button("admin_panel")],
                ]),
            )
            return

    per_page = 10
    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = rows[page * per_page:(page + 1) * per_page]
    fetched_at = context.user_data.get("panel_users_fetched_at", "—")

    lines = [
        f"🟢 <b>کانفیگ‌های روشن پنل</b>",
        f"صفحه {page + 1} از {total_pages} | مجموع: <b>{total:,}</b>",
        f"🕐 {fetched_at}",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for i, c in enumerate(chunk, page * per_page + 1):
        bot_part = f"\n   🆔 ربات: <code>{c['bot_user_id']}</code>" if c.get("bot_user_id") else ""
        pct = f" | {c['percent']}٪" if c.get("limit") else ""
        lines.append(
            f"{i}. <code>{c['username']}</code> — {c['status_fa']}\n"
            f"   🖥 {c['panel_name']} | 📊 {c['volume']}{pct}\n"
            f"   ⏳ انقضا: {c['expire']}{bot_part}"
        )
    if not chunk:
        lines.append("کانفیگ روشنی یافت نشد.")

    text_msg = "\n".join(lines)
    if len(text_msg) > 4000:
        text_msg = text_msg[:3990] + "…"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"admin_active_configs_page_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"admin_active_configs_page_{page + 1}"))

    buttons = []
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("📋 همه کاربران پنل", callback_data="admin_active_users_page_0")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی از پنل", callback_data="admin_active_users")])
    buttons.append([back_button("admin_panel")])

    try:
        await query.edit_message_text(
            text_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            query.from_user.id, text_msg,
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
        )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """گزارش مالی — پیش‌فرض امروز + دکمه‌های بازه"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    period = "today"
    if query.data and query.data.startswith("finance_"):
        period = query.data.replace("finance_", "") or "today"

    text = await build_finance_report(period)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 امروز", callback_data="finance_today"),
            InlineKeyboardButton("📆 دیروز", callback_data="finance_yesterday"),
        ],
        [
            InlineKeyboardButton("🗓 ۷ روز", callback_data="finance_week"),
            InlineKeyboardButton("🗓 ۳۰ روز", callback_data="finance_month"),
        ],
        [InlineKeyboardButton("📊 کل دوره", callback_data="finance_all")],
        [InlineKeyboardButton("📋 لاگ ادمین‌ها", callback_data="admin_logs")],
        [back_button("admin_panel")],
    ])
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(
            query.from_user.id, text, reply_markup=kb, parse_mode=ParseMode.HTML
        )


async def send_daily_finance_report(context: ContextTypes.DEFAULT_TYPE):
    """جاب روزانه: ارسال گزارش مالی امروز به ادمین اصلی"""
    try:
        text = await build_finance_report("today")
        text = "🌙 <b>گزارش مالی روزانه (خودکار)</b>\n" + text
        await context.bot.send_message(
            ADMIN_ID,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 گزارش کامل", callback_data="admin_stats")],
                [InlineKeyboardButton("🛠 پنل مدیریت", callback_data="admin_panel")],
            ]),
        )
        logger.info("Daily finance report sent to admin.")
    except Exception as e:
        logger.error(f"send_daily_finance_report: {e}")


# ---------- بقیه توابع ادمین (از کد اصلی کپی شده و حفظ شده) ----------
async def admin_tariff_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "holland" in query.data:
        server = "holland"
    elif "unlimited" in query.data:
        server = "unlimited"
    else:
        server = "multi"
    context.user_data["admin_server"] = server

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT id, volume_gb, price, is_active FROM tariffs WHERE server_type = ? ORDER BY volume_gb",
            (server,)
        ) as cur:
            rows = await cur.fetchall()

    buttons = []
    for tid, vol, price, active in rows:
        status_btn = "✅" if active else "❌"
        if server == "unlimited":
            label = f"{vol} ماهه — {price:,}"
        else:
            label = f"{vol}G — {price:,}"
        buttons.append([
            InlineKeyboardButton(label, callback_data="noop"),
            InlineKeyboardButton(status_btn, callback_data=f"toggle_tariff_{tid}"),
            InlineKeyboardButton("✏️", callback_data=f"edit_tariff_{tid}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_tariff_{tid}"),
        ])
    buttons.append([InlineKeyboardButton("➕ افزودن تعرفه جدید", callback_data="admin_add_tariff")])
    buttons.append([back_button("admin_panel")])
    if server == "holland":
        title = "🇳🇱 تعرفه‌های هلند"
    elif server == "unlimited":
        title = "💎 تعرفه‌های نامحدود"
    else:
        title = "🌐 تعرفه‌های مولتی"
    await query.edit_message_text(title + "\n\n✅/❌ فعال | ✏️ ویرایش | 🗑 حذف", reply_markup=InlineKeyboardMarkup(buttons))

async def toggle_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tid = int(query.data.split("_")[-1])
    server = context.user_data.get("admin_server", "holland")

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM tariffs WHERE id = ?", (tid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("تعرفه یافت نشد", show_alert=True)
            return
        new = 0 if row[0] else 1
        await db.execute("UPDATE tariffs SET is_active = ? WHERE id = ?", (new, tid))
        await db.commit()

        async with db.execute(
            "SELECT id, volume_gb, price, is_active FROM tariffs WHERE server_type = ? ORDER BY volume_gb",
            (server,)
        ) as cur:
            rows = await cur.fetchall()

    await query.answer("✅ سرویس فعال شد" if new else "❌ سرویس غیرفعال شد", show_alert=True)

    buttons = []
    for t_id, vol, price, active in rows:
        status_btn = "✅ فعال" if active else "❌ غیرفعال"
        buttons.append([
            InlineKeyboardButton(f"{vol} گیگ — {price:,} ت", callback_data="noop"),
            InlineKeyboardButton(status_btn, callback_data=f"toggle_tariff_{t_id}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_tariff_{t_id}"),
        ])
    buttons.append([InlineKeyboardButton("➕ افزودن تعرفه جدید", callback_data="admin_add_tariff")])
    buttons.append([back_button("admin_panel")])

    if server == "holland":
        title = "🇳🇱 تعرفه‌های هلند"
    elif server == "unlimited":
        title = "💎 تعرفه‌های نامحدود"
    else:
        title = "🌐 تعرفه‌های مولتی"
    try:
        await query.edit_message_text(
            title + "\n\nروی دکمه فعال/غیرفعال یا 🗑 بزنید:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=title + "\n\nروی دکمه فعال/غیرفعال یا 🗑 بزنید:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

async def delete_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tid = int(query.data.split("_")[-1])
    server = context.user_data.get("admin_server", "holland")

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM tariffs WHERE id = ?", (tid,))
        await db.commit()
        async with db.execute(
            "SELECT id, volume_gb, price, is_active FROM tariffs WHERE server_type = ? ORDER BY volume_gb",
            (server,)
        ) as cur:
            rows = await cur.fetchall()

    await query.answer("🗑 تعرفه حذف شد", show_alert=True)

    buttons = []
    for t_id, vol, price, active in rows:
        status_btn = "✅ فعال" if active else "❌ غیرفعال"
        buttons.append([
            InlineKeyboardButton(f"{vol} گیگ — {price:,} ت", callback_data="noop"),
            InlineKeyboardButton(status_btn, callback_data=f"toggle_tariff_{t_id}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_tariff_{t_id}"),
        ])
    buttons.append([InlineKeyboardButton("➕ افزودن تعرفه جدید", callback_data="admin_add_tariff")])
    buttons.append([back_button("admin_panel")])
    if server == "holland":
        title = "🇳🇱 تعرفه‌های هلند"
    elif server == "unlimited":
        title = "💎 تعرفه‌های نامحدود"
    else:
        title = "🌐 تعرفه‌های مولتی"
    try:
        await query.edit_message_text(
            title + "\n\nروی دکمه فعال/غیرفعال یا 🗑 بزنید:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except:
        pass

async def edit_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT volume_gb, price FROM tariffs WHERE id = ?", (tid,)) as cur:
            row = await cur.fetchone()
    if not row:
        await query.answer("تعرفه یافت نشد", show_alert=True)
        return
    vol, price = row
    context.user_data["edit_tariff_id"] = tid
    context.user_data["edit_tariff_old_vol"] = vol
    context.user_data["edit_tariff_old_price"] = price
    await query.edit_message_text(
        f"✏️ ویرایش تعرفه\n\n"
        f"حجم فعلی: <b>{vol}</b> گیگ\n"
        f"قیمت فعلی: <b>{price:,}</b> تومان\n\n"
        f"حجم جدید را به گیگابایت وارد کنید (یا همان {vol} را بفرستید):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_EDIT_TARIFF_GB

async def admin_edit_tariff_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        gb = int(update.message.text.strip())
        if gb <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_EDIT_TARIFF_GB

    context.user_data["edit_tariff_new_vol"] = gb
    old_price = context.user_data.get("edit_tariff_old_price", 0)
    await update.message.reply_text(
        f"حجم جدید: <b>{gb}</b> گیگ ثبت شد.\n\n"
        f"قیمت جدید را به تومان وارد کنید (یا همان {old_price:,} را بفرستید):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_EDIT_TARIFF_PRICE

async def admin_edit_tariff_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(",", ""))
        if price <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_EDIT_TARIFF_PRICE

    tid = context.user_data.get("edit_tariff_id")
    gb = context.user_data.get("edit_tariff_new_vol")
    if not tid or not gb:
        await update.message.reply_text("خطا. دوباره تلاش کنید.")
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "UPDATE tariffs SET volume_gb = ?, price = ? WHERE id = ?",
            (gb, price, tid)
        )
        await db.commit()

    await update.message.reply_text(
        f"✅ تعرفه ویرایش شد.\n\n"
        f"📦 حجم جدید: <b>{gb}</b> گیگ\n"
        f"💰 قیمت جدید: <b>{price:,}</b> تومان",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_maintenance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تعمیرات: روشن/خاموش دستی + زمان‌دار"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    info = await get_maintenance_info()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 روشن کردن تعمیرات (دستی)", callback_data="maint_on_manual")],
        [InlineKeyboardButton("⏱ تعمیرات زمان‌دار", callback_data="maint_timed")],
        [InlineKeyboardButton("🟢 خاموش کردن تعمیرات", callback_data="maint_off")],
        [back_button("admin_settings")],
    ])
    await query.edit_message_text(
        f"🔧 <b>حالت تعمیرات</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت فعلی: <b>{info}</b>\n\n"
        f"• <b>دستی:</b> تا وقتی خودتان خاموش کنید فعال می‌ماند.\n"
        f"• <b>زمان‌دار:</b> بعد از مدت مشخص خودکار خاموش می‌شود.\n"
        f"در حالت تعمیرات، کاربران عادی نمی‌توانند از ربات استفاده کنند (ادمین‌ها می‌توانند).",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def admin_toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """سازگاری با callback قدیمی — هدایت به منوی تعمیرات"""
    return await admin_maintenance_menu(update, context)


async def maint_on_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await set_setting("maintenance", "1")
    await set_setting("maintenance_until", "")
    await query.edit_message_text(
        "🔴 <b>تعمیرات دستی فعال شد.</b>\n\n"
        "کاربران عادی فعلاً به ربات دسترسی ندارند.\n"
        "برای خاموش کردن از منوی تعمیرات اقدام کنید.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 منوی تعمیرات", callback_data="admin_toggle_maintenance")],
            [back_button("admin_settings")],
        ]),
    )


async def maint_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await set_setting("maintenance", "0")
    await set_setting("maintenance_until", "")
    await query.edit_message_text(
        "🟢 <b>تعمیرات خاموش شد.</b>\nربات برای همه کاربران فعال است.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 منوی تعمیرات", callback_data="admin_toggle_maintenance")],
            [back_button("admin_settings")],
        ]),
    )


async def maint_timed_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "⏱ <b>تعمیرات زمان‌دار</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕐 ساعت فعلی ایران: <b>{now_tehran().strftime('%Y/%m/%d %H:%M')}</b>\n\n"
        "مدت تعمیرات را به <b>ساعت</b> وارد کنید.\n"
        "مثال: <code>1</code> → یک ساعت از همین الان\n"
        "یا <code>0.5</code> → ۳۰ دقیقه\n\n"
        "زمان پایان بر اساس <b>ساعت ایران</b> محاسبه می‌شود و بعد از آن خودکار خاموش می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_toggle_maintenance")]]),
    )
    return ADMIN_MAINT_HOURS


async def maint_timed_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hours = float(update.message.text.strip().replace(",", "."))
        if hours <= 0 or hours > 168:
            raise ValueError
    except Exception:
        await update.message.reply_text("❌ عدد معتبر بین ۰.۱ تا ۱۶۸ (ساعت) وارد کنید:")
        return ADMIN_MAINT_HOURS

    # محاسبه با ساعت ایران تا با ساعت کاربر یکی باشد
    start_dt = now_tehran()
    end_dt = start_dt + timedelta(hours=hours)
    await set_setting("maintenance", "1")
    await set_setting("maintenance_until", end_dt.isoformat())
    mins = int(round(hours * 60))
    if mins >= 60:
        dur = f"{mins // 60} ساعت و {mins % 60} دقیقه" if mins % 60 else f"{mins // 60} ساعت"
    else:
        dur = f"{mins} دقیقه"

    await update.message.reply_text(
        f"🔴 <b>تعمیرات زمان‌دار فعال شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱ مدت: <b>{dur}</b>\n"
        f"🕐 شروع (ایران): <b>{start_dt.strftime('%Y/%m/%d %H:%M')}</b>\n"
        f"🕐 پایان (ایران): <b>{end_dt.strftime('%Y/%m/%d %H:%M')}</b>\n\n"
        f"پس از این زمان، ربات خودکار از حالت تعمیرات خارج می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True),
    )
    return ConversationHandler.END


# ---------- جستجو / حذف کانفیگ در پنل ----------
async def admin_panel_cfg_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🔎 <b>جستجوی کانفیگ در پنل</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "نام کاربری کانفیگ را در پنل مرزبان وارد کنید:\n"
        "(مثال: <code>user_abc123</code>)",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]]),
    )
    return ADMIN_PANEL_CFG_SEARCH


async def admin_panel_cfg_search_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = (update.message.text or "").strip()
    if len(username) < 2:
        await update.message.reply_text("❌ نام کاربری معتبر وارد کنید:")
        return ADMIN_PANEL_CFG_SEARCH

    await update.message.reply_text("⏳ در حال جستجو در پنل‌ها...")

    found = []
    errors = []
    for ptype, label in [
        ("holland", "🇳🇱 هلند"),
        ("multi", "🌐 مولتی"),
        ("unlimited", "💎 نامحدود"),
        ("test", "🧪 تست"),
    ]:
        try:
            info = await get_user_from_panel(username, server_type=ptype, is_test=(ptype == "test"))
            if info:
                row = _format_panel_user_row(info, label, ptype)
                found.append(row)
        except Exception as e:
            errors.append(f"{label}: {str(e)[:80]}")

    if not found:
        err = ("\n" + "\n".join(errors)) if errors else ""
        await update.message.reply_text(
            f"❌ کانفیگ <code>{username}</code> در هیچ پنلی یافت نشد.{err}",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(True),
        )
        return ConversationHandler.END

    # اگر چند پنل همان URL باشند ممکن است تکراری باشد
    seen = set()
    unique = []
    for r in found:
        k = (r["username"], r.get("expire"), r.get("status"))
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)

    context.user_data["panel_cfg_search_user"] = username
    lines = [
        f"🔎 <b>نتیجه جستجو:</b> <code>{username}</code>",
        "━━━━━━━━━━━━━━━━━━",
    ]
    buttons = []
    for r in unique:
        lines.append(
            f"🖥 {r['panel_name']}\n"
            f"• وضعیت: {r['status_fa']}\n"
            f"• حجم: {r['volume']}\n"
            f"• انقضا: {r['expire']}\n"
            f"• روشن: {'بله ✅' if r['is_on'] else 'خیر ❌'}\n"
            "—————————————"
        )
        buttons.append([
            InlineKeyboardButton(
                f"🗑 حذف از {r['panel_name'][:20]}",
                callback_data=f"panel_del_cfg_{r['panel_type']}_{username}",
            )
        ])
    buttons.append([back_button("admin_panel")])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


async def admin_panel_cfg_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🗑 <b>حذف کانفیگ از پنل</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "نام کاربری کانفیگی که می‌خواهید از پنل مرزبان حذف شود را وارد کنید:\n"
        "⚠️ این عمل غیرقابل بازگشت است.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]]),
    )
    return ADMIN_PANEL_CFG_DELETE


async def admin_panel_cfg_delete_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = (update.message.text or "").strip()
    if len(username) < 2:
        await update.message.reply_text("❌ نام کاربری معتبر وارد کنید:")
        return ADMIN_PANEL_CFG_DELETE

    context.user_data["panel_del_username"] = username
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 حذف از هلند", callback_data=f"panel_del_cfg_holland_{username}")],
        [InlineKeyboardButton("🌐 حذف از مولتی", callback_data=f"panel_del_cfg_multi_{username}")],
        [InlineKeyboardButton("💎 حذف از نامحدود", callback_data=f"panel_del_cfg_unlimited_{username}")],
        [InlineKeyboardButton("🧪 حذف از تست", callback_data=f"panel_del_cfg_test_{username}")],
        [InlineKeyboardButton("🗑 حذف از همه پنل‌ها", callback_data=f"panel_del_cfg_all_{username}")],
        [back_button("admin_panel")],
    ])
    await update.message.reply_text(
        f"کاربر <code>{username}</code> از کدام پنل حذف شود؟",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    return ConversationHandler.END


async def panel_del_cfg_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """callback: panel_del_cfg_{type}_{username}"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    raw = query.data.replace("panel_del_cfg_", "", 1)
    # type may be all/holland/multi/... username may contain underscores
    parts = raw.split("_", 1)
    if len(parts) < 2:
        await query.answer("داده نامعتبر", show_alert=True)
        return
    ptype, username = parts[0], parts[1]

    types_to_try = []
    if ptype == "all":
        types_to_try = ["holland", "multi", "unlimited", "test"]
    elif ptype in ("holland", "multi", "unlimited", "test"):
        types_to_try = [ptype]
    else:
        await query.answer("نوع پنل نامعتبر", show_alert=True)
        return

    results = []
    for t in types_to_try:
        try:
            ok = await delete_user_from_panel(username, is_test=(t == "test"), server_type=t)
            results.append(f"{'✅' if ok else '❌'} {t}")
        except Exception as e:
            results.append(f"❌ {t}: {str(e)[:60]}")

    await log_admin_action(
        query.from_user.id,
        "delete_panel_config",
        detail=f"user={username}, types={ptype}, res={';'.join(results)}",
    )
    await query.edit_message_text(
        f"🗑 <b>نتیجه حذف</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <code>{username}</code>\n"
        + "\n".join(results),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]]),
    )


# ---------- مدیریت سوالات آماده پشتیبانی ----------
async def admin_manage_sqa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    qa = await get_support_quick_qa()
    lines = [
        "🧩 <b>مدیریت سوالات پاسخ آماده پشتیبانی</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"تعداد: <b>{len(qa)}</b>",
        "",
    ]
    buttons = []
    for key, (title, _ans) in qa.items():
        short = title if len(title) <= 40 else title[:37] + "…"
        lines.append(f"• {short}")
        buttons.append([
            InlineKeyboardButton(f"✏️ {short}", callback_data=f"sqa_edit_{key}"),
            InlineKeyboardButton("🗑", callback_data=f"sqa_del_{key}"),
        ])
    buttons.append([InlineKeyboardButton("➕ افزودن سوال جدید", callback_data="sqa_add")])
    buttons.append([InlineKeyboardButton("♻️ بازنشانی به پیش‌فرض", callback_data="sqa_reset_defaults")])
    buttons.append([back_button("admin_panel")])

    text_msg = "\n".join(lines)
    if len(text_msg) > 3500:
        text_msg = text_msg[:3490] + "…"
    await query.edit_message_text(
        text_msg,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def sqa_reset_defaults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("بازنشانی شد", show_alert=True)
    if not await is_admin(query.from_user.id):
        return
    await save_support_quick_qa(dict(DEFAULT_SUPPORT_QUICK_QA))
    await admin_manage_sqa(update, context)


async def sqa_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    key = query.data.replace("sqa_del_", "", 1)
    qa = await get_support_quick_qa()
    if key in qa:
        qa.pop(key)
        await save_support_quick_qa(qa)
        await query.answer("حذف شد", show_alert=True)
    await admin_manage_sqa(update, context)


async def sqa_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "➕ <b>افزودن سوال آماده</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "عنوان دکمه سوال را بفرستید:\n"
        "مثال: <code>🛒 چطور سرویس بخرم؟</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_manage_sqa")]]),
    )
    return ADMIN_SQA_ADD_TITLE


async def sqa_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = (update.message.text or "").strip()
    if len(title) < 3:
        await update.message.reply_text("عنوان خیلی کوتاه است. دوباره بنویسید:")
        return ADMIN_SQA_ADD_TITLE
    context.user_data["sqa_new_title"] = title
    await update.message.reply_text(
        "✅ عنوان ثبت شد.\n\n"
        "حالا <b>متن پاسخ پشتیبانی</b> را کامل بفرستید:",
        parse_mode=ParseMode.HTML,
    )
    return ADMIN_SQA_ADD_ANSWER


async def sqa_add_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = (update.message.text or "").strip()
    if len(answer) < 5:
        await update.message.reply_text("پاسخ خیلی کوتاه است. دوباره بنویسید:")
        return ADMIN_SQA_ADD_ANSWER
    title = context.user_data.get("sqa_new_title") or "سوال"
    qa = await get_support_quick_qa()
    key = "sqa_" + ''.join(__import__('random').choices(__import__('string').ascii_lowercase + __import__('string').digits, k=8))
    qa[key] = (title, answer)
    await save_support_quick_qa(qa)
    context.user_data.pop("sqa_new_title", None)
    await update.message.reply_text(
        f"✅ سوال آماده اضافه شد.\n\n❓ {title}",
        reply_markup=main_keyboard(True),
    )
    return ConversationHandler.END


async def sqa_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    key = query.data.replace("sqa_edit_", "", 1)
    qa = await get_support_quick_qa()
    if key not in qa:
        await query.answer("یافت نشد", show_alert=True)
        return await admin_manage_sqa(update, context)
    title, answer = qa[key]
    context.user_data["sqa_edit_key"] = key
    await query.edit_message_text(
        f"✏️ <b>ویرایش پاسخ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❓ {title}\n\n"
        f"پاسخ فعلی:\n{answer[:500]}{'…' if len(answer) > 500 else ''}\n\n"
        f"متن <b>پاسخ جدید</b> را ارسال کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_manage_sqa")]]),
    )
    return ADMIN_SQA_EDIT_ANSWER


async def sqa_edit_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = (update.message.text or "").strip()
    if len(answer) < 5:
        await update.message.reply_text("پاسخ خیلی کوتاه است. دوباره بنویسید:")
        return ADMIN_SQA_EDIT_ANSWER
    key = context.user_data.get("sqa_edit_key")
    qa = await get_support_quick_qa()
    if not key or key not in qa:
        await update.message.reply_text("خطا. دوباره از منو شروع کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END
    title = qa[key][0]
    qa[key] = (title, answer)
    await save_support_quick_qa(qa)
    context.user_data.pop("sqa_edit_key", None)
    await update.message.reply_text(
        f"✅ پاسخ سوال «{title}» به‌روز شد.",
        reply_markup=main_keyboard(True),
    )
    return ConversationHandler.END


async def admin_add_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📦 حجم تعرفه جدید را به گیگابایت بفرستید (مثال: 60)")
    return ADMIN_ADD_TARIFF_GB

async def admin_add_tariff_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        gb = int(update.message.text.strip())
        if gb <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_ADD_TARIFF_GB
    context.user_data["new_tariff_gb"] = gb
    await update.message.reply_text("💰 قیمت این تعرفه را به تومان بفرستید (مثال: 100000)")
    return ADMIN_ADD_TARIFF_PRICE

async def admin_add_tariff_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(",", ""))
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_ADD_TARIFF_PRICE
    server = context.user_data.get("admin_server", "holland")
    gb = context.user_data["new_tariff_gb"]
    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO tariffs (server_type, volume_gb, price) VALUES (?, ?, ?)",
            (server, gb, price)
        )
        await db.commit()
    await update.message.reply_text(f"✅ تعرفه {gb} گیگ با قیمت {price:,} تومان اضافه شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await get_setting("welcome")
    await query.edit_message_text(
        f"✉️ پیام خوش‌آمدگویی فعلی:\n\n{current}\n\n—————————————\nمتن جدید را بفرستید:"
    )
    return ADMIN_WELCOME

async def admin_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_setting("welcome", update.message.text)
    await update.message.reply_text("✅ پیام خوش‌آمدگویی به‌روزرسانی شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await get_setting("rules")
    await query.edit_message_text(
        f"📜 قوانین فعلی:\n\n{current}\n\n—————————————\nمتن جدید قوانین را بفرستید:"
    )
    return ADMIN_RULES

async def admin_set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_setting("rules", update.message.text)
    await update.message.reply_text("✅ قوانین به‌روزرسانی شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, code, percent, max_uses, used_count, is_active, expires_at
               FROM discount_codes ORDER BY id DESC"""
        ) as cur:
            rows = await cur.fetchall()

    buttons = []
    now = datetime.now()
    if not rows:
        text = "🎟 <b>کدهای تخفیف / کمپین</b>\n\nهیچ کدی وجود ندارد."
    else:
        text = "🎟 <b>کدهای تخفیف / کمپین</b>\nروی هر کد بزنید تا فعال/غیرفعال شود، یا با 🗑 حذفش کنید.\n"
        for did, code, percent, maxu, used, active, expires_at in rows:
            status = "✅" if active else "❌"
            limit = "∞" if maxu == 0 else f"{used}/{maxu}"
            exp_label = ""
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                    if now > exp_dt:
                        exp_label = " | ⏰ منقضی"
                        status = "⌛"
                    else:
                        remain_h = int((exp_dt - now).total_seconds() // 3600)
                        if remain_h >= 24:
                            exp_label = f" | ⏳ {remain_h // 24}د"
                        else:
                            exp_label = f" | ⏳ {remain_h}س"
                except Exception:
                    exp_label = " | ⏳"
            else:
                exp_label = " | ∞"
            buttons.append([
                InlineKeyboardButton(
                    f"{status} {code} | {percent}% | {limit}{exp_label}",
                    callback_data=f"toggle_disc_{did}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"del_disc_{did}")
            ])
    buttons.append([InlineKeyboardButton("➕ ساخت کد تخفیف / کمپین", callback_data="admin_new_discount")])
    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_new_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🎟 <b>ساخت کد تخفیف / کمپین</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد را وارد کنید (فقط حروف انگلیسی و عدد، بدون فاصله):\n"
        "مثال: <code>NeXoRa24H</code> یا <code>VIP100</code>",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_DISCOUNT_CODE

async def admin_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if not code.isalnum() or len(code) < 2:
        await update.message.reply_text("فقط حروف و عدد انگلیسی مجاز است (حداقل ۲ کاراکتر).")
        return ADMIN_DISCOUNT_CODE
    context.user_data["new_disc_code"] = code
    await update.message.reply_text("چند درصد تخفیف بده؟ (عدد از ۱ تا ۱۰۰)")
    return ADMIN_DISCOUNT_PERCENT

async def admin_discount_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p = int(update.message.text.strip())
        if not 1 <= p <= 100:
            raise ValueError
    except:
        await update.message.reply_text("عدد بین ۱ تا ۱۰۰ وارد کنید.")
        return ADMIN_DISCOUNT_PERCENT
    context.user_data["new_disc_percent"] = p
    await update.message.reply_text(
        "حداکثر تعداد استفاده از این کد چقدر باشه؟\n"
        "(برای نامحدود عدد <b>۰</b> را بفرستید):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_DISCOUNT_LIMIT

async def admin_discount_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        limit = int(update.message.text.strip())
        if limit < 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید (۰ = نامحدود).")
        return ADMIN_DISCOUNT_LIMIT
    context.user_data["new_disc_limit"] = limit
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("۲۴ ساعت", callback_data="disc_exp_24"),
            InlineKeyboardButton("۴۸ ساعت", callback_data="disc_exp_48"),
        ],
        [
            InlineKeyboardButton("۷۲ ساعت", callback_data="disc_exp_72"),
            InlineKeyboardButton("۷ روز", callback_data="disc_exp_168"),
        ],
        [
            InlineKeyboardButton("۳۰ روز", callback_data="disc_exp_720"),
            InlineKeyboardButton("بدون انقضا ∞", callback_data="disc_exp_0"),
        ],
        [InlineKeyboardButton("✏️ وارد کردن ساعت دلخواه", callback_data="disc_exp_custom")],
    ])
    await update.message.reply_text(
        "⏰ <b>مدت اعتبار کد (کمپین)</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "چند ساعت این کد معتبر باشد؟\n"
        "یا یکی از گزینه‌های آماده را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )
    return ADMIN_DISCOUNT_EXPIRE


async def admin_discount_expire_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب مدت از دکمه یا درخواست ورودی سفارشی"""
    query = update.callback_query
    await query.answer()
    data = query.data  # disc_exp_24 / disc_exp_0 / disc_exp_custom

    if data == "disc_exp_custom":
        await query.edit_message_text(
            "✏️ تعداد ساعت اعتبار را وارد کنید (مثال: <code>48</code> برای ۴۸ ساعت):\n"
            "عدد <b>۰</b> = بدون انقضا",
            parse_mode=ParseMode.HTML
        )
        return ADMIN_DISCOUNT_EXPIRE

    try:
        hours = int(data.replace("disc_exp_", ""))
    except:
        hours = 0
    return await _save_discount_code(update, context, hours, from_callback=True)


async def admin_discount_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت ساعت دلخواه از متن"""
    try:
        hours = int(update.message.text.strip().replace(",", ""))
        if hours < 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید (۰ = بدون انقضا):")
        return ADMIN_DISCOUNT_EXPIRE
    return await _save_discount_code(update, context, hours, from_callback=False)


def _format_campaign_duration(hours: int) -> str:
    if hours <= 0:
        return "بدون محدودیت زمانی"
    if hours >= 24:
        days = hours // 24
        rem = hours % 24
        if rem:
            return f"{days} روز و {rem} ساعت"
        return f"{days} روز"
    return f"{hours} ساعت"


def build_campaign_promo_message(code: str, percent: int, hours: int, max_uses: int) -> str:
    """متن تبلیغاتی زیبا برای کمپین کد تخفیف"""
    now = datetime.now()
    duration = _format_campaign_duration(hours)
    if hours > 0:
        exp_dt = now + timedelta(hours=hours)
        deadline = exp_dt.strftime("%Y/%m/%d — %H:%M")
        urgency = (
            f"⏳ فقط تا <b>{deadline}</b>\n"
            f"🕐 مدت اعتبار: <b>{duration}</b>"
        )
    else:
        urgency = "⏰ اعتبار: بدون محدودیت زمانی"

    if max_uses == 0:
        capacity = "ظرفیت استفاده: <b>نامحدود</b>"
    elif max_uses == 1:
        capacity = "ظرفیت: <b>فقط ۱ نفر</b> — زودتر اقدام کنید!"
    else:
        capacity = f"ظرفیت محدود: فقط <b>{max_uses}</b> نفر"

    # نوار تخفیف بصری
    bar = "🔥" * min(10, max(3, percent // 10))

    return (
        f"✨ <b>کمپین ویژه تخفیف فعال شد!</b> ✨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{bar}\n"
        f"🏷 تخفیف اختصاصی: <b>{percent}٪</b>\n"
        f"🎟 کد تخفیف:\n"
        f"<code>{code}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{urgency}\n"
        f"{capacity}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛒 چطور استفاده کنم؟\n"
        f"۱) وارد ربات شو و «خرید سرویس» را بزن\n"
        f"۲) پلن مورد نظرت را انتخاب کن\n"
        f"۳) روی «🎟 اعمال کد تخفیف» بزن\n"
        f"۴) کد <code>{code}</code> را وارد کن\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 همین حالا سرویس بگیر و از تخفیف {percent}٪ استفاده کن!\n"
        f"🚀 فرصت محدوده — از دستش نده 👇"
    )


async def broadcast_campaign_to_users(bot, promo_text: str) -> tuple:
    """ارسال کمپین به همه کاربران غیربن. برمی‌گرداند (موفق، ناموفق)"""
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT user_id FROM users WHERE is_banned = 0") as cur:
            users = await cur.fetchall()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید سرویس با تخفیف", callback_data="buy_service")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_main")],
    ])
    ok, fail = 0, 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, promo_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    return ok, fail


async def _save_discount_code(update, context, hours: int, from_callback: bool = False):
    code = context.user_data.get("new_disc_code")
    percent = context.user_data.get("new_disc_percent")
    limit = context.user_data.get("new_disc_limit", 0)
    if not code or percent is None:
        msg = "❌ اطلاعات ناقص است. دوباره از ابتدا شروع کنید."
        if from_callback:
            await update.callback_query.edit_message_text(msg, reply_markup=main_keyboard(True))
        else:
            await update.message.reply_text(msg, reply_markup=main_keyboard(True))
        return ConversationHandler.END

    now = datetime.now()
    expires_at = None
    if hours > 0:
        expires_at = (now + timedelta(hours=hours)).isoformat()

    async with aiosqlite.connect("bot.db") as db:
        try:
            await db.execute(
                """INSERT INTO discount_codes
                   (code, percent, max_uses, expires_at, starts_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (code, percent, limit, expires_at, now.isoformat(), now.isoformat())
            )
            await db.commit()
        except Exception:
            err = "❌ این کد قبلاً وجود دارد."
            if from_callback:
                await update.callback_query.edit_message_text(err, reply_markup=main_keyboard(True))
            else:
                await update.message.reply_text(err, reply_markup=main_keyboard(True))
            return ConversationHandler.END

    if hours > 0:
        exp_dt = now + timedelta(hours=hours)
        time_txt = _format_campaign_duration(hours)
        expire_txt = f"⏰ اعتبار: <b>{time_txt}</b> (تا {exp_dt.strftime('%Y-%m-%d %H:%M')})"
    else:
        expire_txt = "⏰ اعتبار: <b>بدون انقضا</b>"

    limit_txt = "نامحدود" if limit == 0 else str(limit)
    text = (
        f"✅ <b>کد تخفیف / کمپین ساخته شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎟 کد: <code>{code}</code>\n"
        f"💰 تخفیف: <b>{percent}٪</b>\n"
        f"🔢 ظرفیت: {limit_txt}\n"
        f"{expire_txt}"
    )

    # اگر زمان‌دار باشد → کمپین همگانی خودکار
    if hours > 0:
        text += "\n\n📢 در حال ارسال پیام تبلیغاتی به همه کاربران..."
        if from_callback:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        promo = build_campaign_promo_message(code, percent, hours, limit)
        bot = context.bot
        try:
            ok, fail = await broadcast_campaign_to_users(bot, promo)
            result = (
                f"✅ <b>کد تخفیف / کمپین ساخته شد</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎟 کد: <code>{code}</code>\n"
                f"💰 تخفیف: <b>{percent}٪</b>\n"
                f"🔢 ظرفیت: {limit_txt}\n"
                f"{expire_txt}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📢 کمپین همگانی ارسال شد\n"
                f"✅ موفق: <b>{ok}</b> نفر\n"
                f"❌ ناموفق: <b>{fail}</b> نفر"
            )
        except Exception as e:
            logger.error(f"campaign broadcast: {e}")
            result = text + f"\n\n⚠️ خطا در ارسال همگانی:\n{str(e)[:120]}"

        # پیش‌نمایش متن تبلیغاتی برای ادمین
        preview = (
            f"\n\n📝 <b>پیش‌نمایش پیام ارسالی:</b>\n"
            f"—————————————\n"
            f"{promo}"
        )
        # اگر خیلی طولانی شد، جدا بفرست
        full = result + preview
        if len(full) > 3900:
            if from_callback:
                await update.callback_query.edit_message_text(
                    result, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
                )
            else:
                await update.message.reply_text(
                    result, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
                )
            await context.bot.send_message(
                update.effective_user.id,
                f"📝 <b>پیش‌نمایش پیام کمپین:</b>\n━━━━━━━━━━━━━━━━━━\n{promo}",
                parse_mode=ParseMode.HTML,
            )
        else:
            if from_callback:
                await update.callback_query.edit_message_text(
                    full, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
                )
            else:
                await update.message.reply_text(
                    full, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
                )
    else:
        if from_callback:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
            )
        else:
            await update.message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
            )

    for k in ("new_disc_code", "new_disc_percent", "new_disc_limit"):
        context.user_data.pop(k, None)
    return ConversationHandler.END

async def toggle_disc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    did = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM discount_codes WHERE id = ?", (did,)) as cur:
            row = await cur.fetchone()
        new = 0 if row[0] else 1
        await db.execute("UPDATE discount_codes SET is_active = ? WHERE id = ?", (new, did))
        await db.commit()
    await admin_discounts(update, context)

async def del_disc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    did = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM discount_codes WHERE id = ?", (did,))
        await db.commit()
    await query.answer("حذف شد", show_alert=True)
    await admin_discounts(update, context)


# ---------- کد هدیه یک‌بارمصرف ----------
async def admin_gift_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, code, volume_gb, days, server_type, max_uses, used_count, is_active
               FROM gift_codes ORDER BY id DESC LIMIT 30"""
        ) as cur:
            rows = await cur.fetchall()

    buttons = []
    if not rows:
        text = (
            "🎁 <b>کدهای هدیه</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "هیچ کد هدیه‌ای وجود ندارد.\n"
            "با دکمه زیر کد جدید بسازید."
        )
    else:
        text = "🎁 <b>کدهای هدیه</b>\n━━━━━━━━━━━━━━━━━━\n"
        for gid, code, vol, days, stype, maxu, used, active in rows:
            status = "✅" if active else "❌"
            limit = "∞" if maxu == 0 else f"{used}/{maxu}"
            sname = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود"}.get(stype, stype)
            text += f"{status} <code>{code}</code> | {vol}G / {days}روز | {sname} | {limit}\n"
            buttons.append([
                InlineKeyboardButton(f"{status} {code}", callback_data=f"toggle_gift_{gid}"),
                InlineKeyboardButton("🗑", callback_data=f"del_gift_{gid}")
            ])
        text += "\nروی کد بزنید تا فعال/غیرفعال شود."

    buttons.append([InlineKeyboardButton("➕ ساخت کد هدیه جدید", callback_data="admin_new_gift")])
    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def admin_new_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🎁 <b>ساخت کد هدیه</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد هدیه را وارد کنید (حروف انگلیسی و عدد، بدون فاصله):\n"
        "مثال: <code>GIFT2026</code> یا <code>VIP1G30D</code>",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_GIFT_CODE


async def admin_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if not code.isalnum() or len(code) < 3 or len(code) > 32:
        await update.message.reply_text(
            "❌ کد باید فقط حروف و عدد انگلیسی باشد (۳ تا ۳۲ کاراکتر). دوباره وارد کنید:"
        )
        return ADMIN_GIFT_CODE
    context.user_data["gift_code"] = code
    await update.message.reply_text(
        f"✅ کد: <code>{code}</code>\n\n"
        f"📦 حجم را به گیگابایت وارد کنید (مثال: 5 یا 10):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_GIFT_VOLUME


async def admin_gift_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        vol = int(update.message.text.strip().replace(",", ""))
        if vol <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ عدد معتبر و بزرگ‌تر از صفر وارد کنید:")
        return ADMIN_GIFT_VOLUME
    context.user_data["gift_volume"] = vol
    await update.message.reply_text(
        f"✅ حجم: <b>{vol}</b> گیگ\n\n"
        f"⏱ تعداد روز اعتبار را وارد کنید (مثال: 30):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_GIFT_DAYS


async def admin_gift_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip().replace(",", ""))
        if days <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ عدد معتبر و بزرگ‌تر از صفر وارد کنید:")
        return ADMIN_GIFT_DAYS
    context.user_data["gift_days"] = days
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 هلند", callback_data="gift_server_holland")],
        [InlineKeyboardButton("🌐 مولتی", callback_data="gift_server_multi")],
        [InlineKeyboardButton("💎 نامحدود", callback_data="gift_server_unlimited")],
        [back_button("admin_gift_codes")],
    ])
    await update.message.reply_text(
        f"✅ روز: <b>{days}</b>\n\n"
        f"🖥 نوع سرور را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )
    return ADMIN_GIFT_SERVER


async def admin_gift_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server = query.data.replace("gift_server_", "")
    if server not in ("holland", "multi", "unlimited"):
        server = "holland"
    context.user_data["gift_server"] = server
    await query.edit_message_text(
        f"✅ سرور: <b>{server}</b>\n\n"
        f"🔢 حداکثر تعداد استفاده از این کد را وارد کنید:\n"
        f"(برای یک‌بارمصرف عدد <b>۱</b> را بفرستید — برای نامحدود <b>۰</b>)",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_GIFT_MAX_USES


async def admin_gift_max_uses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_uses = int(update.message.text.strip())
        if max_uses < 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید (۰ = نامحدود):")
        return ADMIN_GIFT_MAX_USES

    code = context.user_data.get("gift_code")
    vol = context.user_data.get("gift_volume")
    days = context.user_data.get("gift_days")
    server = context.user_data.get("gift_server", "holland")
    if not all([code, vol, days]):
        await update.message.reply_text("❌ اطلاعات ناقص. دوباره از ابتدا شروع کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        try:
            await db.execute(
                """INSERT INTO gift_codes (code, volume_gb, days, server_type, max_uses, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (code, vol, days, server, max_uses, datetime.now().isoformat(), update.effective_user.id)
            )
            await db.commit()
        except Exception:
            await update.message.reply_text(
                "❌ این کد قبلاً وجود دارد. کد دیگری انتخاب کنید.",
                reply_markup=main_keyboard(True)
            )
            return ConversationHandler.END

    sname = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود"}.get(server, server)
    limit_txt = "نامحدود" if max_uses == 0 else str(max_uses)
    await update.message.reply_text(
        f"✅ <b>کد هدیه ساخته شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 کد: <code>{code}</code>\n"
        f"📦 حجم: <b>{vol}</b> گیگ\n"
        f"⏱ روز: <b>{days}</b>\n"
        f"🖥 سرور: {sname}\n"
        f"🔢 ظرفیت: {limit_txt}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    for k in ("gift_code", "gift_volume", "gift_days", "gift_server"):
        context.user_data.pop(k, None)
    return ConversationHandler.END


async def toggle_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    gid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM gift_codes WHERE id = ?", (gid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("یافت نشد", show_alert=True)
            return
        new = 0 if row[0] else 1
        await db.execute("UPDATE gift_codes SET is_active = ? WHERE id = ?", (new, gid))
        await db.commit()
    await query.answer("✅ فعال شد" if new else "❌ غیرفعال شد", show_alert=True)
    await admin_gift_codes(update, context)


async def del_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    gid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM gift_codes WHERE id = ?", (gid,))
        await db.commit()
    await query.answer("🗑 حذف شد", show_alert=True)
    await admin_gift_codes(update, context)


async def redeem_gift_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع استفاده از کد هدیه توسط کاربر"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if await is_banned(user.id):
        await query.edit_message_text("🚫 شما از استفاده از این ربات محروم شده‌اید.")
        return
    if await is_maintenance() and not await is_admin(user.id):
        await query.edit_message_text("🔧 ربات در حالت تعمیرات است.")
        return
    await query.edit_message_text(
        "🎁 <b>استفاده از کد هدیه</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "کد هدیه خود را وارد کنید:\n"
        "مثال: <code>GIFT2026</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button()]])
    )
    return WAITING_GIFT_CODE


async def redeem_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت و اعمال کد هدیه"""
    user = update.effective_user
    code = update.message.text.strip().upper()

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT id, volume_gb, days, server_type, max_uses, used_count, is_active
               FROM gift_codes WHERE code = ?""",
            (code,)
        ) as cur:
            row = await cur.fetchone()

    if not row or not row[6]:
        await update.message.reply_text(
            "❌ کد هدیه معتبر نیست یا غیرفعال است.\nدوباره تلاش کنید یا /start بزنید."
        )
        return WAITING_GIFT_CODE

    gid, vol, days, server, max_uses, used, _ = row
    if max_uses > 0 and used >= max_uses:
        await update.message.reply_text(
            "❌ ظرفیت استفاده از این کد به پایان رسیده است.",
            reply_markup=main_keyboard(await is_admin(user.id))
        )
        return ConversationHandler.END

    # ساخت کانفیگ رایگان
    gift_name = "gift_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    is_unlim = (server == "unlimited")
    try:
        config = await create_config_from_panel(
            gift_name, vol, days=days, is_unlimited=is_unlim, server_type=server
        )
    except Exception as e:
        logger.error(f"redeem_gift create error: {e}")
        await update.message.reply_text(
            f"❌ خطا در ساخت سرویس هدیه.\nلطفاً بعداً تلاش کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=main_keyboard(await is_admin(user.id))
        )
        return ConversationHandler.END

    tracking = generate_tracking_code()
    async with aiosqlite.connect("bot.db") as db:
        cur = await db.execute(
            """INSERT INTO orders (user_id, server_type, volume_gb, price, final_price,
               config_name, status, created_at, panel_username, config_data, tracking_code)
               VALUES (?, ?, ?, 0, 0, ?, 'paid', ?, ?, ?, ?)""",
            (
                user.id, server, vol, config["username"],
                datetime.now().isoformat(), config["username"],
                json.dumps({**config, "type": "gift_code", "gift_code": code}),
                tracking,
            )
        )
        order_id = cur.lastrowid
        await db.execute(
            "UPDATE gift_codes SET used_count = used_count + 1 WHERE id = ?", (gid,)
        )
        await db.commit()

    qr = generate_qr(config["subscription_url"])
    sname = {"holland": "هلند", "multi": "مولتی", "unlimited": "نامحدود"}.get(server, server)
    caption = (
        f"🎁 <b>کد هدیه با موفقیت اعمال شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"کد: <code>{code}</code>\n"
        f"📦 {sname} — {vol} گیگ / {days} روز\n\n"
        f"👤 نام کاربری: <code>{config['username']}</code>\n"
        f"🔗 لینک اشتراک:\n<code>{config['subscription_url']}</code>\n\n"
        f"🔖 کد رهگیری: <code>{tracking}</code>\n"
        f"📦 سفارش: #{order_id}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏳ زمان: {config['expire']}", callback_data="noop")],
        [InlineKeyboardButton(f"📊 حجم: {config['volume']}", callback_data="noop")],
        [
            InlineKeyboardButton("📷 QR CODE", callback_data=f"qr_{order_id}"),
            InlineKeyboardButton("📄 دانلود فایل", callback_data=f"dlcfg_{order_id}"),
        ],
        [InlineKeyboardButton("📖 آموزش استفاده", callback_data=f"guide_{order_id}")],
        [back_button()],
    ])
    await update.message.reply_photo(
        photo=InputFile(qr, "qr.png"),
        caption=caption,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def admin_warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "⚠️ <b>اخطار به کاربر</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "آیدی عددی یا نام کاربری کاربر را وارد کنید:\n"
        "مثال: <code>123456789</code> یا <code>@username</code>",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_WARN_TARGET

async def admin_warn_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_row = None

    async with aiosqlite.connect("bot.db") as db:
        if text.startswith("@"):
            uname = text[1:]
            async with db.execute(
                "SELECT user_id, full_name, username, balance, is_banned, warnings, join_date FROM users WHERE username = ?",
                (uname,)
            ) as cur:
                user_row = await cur.fetchone()
        else:
            try:
                uid = int(text)
            except:
                await update.message.reply_text(
                    "❌ ورودی نامعتبر است.\nآیدی عددی یا @username وارد کنید:"
                )
                return ADMIN_WARN_TARGET
            async with db.execute(
                "SELECT user_id, full_name, username, balance, is_banned, warnings, join_date FROM users WHERE user_id = ?",
                (uid,)
            ) as cur:
                user_row = await cur.fetchone()

    if not user_row:
        await update.message.reply_text(
            "❌ کاربر یافت نشد.\nآیدی یا یوزرنیم را دوباره وارد کنید:"
        )
        return ADMIN_WARN_TARGET

    uid, full_name, username, balance, is_banned, warnings, join_date = user_row
    if uid == ADMIN_ID:
        await update.message.reply_text(
            "🔒 امکان اخطار به مالک ربات وجود ندارد.",
            reply_markup=main_keyboard(True)
        )
        return ConversationHandler.END

    context.user_data["warn_target"] = uid
    warnings = warnings or 0
    banned_text = "🚫 مسدود" if is_banned else "✅ فعال"
    join = join_date[:16].replace("T", " ") if join_date else "—"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ ادامه بدون توضیحات", callback_data="warn_no_note")],
        [back_button("admin_panel")]
    ])
    await update.message.reply_text(
        f"✅ <b>کاربر یافت شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"📛 نام: {full_name or '—'}\n"
        f"🔗 یوزرنیم: @{username or '—'}\n"
        f"💰 موجودی: <b>{balance:,}</b> تومان\n"
        f"📌 وضعیت: {banned_text}\n"
        f"⚠️ اخطارهای فعلی: <b>{warnings}</b> از ۳\n"
        f"📅 عضویت: {join}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 دلیل اخطار را بنویسید و ارسال کنید\n"
        f"یا روی دکمه «ادامه بدون توضیحات» بزنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )
    return ADMIN_WARN_TEXT

async def admin_warn_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("warn_target")
    if not uid:
        await update.message.reply_text("خطا. دوباره تلاش کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    reason = None
    if update.message and update.message.text:
        reason = update.message.text.strip()
        if not reason:
            reason = None

    warnings, was_banned = await issue_warning(
        context.bot, uid, reason=reason, issued_by=update.effective_user.id
    )

    if was_banned:
        confirm = (
            f"🚫 <b>کاربر مسدود شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"کاربر <code>{uid}</code> با دریافت اخطار شماره <b>{warnings}</b> "
            f"به‌طور خودکار از ربات مسدود گردید."
        )
    else:
        confirm = (
            f"⚠️ <b>اخطار ثبت شد</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"اخطار شماره <b>{warnings}</b> از ۳ برای کاربر <code>{uid}</code> ثبت و ارسال شد."
        )
        if reason:
            confirm += f"\n\n📝 دلیل:\n{reason}"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            confirm, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
        )
    else:
        await update.message.reply_text(
            confirm, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(True)
        )
    context.user_data.pop("warn_target", None)
    return ConversationHandler.END

async def admin_warn_no_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await admin_warn_text(update, context)

async def admin_clear_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "🗑 <b>حذف اخطار کاربر</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "آیدی عددی یا نام کاربری کاربر را وارد کنید:\n"
        "مثال: <code>123456789</code> یا <code>@username</code>",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_CLEAR_WARN_TARGET

async def admin_do_clear_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_row = None

    async with aiosqlite.connect("bot.db") as db:
        if text.startswith("@"):
            uname = text[1:]
            async with db.execute(
                "SELECT user_id, full_name, username, warnings, is_banned FROM users WHERE username = ?",
                (uname,)
            ) as cur:
                user_row = await cur.fetchone()
        else:
            try:
                uid = int(text)
            except:
                await update.message.reply_text(
                    "❌ ورودی نامعتبر است.\nآیدی عددی یا @username وارد کنید:"
                )
                return ADMIN_CLEAR_WARN_TARGET
            async with db.execute(
                "SELECT user_id, full_name, username, warnings, is_banned FROM users WHERE user_id = ?",
                (uid,)
            ) as cur:
                user_row = await cur.fetchone()

    if not user_row:
        await update.message.reply_text(
            "❌ کاربر یافت نشد.\nآیدی یا یوزرنیم را دوباره وارد کنید:"
        )
        return ADMIN_CLEAR_WARN_TARGET

    uid, full_name, username, warnings, is_banned = user_row
    warnings = warnings or 0

    if warnings == 0:
        await update.message.reply_text(
            f"ℹ️ کاربر <b>{full_name or uid}</b> (@{username or '—'}) هیچ اخطاری ندارد.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(True)
        )
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET warnings = 0 WHERE user_id = ?", (uid,))
        await db.commit()

    try:
        await context.bot.send_message(
            uid,
            "✅ <b>حذف اخطارها</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "تمام اخطارهای ثبت‌شده برای حساب شما توسط مدیریت پاک شد.\n"
            "لطفاً قوانین ربات را رعایت کنید تا دوباره اخطار دریافت نکنید.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"notify clear warn {uid}: {e}")

    await update.message.reply_text(
        f"✅ <b>اخطارها حذف شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 {full_name or '—'} (@{username or '—'})\n"
        f"🆔 <code>{uid}</code>\n"
        f"⚠️ اخطارهای قبلی: <b>{warnings}</b>\n"
        f"اکنون تعداد اخطارها: <b>۰</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی عددی کاربری که می‌خواهید مسدود کنید را وارد کنید:")
    return ADMIN_BAN

async def admin_do_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست.")
        return ADMIN_BAN
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (uid,))
        await db.commit()
    await log_admin_action(update.effective_user.id, "ban_user", uid)
    await update.message.reply_text(f"✅ کاربر {uid} مسدود شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی عددی کاربری که می‌خواهید رفع مسدودیت کنید را وارد کنید:")
    return ADMIN_UNBAN

async def admin_do_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست.")
        return ADMIN_UNBAN
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (uid,))
        await db.commit()
    await update.message.reply_text(f"✅ کاربر {uid} از مسدودیت خارج شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("پیامی که می‌خواهید به تمام کاربران ارسال شود را بفرستید:")
    return ADMIN_BROADCAST

async def admin_do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT user_id FROM users WHERE is_banned = 0") as cur:
            users = await cur.fetchall()
    success = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_msg_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی عددی کاربری که می‌خواهید بهش پیام بدید را وارد کنید:")
    return ADMIN_MSG_USER_ID

async def admin_msg_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست.")
        return ADMIN_MSG_USER_ID
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
    if not row:
        await update.message.reply_text("کاربر یافت نشد.")
        return ADMIN_MSG_USER_ID
    context.user_data["msg_target"] = uid
    await update.message.reply_text(
        f"کاربر پیدا شد:\nنام: {row[0]}\nیوزرنیم: @{row[1] or '—'}\n\n"
        f"پیامی که می‌خواهید به این کاربر بفرستید را ارسال کنید:"
    )
    return ADMIN_MSG_TEXT

async def admin_msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data["msg_target"]
    try:
        await context.bot.send_message(uid, update.message.text)
        await update.message.reply_text("✅ پیام ارسال شد.", reply_markup=main_keyboard(True))
    except Exception as e:
        await update.message.reply_text(f"خطا در ارسال: {e}")
    return ConversationHandler.END

# ---------- پیام به ادمین‌ها ----------
async def admin_broadcast_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "📣 <b>پیام به تمام ادمین‌ها</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "پیام خود را که می‌خواهید به تمام ادمین‌های فعال ارسال شود بنویسید و ارسال کنید:\n\n"
        "📝 متن پیام را با دقت بنویسید؛ پس از ارسال قابل ویرایش نیست.",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_BROADCAST_ADMINS

async def admin_do_broadcast_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("متن پیام خیلی کوتاه است. دوباره بنویسید:")
        return ADMIN_BROADCAST_ADMINS

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id FROM admins WHERE is_active = 1"
        ) as cur:
            admins = await cur.fetchall()

    # اطمینان از وجود ادمین اصلی در لیست
    admin_ids = {row[0] for row in admins}
    admin_ids.add(ADMIN_ID)

    msg = (
        f"📣 <b>پیام از طرف مدیریت</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{text}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    success = 0
    for uid in admin_ids:
        try:
            await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass

    await update.message.reply_text(
        f"✅ پیام به <b>{success}</b> ادمین ارسال شد.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_msg_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "✉️ <b>پیام به ادمین</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "آیدی عددی یا نام کاربری ادمین را وارد کنید:\n"
        "مثال: <code>123456789</code> یا <code>@username</code>",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MSG_ADMIN_TARGET

async def admin_msg_admin_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_row = None
    uid = None

    async with aiosqlite.connect("bot.db") as db:
        if text.startswith("@"):
            uname = text[1:]
            async with db.execute(
                """SELECT u.user_id, u.full_name, u.username, u.balance, u.is_banned, u.join_date,
                          a.is_active
                   FROM users u
                   INNER JOIN admins a ON u.user_id = a.user_id
                   WHERE u.username = ?""",
                (uname,)
            ) as cur:
                user_row = await cur.fetchone()
        else:
            try:
                uid = int(text)
            except:
                await update.message.reply_text(
                    "❌ ورودی نامعتبر است.\nآیدی عددی یا @username وارد کنید:"
                )
                return ADMIN_MSG_ADMIN_TARGET

            # ادمین اصلی همیشه معتبر است
            if uid == ADMIN_ID:
                async with db.execute(
                    "SELECT user_id, full_name, username, balance, is_banned, join_date FROM users WHERE user_id = ?",
                    (uid,)
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    user_row = (*row, 1)
            else:
                async with db.execute(
                    """SELECT u.user_id, u.full_name, u.username, u.balance, u.is_banned, u.join_date,
                              a.is_active
                       FROM users u
                       INNER JOIN admins a ON u.user_id = a.user_id
                       WHERE u.user_id = ?""",
                    (uid,)
                ) as cur:
                    user_row = await cur.fetchone()

    if not user_row:
        await update.message.reply_text(
            "❌ ادمین یافت نشد.\n"
            "آیدی یا یوزرنیم یک ادمین ثبت‌شده را وارد کنید:"
        )
        return ADMIN_MSG_ADMIN_TARGET

    uid, full_name, username, balance, is_banned, join_date, is_active = user_row
    context.user_data["msg_admin_target"] = uid

    banned_text = "🚫 مسدود" if is_banned else "✅ فعال"
    admin_status = "🟢 ادمین فعال" if is_active else "🔴 ادمین غیرفعال"
    if uid == ADMIN_ID:
        admin_status = "🔒 مالک (ادمین اصلی)"
    join = join_date[:16].replace("T", " ") if join_date else "—"

    await update.message.reply_text(
        f"✅ <b>ادمین یافت شد</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"📛 نام: {full_name or '—'}\n"
        f"🔗 یوزرنیم: @{username or '—'}\n"
        f"💰 موجودی: <b>{balance:,}</b> تومان\n"
        f"📌 وضعیت حساب: {banned_text}\n"
        f"🛡 وضعیت ادمین: {admin_status}\n"
        f"📅 عضویت: {join}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 متن پیام خود را ارسال کنید:",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MSG_ADMIN_TEXT

async def admin_msg_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data.get("msg_admin_target")
    if not uid:
        await update.message.reply_text("خطا. دوباره از ابتدا تلاش کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    text = update.message.text.strip()
    if len(text) < 1:
        await update.message.reply_text("متن پیام خالی است. دوباره بنویسید:")
        return ADMIN_MSG_ADMIN_TEXT

    msg = (
        f"✉️ <b>پیام از طرف مدیریت</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{text}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    try:
        await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
        await update.message.reply_text(
            f"✅ پیام با موفقیت به ادمین <code>{uid}</code> ارسال شد.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(True)
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا در ارسال پیام:\n{e}",
            reply_markup=main_keyboard(True)
        )
    context.user_data.pop("msg_admin_target", None)
    return ConversationHandler.END

async def admin_test_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی کاربری که می‌خواهید اکانت تست آن دوباره شارژ شود را وارد کنید:")
    return ADMIN_TEST_RECHARGE

async def admin_do_test_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست.")
        return ADMIN_TEST_RECHARGE
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET test_used = 0, last_test_at = NULL WHERE user_id = ?", (uid,))
        await db.commit()
    await update.message.reply_text(f"✅ اکانت تست کاربر {uid} دوباره فعال شد.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی کاربری که می‌خواهید موجودی آن را افزایش دهید را وارد کنید:")
    return ADMIN_ADD_BALANCE_ID

async def admin_add_balance_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست.")
        return ADMIN_ADD_BALANCE_ID
    context.user_data["bal_uid"] = uid
    await update.message.reply_text("مبلغ برای شارژ کیف پول کاربر را وارد کنید:")
    return ADMIN_ADD_BALANCE_AMOUNT

async def admin_add_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر و بزرگ‌تر از صفر وارد کنید.")
        return ADMIN_ADD_BALANCE_AMOUNT
    context.user_data["bal_amount"] = amount
    context.user_data["bal_charged"] = False  # جلوگیری از شارژ دوبار
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("ادامه بدون توضیحات", callback_data="bal_no_note")]])
    await update.message.reply_text("آیا می‌خواهید توضیحاتی برای کاربر بدهید؟ (متن را بفرستید یا دکمه را بزنید)", reply_markup=kb)
    return ADMIN_ADD_BALANCE_NOTE

async def admin_add_balance_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # جلوگیری از شارژ دوبار
    if context.user_data.get("bal_charged"):
        if update.callback_query:
            await update.callback_query.answer("این عملیات قبلاً انجام شده است.", show_alert=True)
        else:
            await update.message.reply_text("این عملیات قبلاً انجام شده است.")
        return ConversationHandler.END

    note = None
    # فقط وقتی واقعاً پیام متنی جدید ارسال شده باشد (نه متن پیام قبلی در حالت callback)
    if update.message and update.message.text and not update.callback_query:
        note = update.message.text.strip()
        # اگر متن همان پیام prompt باشد، نادیده بگیر
        if "آیا می‌خواهید توضیحاتی" in note:
            note = None

    uid = context.user_data.get("bal_uid")
    amount = context.user_data.get("bal_amount")
    if not uid or amount is None:
        msg = "❌ اطلاعات ناقص است. دوباره از ابتدا تلاش کنید."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=main_keyboard(True))
        else:
            await update.message.reply_text(msg, reply_markup=main_keyboard(True))
        return ConversationHandler.END

    context.user_data["bal_charged"] = True  # علامت‌گذاری قبل از شارژ

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, uid))
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
            new_balance = row[0] if row else amount

    msg = (
        f"💰 <b>افزایش موجودی حساب</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 مبلغ <b>{amount:,}</b> تومان\n"
        f"از طرف مدیریت به حساب شما واریز شد.\n"
        f"💳 موجودی جدید شما: <b>{new_balance:,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ مبلغ با موفقیت به کیف پول شما اضافه شد.\n"
        f"❤️ از همراهی شما سپاسگزاریم"
    )
    if note:
        msg += f"\n\n📝 {note}"

    try:
        await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
    except:
        pass

    confirm_text = f"✅ موجودی کاربر {uid} به مبلغ {amount:,} تومان افزایش یافت."
    if update.callback_query:
        await update.callback_query.edit_message_text(confirm_text, reply_markup=main_keyboard(True))
    else:
        await update.message.reply_text(confirm_text, reply_markup=main_keyboard(True))

    # پاک کردن داده‌های موقت
    context.user_data.pop("bal_uid", None)
    context.user_data.pop("bal_amount", None)
    context.user_data.pop("bal_charged", None)
    return ConversationHandler.END

async def admin_bal_no_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await admin_add_balance_note(update, context)

async def admin_all_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("مبلغی که می‌خواهید به کیف پول تمام کاربران اضافه شود را وارد کنید:")
    return ADMIN_ALL_BALANCE

async def admin_do_all_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر و بزرگ‌تر از صفر وارد کنید.")
        return ADMIN_ALL_BALANCE

    # جلوگیری از اجرای دوباره در صورت ارسال مجدد مبلغ
    if context.user_data.get("all_bal_charged"):
        await update.message.reply_text("این عملیات قبلاً انجام شده است.", reply_markup=main_keyboard(True))
        return ConversationHandler.END
    context.user_data["all_bal_charged"] = True

    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET balance = balance + ?", (amount,))
        await db.commit()
        async with db.execute("SELECT user_id, balance FROM users WHERE is_banned = 0") as cur:
            users = await cur.fetchall()

    success = 0
    for uid, new_balance in users:
        msg = (
            f"💰 <b>افزایش موجودی حساب</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎁 مبلغ <b>{amount:,}</b> تومان\n"
            f"از طرف مدیریت به حساب شما واریز شد.\n"
            f"💳 موجودی جدید شما: <b>{new_balance:,}</b> تومان\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ مبلغ با موفقیت به کیف پول شما اضافه شد.\n"
            f"❤️ از همراهی شما سپاسگزاریم"
        )
        try:
            await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass

    await update.message.reply_text(
        f"✅ مبلغ {amount:,} تومان به {success} کاربر ارسال و اضافه شد.",
        reply_markup=main_keyboard(True)
    )
    context.user_data.pop("all_bal_charged", None)
    return ConversationHandler.END

async def admin_deduct_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("آیدی کاربری که می‌خواهید موجودی او را کسر کنید را وارد کنید:")
    return ADMIN_DEDUCT_ID

async def admin_deduct_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آیدی معتبر نیست. لطفاً فقط عدد وارد کنید.")
        return ADMIN_DEDUCT_ID

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT full_name, username, balance, is_banned FROM users WHERE user_id = ?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await update.message.reply_text("❌ کاربر یافت نشد. آیدی را دوباره وارد کنید:")
        return ADMIN_DEDUCT_ID

    full_name, username, balance, is_banned = row
    context.user_data["deduct_uid"] = uid
    context.user_data["deduct_balance"] = balance

    banned_text = "🚫 مسدود" if is_banned else "✅ فعال"
    text = (
        f"👤 <b>اطلاعات کاربر</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"📛 نام: {full_name or '—'}\n"
        f"🔗 یوزرنیم: @{username or '—'}\n"
        f"💰 موجودی فعلی: <b>{balance:,}</b> تومان\n"
        f"📌 وضعیت: {banned_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"مبلغی که می‌خواهید کسر کنید را به تومان وارد کنید (مثال: 20000):\n"
        f"یا از دکمه زیر برای کسر <b>کل موجودی</b> استفاده کنید."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 کسر کل موجودی", callback_data="deduct_full_balance")],
        [back_button("admin_panel")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ADMIN_DEDUCT_AMOUNT

async def admin_deduct_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("لطفاً یک عدد معتبر و بزرگ‌تر از صفر وارد کنید.")
        return ADMIN_DEDUCT_AMOUNT

    uid = context.user_data["deduct_uid"]
    current = context.user_data.get("deduct_balance", 0)

    if amount > current:
        amount = current

    if amount == 0:
        await update.message.reply_text("موجودی کاربر صفر است. چیزی برای کسر وجود ندارد.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (amount, uid)
        )
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (uid,)) as cur:
            new_balance = (await cur.fetchone())[0]

    msg = (
        f"📉 <b>کسر موجودی حساب</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 مبلغ <b>{amount:,}</b> تومان\n"
        f"از طرف مدیریت از حساب شما کسر شد.\n"
        f"💳 موجودی جدید شما: <b>{new_balance:,}</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ موجودی شما توسط مدیریت کاهش یافت.\n"
        f"❤️ از همراهی شما سپاسگزاریم"
    )
    try:
        await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
    except:
        pass

    await update.message.reply_text(
        f"✅ مبلغ {amount:,} تومان از موجودی کاربر {uid} کسر شد.\n"
        f"موجودی جدید: {new_balance:,} تومان",
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def deduct_full_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = context.user_data.get("deduct_uid")
    if not uid:
        await query.edit_message_text("خطا: اطلاعات کاربر یافت نشد.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row or row[0] <= 0:
            await query.edit_message_text("موجودی کاربر صفر است.", reply_markup=main_keyboard(True))
            return ConversationHandler.END

        amount = row[0]
        await db.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (uid,))
        await db.commit()

    msg = (
        f"📉 <b>کسر موجودی حساب</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 مبلغ <b>{amount:,}</b> تومان\n"
        f"از طرف مدیریت از حساب شما کسر شد.\n"
        f"💳 موجودی جدید شما: <b>۰</b> تومان\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ کل موجودی شما توسط مدیریت صفر شد.\n"
        f"❤️ از همراهی شما سپاسگزاریم"
    )
    try:
        await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
    except:
        pass

    await query.edit_message_text(
        f"✅ کل موجودی کاربر {uid} ({amount:,} تومان) کسر و صفر شد.",
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_deduct_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, full_name, username, balance FROM users WHERE is_banned = 0 AND balance > 0 ORDER BY balance DESC"
        ) as cur:
            users = await cur.fetchall()

    if not users:
        await query.edit_message_text(
            "هیچ کاربری با موجودی بیشتر از صفر یافت نشد.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return

    text = "📉 <b>لیست کاربران دارای موجودی</b>\n━━━━━━━━━━━━━━━━━━\n"
    total = 0
    for uid, name, uname, bal in users[:50]:
        total += bal
        text += f"• {name or '—'} (@{uname or '—'}) | <code>{uid}</code>\n  💰 {bal:,} تومان\n"

    if len(users) > 50:
        text += f"\n... و {len(users) - 50} کاربر دیگر\n"

    text += f"\n━━━━━━━━━━━━━━━━━━\n📊 مجموع کل: <b>{total:,}</b> تومان\n👥 تعداد: {len(users)} نفر"
    text += "\n\n⚠️ با زدن دکمه زیر، <b>کل موجودی همه کاربران</b> صفر می‌شود."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ کسر کل موجودی همه کاربران", callback_data="confirm_deduct_all")],
        [back_button("admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def confirm_deduct_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT user_id, balance FROM users WHERE is_banned = 0 AND balance > 0"
        ) as cur:
            users = await cur.fetchall()

        await db.execute("UPDATE users SET balance = 0 WHERE is_banned = 0")
        await db.commit()

    success = 0
    for uid, amount in users:
        msg = (
            f"📉 <b>کسر موجودی حساب</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💸 مبلغ <b>{amount:,}</b> تومان\n"
            f"از طرف مدیریت از حساب شما کسر شد.\n"
            f"💳 موجودی جدید شما: <b>۰</b> تومان\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ مدیریت کل موجودی حساب شما را صفر کرد.\n"
            f"❤️ از همراهی شما سپاسگزاریم"
        )
        try:
            await context.bot.send_message(uid, msg, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass

    await query.edit_message_text(
        f"✅ موجودی {success} کاربر صفر شد و به همه اطلاع‌رسانی گردید.",
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT o.id, o.user_id, o.server_type, o.volume_gb, o.final_price, o.config_name, o.created_at,
                      u.full_name, u.username
               FROM orders o
               LEFT JOIN users u ON o.user_id = u.user_id
               WHERE o.status = 'pending'
               ORDER BY o.id DESC LIMIT 20"""
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "✅ هیچ سفارش در انتظاری وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return

    buttons = []
    text = "⏳ <b>سفارشات در انتظار</b>\n━━━━━━━━━━━━━━━━━━\n"
    for oid, uid, server, vol, price, conf_name, created, full_name, username in rows:
        if server == "holland":
            server_name = "هلند"
            plan = f"{vol}G"
        elif server == "unlimited":
            server_name = "نامحدود"
            plan = f"{vol}م"
        elif server == "custom":
            server_name = "دلخواه"
            plan = f"{vol}G"
        else:
            server_name = "مولتی"
            plan = f"{vol}G"
        text += (
            f"#{oid} | {server_name} {plan} | {price:,} ت\n"
            f"👤 {full_name or '—'} (@{username or '—'}) | <code>{uid}</code>\n"
            f"🕐 {created[:16].replace('T', ' ') if created else '—'}\n"
            f"—————————————\n"
        )
        buttons.append([
            InlineKeyboardButton(f"✅ #{oid}", callback_data=f"approve_order_{oid}"),
            InlineKeyboardButton(f"❌ #{oid}", callback_data=f"reject_order_{oid}")
        ])

    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 آیدی عددی یا یوزرنیم کاربر را وارد کنید:\n"
        "(مثال: 123456789 یا @username)"
    )
    return ADMIN_SEARCH_USER

async def admin_do_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_row = None

    async with aiosqlite.connect("bot.db") as db:
        if text.startswith("@"):
            uname = text[1:]
            async with db.execute(
                "SELECT user_id, full_name, username, balance, is_banned, join_date, test_used, referral_code FROM users WHERE username = ?",
                (uname,)
            ) as cur:
                user_row = await cur.fetchone()
        else:
            try:
                uid = int(text)
                async with db.execute(
                    "SELECT user_id, full_name, username, balance, is_banned, join_date, test_used, referral_code FROM users WHERE user_id = ?",
                    (uid,)
                ) as cur:
                    user_row = await cur.fetchone()
            except:
                await update.message.reply_text("آیدی معتبر نیست. دوباره تلاش کنید:")
                return ADMIN_SEARCH_USER

        if not user_row:
            await update.message.reply_text("❌ کاربر یافت نشد. دوباره وارد کنید:")
            return ADMIN_SEARCH_USER

        uid, full_name, username, balance, is_banned, join_date, test_used, ref_code = user_row

        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'paid'", (uid,)
        ) as cur:
            paid_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'pending'", (uid,)
        ) as cur:
            pending_count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COALESCE(SUM(final_price), 0) FROM orders WHERE user_id = ? AND status = 'paid'", (uid,)
        ) as cur:
            user_revenue = (await cur.fetchone())[0]

    banned_text = "🚫 مسدود" if is_banned else "✅ فعال"
    test_text = "بله" if test_used else "خیر"
    join = join_date[:16].replace("T", " ") if join_date else "—"

    msg = (
        f"🔍 <b>نتیجه جستجو</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"📛 نام: {full_name or '—'}\n"
        f"🔗 یوزرنیم: @{username or '—'}\n"
        f"💰 موجودی: <b>{balance:,}</b> تومان\n"
        f"📌 وضعیت: {banned_text}\n"
        f"🧪 تست استفاده شده: {test_text}\n"
        f"🎁 کد دعوت: <code>{ref_code}</code>\n"
        f"📅 تاریخ عضویت: {join}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ سفارشات پرداخت‌شده: {paid_count}\n"
        f"⏳ سفارشات در انتظار: {pending_count}\n"
        f"💵 مجموع خرید: {user_revenue:,} تومان\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 مشاهده خریدها و کد رهگیری", callback_data=f"admin_user_orders_{uid}")],
        [back_button("admin_panel")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def send_db_backup(bot, chat_id: int = None, caption_prefix: str = "💾 بک‌آپ دیتابیس") -> bool:
    """ارسال فایل bot.db به چت مشخص (پیش‌فرض: ادمین اصلی)"""
    target = chat_id or ADMIN_ID
    try:
        if not os.path.exists("bot.db"):
            await bot.send_message(target, "❌ فایل bot.db یافت نشد.")
            return False
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        with open("bot.db", "rb") as f:
            await bot.send_document(
                chat_id=target,
                document=InputFile(f, filename=f"bot_backup_{stamp}.db"),
                caption=(
                    f"{caption_prefix}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"📦 اندازه: {os.path.getsize('bot.db') / 1024:.1f} KB"
                ),
                parse_mode=ParseMode.HTML,
            )
        return True
    except Exception as e:
        logger.error(f"send_db_backup: {e}")
        try:
            await bot.send_message(target, f"❌ خطا در ارسال بک‌آپ:\n{str(e)[:200]}")
        except Exception:
            pass
        return False


async def auto_backup_db(context: ContextTypes.DEFAULT_TYPE):
    """جاب روزانه: بک‌آپ خودکار دیتابیس برای ادمین"""
    try:
        ok = await send_db_backup(
            context.bot,
            ADMIN_ID,
            caption_prefix="💾 <b>بک‌آپ خودکار روزانه</b>",
        )
        if ok:
            logger.info("Auto DB backup sent to admin.")
    except Exception as e:
        logger.error(f"auto_backup_db: {e}")


async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    try:
        ok = await send_db_backup(context.bot, query.from_user.id)
        if ok:
            await query.edit_message_text(
                "✅ فایل بک‌آپ دیتابیس ارسال شد.",
                reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
            )
        else:
            await query.edit_message_text(
                "❌ ارسال بک‌آپ ناموفق بود.",
                reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
            )
    except Exception as e:
        await query.edit_message_text(
            f"❌ خطا در ارسال بک‌آپ: {e}",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )

async def admin_pending_charges(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            """SELECT c.id, c.user_id, c.amount, c.created_at, u.full_name, u.username
               FROM wallet_charges c
               LEFT JOIN users u ON c.user_id = u.user_id
               WHERE c.status = 'pending'
               ORDER BY c.id DESC LIMIT 20"""
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await query.edit_message_text(
            "✅ هیچ درخواست شارژی در انتظار نیست.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
        )
        return

    buttons = []
    text = "💳 <b>شارژهای در انتظار</b>\n━━━━━━━━━━━━━━━━━━\n"
    for cid, uid, amount, created, full_name, username in rows:
        text += (
            f"#{cid} | {amount:,} تومان\n"
            f"👤 {full_name or '—'} (@{username or '—'}) | <code>{uid}</code>\n"
            f"🕐 {created[:16].replace('T', ' ') if created else '—'}\n"
            f"—————————————\n"
        )
        buttons.append([
            InlineKeyboardButton(f"✅ #{cid}", callback_data=f"approve_charge_{cid}"),
            InlineKeyboardButton(f"❌ #{cid}", callback_data=f"reject_charge_{cid}")
        ])

    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    bonus = await get_int_setting("referral_bonus", 5000)
    min_charge = await get_int_setting("min_charge", 10000)
    service_days = await get_int_setting("service_days", 30)
    test_mb = await get_int_setting("test_volume_mb", 30)
    maint_text = await get_maintenance_info()
    channels = await get_join_channels(active_only=True)
    ch_count = len(channels)
    ch_preview = "، ".join([c[1] for c in channels[:3]]) if channels else "ندارد"
    if ch_count > 3:
        ch_preview += f" و {ch_count - 3} مورد دیگر"

    text = (
        f"⚙️ <b>تنظیمات عمومی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎁 هدیه رفرال: <b>{bonus:,}</b> تومان\n"
        f"💵 حداقل شارژ کیف پول: <b>{min_charge:,}</b> تومان\n"
        f"⏱ مدت اعتبار سرویس: <b>{service_days}</b> روز\n"
        f"🧪 حجم اکانت تست: <b>{test_mb}</b> مگابایت\n"
        f"🔧 حالت تعمیرات: <b>{maint_text}</b>\n"
        f"📢 کانال‌های جوین اجباری: <b>{ch_count}</b> عدد\n"
        f"   {ch_preview}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"برای تغییر هر مورد، روی دکمه مربوطه بزنید:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 تغییر هدیه رفرال", callback_data="admin_set_referral")],
        [InlineKeyboardButton("💵 تغییر حداقل شارژ", callback_data="admin_set_min_charge")],
        [InlineKeyboardButton("⏱ تغییر مدت سرویس", callback_data="admin_set_service_days")],
        [InlineKeyboardButton("🧪 تغییر حجم اکانت تست", callback_data="admin_set_test_volume")],
        [InlineKeyboardButton("🔧 مدیریت تعمیرات (دستی/زمان‌دار)", callback_data="admin_toggle_maintenance")],
        [InlineKeyboardButton("📢 مدیریت کانال‌های جوین اجباری", callback_data="admin_manage_channels")],
        [InlineKeyboardButton("🔄 ریست تست همه کاربران", callback_data="admin_reset_all_tests")],
        [InlineKeyboardButton("🖥 مدیریت پنل‌ها", callback_data="admin_panels")],
        [InlineKeyboardButton("🔌 تست اتصال پنل‌ها", callback_data="admin_test_panels")],
        [back_button("admin_panel")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_set_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await get_int_setting("referral_bonus", 5000)
    await query.edit_message_text(
        f"🎁 هدیه رفرال فعلی: <b>{current:,}</b> تومان\n\n"
        f"مبلغ جدید را به تومان وارد کنید (مثال: 10000):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_SET_REFERRAL

async def admin_do_set_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        if amount < 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_SET_REFERRAL

    await set_setting("referral_bonus", str(amount))
    await update.message.reply_text(
        f"✅ هدیه رفرال به <b>{amount:,}</b> تومان تغییر یافت.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_set_min_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await get_int_setting("min_charge", 10000)
    await query.edit_message_text(
        f"💵 حداقل شارژ فعلی: <b>{current:,}</b> تومان\n\n"
        f"مبلغ جدید را به تومان وارد کنید (مثال: 20000):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_SET_MIN_CHARGE

async def admin_do_set_min_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(",", ""))
        if amount < 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر وارد کنید.")
        return ADMIN_SET_MIN_CHARGE

    await set_setting("min_charge", str(amount))
    await update.message.reply_text(
        f"✅ حداقل مبلغ شارژ به <b>{amount:,}</b> تومان تغییر یافت.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_set_service_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = await get_int_setting("service_days", 30)
    await query.edit_message_text(
        f"⏱ مدت اعتبار فعلی: <b>{current}</b> روز\n\n"
        f"تعداد روز جدید را وارد کنید (مثال: 30):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_SET_SERVICE_DAYS

async def admin_do_set_service_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text.strip())
        if days <= 0:
            raise ValueError
    except:
        await update.message.reply_text("عدد معتبر و بزرگ‌تر از صفر وارد کنید.")
        return ADMIN_SET_SERVICE_DAYS
    await set_setting("service_days", str(days))
    await update.message.reply_text(
        f"✅ مدت اعتبار سرویس به <b>{days}</b> روز تغییر یافت.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_set_test_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    current = await get_int_setting("test_volume_mb", 30)
    await query.edit_message_text(
        f"🧪 <b>تغییر حجم اکانت تست</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"حجم جدید اکانت تست را وارد کنید:\n"
        f"(مثال: <code>40</code> → یعنی ۴۰ مگابایت)\n\n"
        f"📦 حجم فعلی: <b>{current}</b> مگابایت",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_settings")]])
    )
    return ADMIN_SET_TEST_VOLUME

async def admin_do_set_test_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mb = int(update.message.text.strip().replace(",", "").replace("مگ", "").replace("mb", "").replace("MB", ""))
        if mb <= 0:
            raise ValueError
    except:
        await update.message.reply_text(
            "❌ عدد معتبر و بزرگ‌تر از صفر وارد کنید (مثال: 40):"
        )
        return ADMIN_SET_TEST_VOLUME

    await set_setting("test_volume_mb", str(mb))
    await update.message.reply_text(
        f"✅ حجم اکانت تست به <b>{mb}</b> مگابایت تغییر یافت.\n\n"
        f"از این لحظه اکانت‌های تست جدید با این حجم ساخته می‌شوند.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    return ConversationHandler.END

async def admin_manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    rows = await get_join_channels(active_only=False)
    buttons = []
    if not rows:
        text = (
            "📢 <b>مدیریت کانال‌های جوین اجباری</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "هیچ کانالی ثبت نشده است.\n"
            "با دکمه زیر کانال جدید اضافه کنید."
        )
    else:
        text = "📢 <b>کانال‌های جوین اجباری</b>\n━━━━━━━━━━━━━━━━━━\n"
        for cid, channel, active in rows:
            status = "🟢 فعال" if active else "🔴 غیرفعال"
            text += f"{status} | <code>{channel}</code>\n"
            btn_label = "✅ فعال" if active else "❌ غیرفعال"
            buttons.append([
                InlineKeyboardButton(f"{btn_label} {channel}", callback_data=f"toggle_channel_{cid}"),
                InlineKeyboardButton("🗑", callback_data=f"del_channel_{cid}")
            ])
        text += "━━━━━━━━━━━━━━━━━━\nروی دکمه فعال/غیرفعال یا 🗑 بزنید."

    buttons.append([InlineKeyboardButton("➕ اضافه کردن کانال", callback_data="admin_add_channel")])
    buttons.append([back_button("admin_settings")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "📢 <b>اضافه کردن کانال جوین اجباری</b>\n\n"
        "یوزرنیم یا آیدی عددی کانال را ارسال کنید:\n"
        "• مثال یوزرنیم: <code>@mychannel</code>\n"
        "• مثال آیدی عددی: <code>-1001234567890</code>\n\n"
        "⚠️ ربات باید در کانال ادمین باشد.",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_SET_CHANNEL

async def admin_do_set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # تشخیص آیدی عددی یا یوزرنیم
    if text.lstrip("-").isdigit():
        channel = text  # آیدی عددی (مثل -100...)
    else:
        channel = text.lstrip("@").strip()
        if not channel or " " in channel or not channel.replace("_", "").isalnum():
            await update.message.reply_text(
                "❌ نامعتبر است.\n"
                "یوزرنیم (مثال: @mychannel) یا آیدی عددی (مثال: -1001234567890) وارد کنید:"
            )
            return ADMIN_SET_CHANNEL
        channel = "@" + channel

    # بررسی ادمین بودن ربات در کانال
    if not await is_bot_admin_in_channel(context.bot, channel):
        await update.message.reply_text(
            f"❌ <b>ربات ادمین کانال نیست</b>\n\n"
            f"کانال: <code>{channel}</code>\n\n"
            f"ابتدا ربات را در کانال ادمین کنید، سپس دوباره اضافه کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_channels")]
            ])
        )
        return ConversationHandler.END

    async with aiosqlite.connect("bot.db") as db:
        try:
            await db.execute(
                "INSERT INTO join_channels (channel, is_active, added_at) VALUES (?, 1, ?)",
                (channel, datetime.now().isoformat())
            )
            await db.commit()
        except Exception:
            await update.message.reply_text(
                "❌ این کانال قبلاً ثبت شده است.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_channels")]
                ])
            )
            return ConversationHandler.END

    await update.message.reply_text(
        f"✅ کانال <b>{channel}</b> با موفقیت اضافه شد.\n"
        f"کاربران برای استفاده از ربات باید در این کانال عضو باشند.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 مدیریت کانال‌ها", callback_data="admin_manage_channels")],
            [back_button("admin_settings")]
        ])
    )
    return ConversationHandler.END

async def toggle_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    cid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM join_channels WHERE id = ?", (cid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("کانال یافت نشد", show_alert=True)
            return
        new = 0 if row[0] else 1
        await db.execute("UPDATE join_channels SET is_active = ? WHERE id = ?", (new, cid))
        await db.commit()
    await query.answer("✅ فعال شد" if new else "❌ غیرفعال شد", show_alert=True)
    await admin_manage_channels(update, context)

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    cid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM join_channels WHERE id = ?", (cid,))
        await db.commit()
    await query.answer("🗑 کانال حذف شد", show_alert=True)
    await admin_manage_channels(update, context)

async def admin_reset_all_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("UPDATE users SET test_used = 0, last_test_at = NULL")
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            count = (await cur.fetchone())[0]
    await query.edit_message_text(
        f"✅ اکانت تست {count} کاربر ریست شد.\nهمه می‌توانند دوباره تست بگیرند.",
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panel")]])
    )

async def test_panel_connection(panel: dict) -> tuple:
    """تست اتصال به پنل. برمی‌گرداند: (موفق؟, پیام)"""
    name = panel.get("name") or panel.get("panel_type") or "?"
    url = (panel.get("url") or "").rstrip("/")
    if not url:
        return False, f"{name}: آدرس پنل خالی است"
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            login_res = await client.post(
                f"{url}/api/admin/token",
                data={"username": panel["username"], "password": panel["password"]},
            )
            if login_res.status_code != 200:
                return False, f"{name}: لاگین ناموفق (HTTP {login_res.status_code})"
            token = login_res.json().get("access_token")
            if not token:
                return False, f"{name}: توکن دریافت نشد"
            headers = {"Authorization": f"Bearer {token}"}
            try:
                ping = await client.get(f"{url}/api/system", headers=headers)
                if ping.status_code == 401:
                    return False, f"{name}: توکن نامعتبر"
            except Exception:
                pass
            return True, f"{name}: متصل"
    except httpx.TimeoutException:
        return False, f"{name}: تایم‌اوت اتصال"
    except Exception as e:
        err = str(e)[:80]
        return False, f"{name}: خطا — {err}"


async def admin_test_panels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تست اتصال به پنل‌های پاسارگاد / سنایی / مرزبان / تست"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    await query.edit_message_text("🔄 در حال تست اتصال به پنل‌ها... لطفاً صبر کنید.")

    types_order = [
        ("holland", "🇳🇱 پاسارگاد (هلند)"),
        ("multi", "🌐 سنایی (مولتی)"),
        ("unlimited", "💎 مرزبان (نامحدود)"),
        ("test", "🧪 پنل تست"),
    ]
    lines = ["🖥 <b>وضعیت اتصال پنل‌ها</b>", "━━━━━━━━━━━━━━━━━━"]
    ok_count = 0
    for ptype, label in types_order:
        panel = await get_panel(ptype)
        if not panel.get("name") or panel.get("name") == "پیش‌فرض":
            panel = dict(panel)
            panel["name"] = label
        success, msg = await test_panel_connection(panel)
        if success:
            ok_count += 1
            lines.append(f"✅ {label}")
            lines.append(f"   🔗 {(panel.get('url') or '')[:50]}")
        else:
            lines.append(f"❌ {label}")
            lines.append(f"   {msg}")
        lines.append("—————————————")

    lines.append(f"نتیجه: <b>{ok_count}</b> از {len(types_order)} پنل سالم")
    text_msg = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تست مجدد", callback_data="admin_test_panels")],
        [InlineKeyboardButton("🖥 مدیریت پنل‌ها", callback_data="admin_panels")],
        [back_button("admin_settings")],
    ])
    try:
        await query.edit_message_text(text_msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await context.bot.send_message(query.from_user.id, text_msg, reply_markup=kb, parse_mode=ParseMode.HTML)


async def admin_panels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT id, name, panel_type, url, is_active FROM panels ORDER BY id") as cur:
            rows = await cur.fetchall()
    text = "🖥 <b>مدیریت پنل‌ها</b>\n━━━━━━━━━━━━━━━━━━\n"
    buttons = []
    if not rows:
        text += "هیچ پنلی ثبت نشده.\n"
    else:
        type_names = {
            "holland": "🇳🇱 هلند / پاسارگاد",
            "multi": "🌐 مولتی / سنایی",
            "unlimited": "💎 نامحدود / مرزبان",
            "test": "🧪 اکانت تست",
            "main": "🇳🇱 هلند (قدیمی)",
        }
        for pid, name, ptype, url, active in rows:
            type_name = type_names.get(ptype, ptype or "—")
            status = "✅" if active else "❌"
            text += f"{status} {name}\n📌 {type_name}\n🔗 {(url or '')[:40]}...\n—————————————\n"
            buttons.append([
                InlineKeyboardButton(f"{status} {name}", callback_data=f"toggle_panel_{pid}"),
                InlineKeyboardButton("🗑", callback_data=f"del_panel_{pid}")
            ])
    buttons.append([InlineKeyboardButton("➕ افزودن پنل جدید", callback_data="admin_add_panel")])
    buttons.append([back_button("admin_settings")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def admin_add_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ افزودن پنل جدید\n\n"
        "نام پنل را وارد کنید (مثال: Pasarguard اصلی):"
    )
    return ADMIN_PANEL_NAME

async def admin_panel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("نام معتبر وارد کنید:")
        return ADMIN_PANEL_NAME
    context.user_data["panel_name"] = name
    await update.message.reply_text("آدرس پنل را وارد کنید (مثال: https://panel.example.com):")
    return ADMIN_PANEL_URL

async def admin_panel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip().rstrip("/")
    if not url.startswith("http"):
        await update.message.reply_text("آدرس باید با http یا https شروع شود. دوباره وارد کنید:")
        return ADMIN_PANEL_URL
    context.user_data["panel_url"] = url
    await update.message.reply_text("نام کاربری پنل را وارد کنید:")
    return ADMIN_PANEL_USER

async def admin_panel_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if not username:
        await update.message.reply_text("نام کاربری معتبر وارد کنید:")
        return ADMIN_PANEL_USER
    context.user_data["panel_user"] = username
    await update.message.reply_text("رمز عبور پنل را وارد کنید:")
    return ADMIN_PANEL_PASS

async def admin_panel_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if not password:
        await update.message.reply_text("رمز عبور معتبر وارد کنید:")
        return ADMIN_PANEL_PASS
    context.user_data["panel_pass"] = password

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 هلند (پاسارگاد)", callback_data="panel_type_holland")],
        [InlineKeyboardButton("🌐 مولتی (سنایی)", callback_data="panel_type_multi")],
        [InlineKeyboardButton("💎 نامحدود (مرزبان)", callback_data="panel_type_unlimited")],
        [InlineKeyboardButton("🧪 اکانت تست", callback_data="panel_type_test")],
        [back_button("admin_panels")]
    ])
    await update.message.reply_text(
        "این پنل برای چه موردی استفاده شود؟\n\n"
        "🇳🇱 هلند → پنل پاسارگاد\n"
        "🌐 مولتی → پنل سنایی\n"
        "💎 نامحدود → پنل مرزبان\n"
        "🧪 تست → اکانت تست",
        reply_markup=kb
    )
    return ConversationHandler.END

async def admin_panel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    raw = query.data.replace("panel_type_", "")
    ptype = raw if raw in ("holland", "multi", "unlimited", "test") else "holland"
    name = context.user_data.get("panel_name", "بدون نام")
    url = context.user_data.get("panel_url", "")
    username = context.user_data.get("panel_user", "")
    password = context.user_data.get("panel_pass", "")

    if not all([name, url, username, password]):
        await query.edit_message_text(
            "❌ اطلاعات ناقص است. دوباره از ابتدا شروع کنید.",
            reply_markup=InlineKeyboardMarkup([[back_button("admin_panels")]])
        )
        return

    async with aiosqlite.connect("bot.db") as db:
        await db.execute(
            "INSERT INTO panels (name, url, username, password, panel_type) VALUES (?, ?, ?, ?, ?)",
            (name, url, username, password, ptype)
        )
        await db.commit()

    type_names = {
        "holland": "🇳🇱 هلند (پاسارگاد)",
        "multi": "🌐 مولتی (سنایی)",
        "unlimited": "💎 نامحدود (مرزبان)",
        "test": "🧪 اکانت تست",
    }
    type_name = type_names.get(ptype, ptype)
    await query.edit_message_text(
        f"✅ پنل با موفقیت اضافه شد.\n\n"
        f"📛 نام: {name}\n"
        f"📌 نوع: {type_name}\n"
        f"🔗 آدرس: {url}",
        reply_markup=InlineKeyboardMarkup([[back_button("admin_panels")]])
    )
    context.user_data.clear()

async def toggle_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute("SELECT is_active FROM panels WHERE id = ?", (pid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("پنل یافت نشد", show_alert=True)
            return
        new = 0 if row[0] else 1
        await db.execute("UPDATE panels SET is_active = ? WHERE id = ?", (new, pid))
        await db.commit()
    await query.answer("✅ فعال شد" if new else "❌ غیرفعال شد", show_alert=True)
    await admin_panels(update, context)

async def del_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = int(query.data.split("_")[-1])
    async with aiosqlite.connect("bot.db") as db:
        await db.execute("DELETE FROM panels WHERE id = ?", (pid,))
        await db.commit()
    await query.answer("🗑 پنل حذف شد", show_alert=True)
    await admin_panels(update, context)

# ---------- مدیریت پروکسی (ادمین) ----------
async def admin_proxy_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 پروکسی لوکیشن هلند", callback_data="admin_proxy_charge_holland")],
        [InlineKeyboardButton("🇺🇸 پروکسی لوکیشن آمریکا", callback_data="admin_proxy_charge_america")],
        [InlineKeyboardButton("🇸🇬 پروکسی لوکیشن سنگاپور", callback_data="admin_proxy_charge_singapore")],
        [back_button("admin_panel")]
    ])
    stock_lines = []
    for loc_key, loc_info in PROXY_LOCATIONS.items():
        cnt = await get_proxy_stock_count(loc_key)
        warn = " ⚠️ کم" if cnt < PROXY_LOW_STOCK_THRESHOLD else ""
        stock_lines.append(f"{loc_info['name']}: <b>{cnt}</b>{warn}")
    stock_text = "\n".join(stock_lines)
    await query.edit_message_text(
        "🌐 <b>شارژ پروکسی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>موجودی فعلی انبار</b>\n{stock_text}\n"
        f"(آستانه هشدار: {PROXY_LOW_STOCK_THRESHOLD})\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "لوکیشن مورد نظر برای شارژ انبار را انتخاب کنید:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

async def admin_proxy_charge_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    location = query.data.replace("admin_proxy_charge_", "")
    if location not in PROXY_LOCATIONS:
        await query.answer("لوکیشن نامعتبر", show_alert=True)
        return
    context.user_data["admin_proxy_charge_loc"] = location
    loc_name = PROXY_LOCATIONS[location]["name"]
    stock = await get_proxy_stock_count(location)
    await query.edit_message_text(
        f"🌐 <b>شارژ پروکسی {loc_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 موجودی فعلی انبار: <b>{stock}</b> عدد\n\n"
        f"پروکسی‌های این لوکیشن را ارسال کنید.\n"
        f"هر خط = یک پروکسی (مثال):\n"
        f"<code>ip:port:user:pass</code>\n"
        f"یا\n"
        f"<code>socks5://user:pass@ip:port</code>\n\n"
        f"می‌توانید چند خط متن بفرستید یا یک فایل <b>.txt</b> آپلود کنید.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[back_button("admin_proxy_charge")]])
    )
    return ADMIN_PROXY_CHARGE

async def admin_receive_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = context.user_data.get("admin_proxy_charge_loc")
    if not location:
        await update.message.reply_text("خطا. دوباره از پنل شروع کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    text = ""
    if update.message.document:
        doc = update.message.document
        file_name = (doc.file_name or "").lower()
        mime = (doc.mime_type or "").lower()
        if not (file_name.endswith(".txt") or mime in ("text/plain", "application/octet-stream")):
            await update.message.reply_text(
                "❌ فقط فایل متنی با پسوند <b>.txt</b> مجاز است.\n"
                "یا پروکسی‌ها را به صورت متن چندخطی ارسال کنید.",
                parse_mode=ParseMode.HTML,
            )
            return ADMIN_PROXY_CHARGE
        try:
            tg_file = await doc.get_file()
            data = await tg_file.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"proxy file download: {e}")
            await update.message.reply_text("❌ خطا در خواندن فایل. دوباره تلاش کنید:")
            return ADMIN_PROXY_CHARGE
    elif update.message.text:
        text = update.message.text.strip()
    else:
        await update.message.reply_text(
            "❌ متن یا فایل .txt ارسال کنید:"
        )
        return ADMIN_PROXY_CHARGE

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        await update.message.reply_text("❌ هیچ پروکسی معتبری یافت نشد. دوباره ارسال کنید:")
        return ADMIN_PROXY_CHARGE

    async with aiosqlite.connect("bot.db") as db:
        now = datetime.now().isoformat()
        for proxy in lines:
            await db.execute(
                "INSERT INTO proxy_stock (location, proxy_text, is_sold, created_at) VALUES (?, ?, 0, ?)",
                (location, proxy, now)
            )
        await db.commit()

    loc_name = PROXY_LOCATIONS[location]["name"]
    new_stock = await get_proxy_stock_count(location)
    await update.message.reply_text(
        f"✅ <b>{len(lines)}</b> پروکسی برای لوکیشن {loc_name} به انبار اضافه شد.\n"
        f"📦 موجودی جدید: <b>{new_stock}</b> عدد",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    context.user_data.pop("admin_proxy_charge_loc", None)
    return ConversationHandler.END


# ---------- مدیریت / حذف پروکسی از انبار ----------
async def admin_proxy_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب لوکیشن برای مشاهده و حذف پروکسی‌های انبار"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    stock_lines = []
    buttons = []
    for loc_key, loc_info in PROXY_LOCATIONS.items():
        cnt = await get_proxy_stock_count(loc_key)
        warn = " ⚠️" if cnt < PROXY_LOW_STOCK_THRESHOLD else ""
        stock_lines.append(f"{loc_info['name']}: <b>{cnt}</b>{warn}")
        buttons.append([
            InlineKeyboardButton(
                f"{loc_info['name']} ({cnt})",
                callback_data=f"admin_proxy_stock_list_{loc_key}_0"
            )
        ])

    buttons.append([back_button("admin_panel")])
    await query.edit_message_text(
        "🗑 <b>مدیریت انبار پروکسی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(stock_lines)
        + "\n━━━━━━━━━━━━━━━━━━\n"
        "لوکیشن را انتخاب کنید تا لیست پروکسی‌های فروخته‌نشده را ببینید و حذف کنید:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def admin_proxy_stock_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست صفحه‌بندی‌شده پروکسی‌های یک لوکیشن + دکمه حذف"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    # callback: admin_proxy_stock_list_{location}_{page}
    parts = query.data.split("_")
    try:
        location = parts[4]
        page = int(parts[5]) if len(parts) > 5 else 0
    except Exception:
        await query.answer("داده نامعتبر", show_alert=True)
        return

    if location not in PROXY_LOCATIONS:
        await query.answer("لوکیشن نامعتبر", show_alert=True)
        return

    PAGE_SIZE = 8
    if page < 0:
        page = 0
    offset = page * PAGE_SIZE
    loc_name = PROXY_LOCATIONS[location]["name"]

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM proxy_stock WHERE location = ? AND is_sold = 0",
            (location,),
        ) as cur:
            total = (await cur.fetchone())[0] or 0

        async with db.execute(
            """SELECT id, proxy_text, created_at FROM proxy_stock
               WHERE location = ? AND is_sold = 0
               ORDER BY id DESC LIMIT ? OFFSET ?""",
            (location, PAGE_SIZE, offset),
        ) as cur:
            rows = await cur.fetchall()

    if total == 0:
        await query.edit_message_text(
            f"📦 انبار {loc_name} خالی است.",
            reply_markup=InlineKeyboardMarkup([
                [back_button("admin_proxy_stock")],
                [back_button("admin_panel")],
            ]),
        )
        return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
        offset = page * PAGE_SIZE
        async with aiosqlite.connect("bot.db") as db:
            async with db.execute(
                """SELECT id, proxy_text, created_at FROM proxy_stock
                   WHERE location = ? AND is_sold = 0
                   ORDER BY id DESC LIMIT ? OFFSET ?""",
                (location, PAGE_SIZE, offset),
            ) as cur:
                rows = await cur.fetchall()

    text_msg = (
        f"🗑 <b>انبار {loc_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 موجودی: <b>{total}</b> عدد\n"
        f"📄 صفحه {page + 1} از {total_pages}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"روی 🗑 بزنید تا آن پروکسی حذف شود:\n"
    )

    buttons = []
    for pid, proxy_text, created in rows:
        preview = (proxy_text or "")[:40]
        if len(proxy_text or "") > 40:
            preview += "…"
        preview = preview.replace("<", "‹").replace(">", "›")
        buttons.append([
            InlineKeyboardButton(f"#{pid} {preview}", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"del_proxy_stock_{pid}_{location}_{page}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_proxy_stock_list_{location}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"admin_proxy_stock_list_{location}_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(
            f"⚠️ پاک کردن همه ({total})",
            callback_data=f"admin_proxy_clear_confirm_{location}"
        )
    ])
    buttons.append([back_button("admin_proxy_stock")])
    buttons.append([back_button("admin_panel")])

    await query.edit_message_text(
        text_msg,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def del_proxy_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف یک پروکسی از انبار"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    # del_proxy_stock_{id}_{location}_{page}
    parts = query.data.split("_")
    try:
        pid = int(parts[3])
        location = parts[4]
        page = int(parts[5]) if len(parts) > 5 else 0
    except Exception:
        await query.answer("داده نامعتبر", show_alert=True)
        return

    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT proxy_text, is_sold FROM proxy_stock WHERE id = ?", (pid,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await query.answer("پروکسی یافت نشد", show_alert=True)
            query.data = f"admin_proxy_stock_list_{location}_{page}"
            return await admin_proxy_stock_list(update, context)
        if row[1]:
            await query.answer("این پروکسی قبلاً فروخته شده و قابل حذف از انبار نیست", show_alert=True)
            return

        await db.execute("DELETE FROM proxy_stock WHERE id = ? AND is_sold = 0", (pid,))
        await db.commit()

    await log_admin_action(query.from_user.id, "delete_proxy_stock", target_id=pid, detail=f"loc={location}")
    await query.answer("✅ پروکسی حذف شد", show_alert=True)

    query.data = f"admin_proxy_stock_list_{location}_{page}"
    return await admin_proxy_stock_list(update, context)


async def admin_proxy_clear_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأیید پاک کردن همه پروکسی‌های یک لوکیشن"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    location = query.data.replace("admin_proxy_clear_confirm_", "")
    if location not in PROXY_LOCATIONS:
        await query.answer("لوکیشن نامعتبر", show_alert=True)
        return

    loc_name = PROXY_LOCATIONS[location]["name"]
    stock = await get_proxy_stock_count(location)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ بله، همه {stock} تا حذف شود",
            callback_data=f"admin_proxy_clear_do_{location}"
        )],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"admin_proxy_stock_list_{location}_0")],
        [back_button("admin_proxy_stock")],
    ])
    await query.edit_message_text(
        f"⚠️ <b>حذف دسته‌جمعی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"آیا مطمئنید می‌خواهید <b>همه {stock}</b> پروکسی فروخته‌نشدهٔ لوکیشن {loc_name} را حذف کنید؟\n\n"
        f"این عمل قابل بازگشت نیست.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


async def admin_proxy_clear_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای پاک کردن همه پروکسی‌های یک لوکیشن"""
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    location = query.data.replace("admin_proxy_clear_do_", "")
    if location not in PROXY_LOCATIONS:
        await query.answer("لوکیشن نامعتبر", show_alert=True)
        return

    loc_name = PROXY_LOCATIONS[location]["name"]
    async with aiosqlite.connect("bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM proxy_stock WHERE location = ? AND is_sold = 0",
            (location,),
        ) as cur:
            count = (await cur.fetchone())[0] or 0
        await db.execute(
            "DELETE FROM proxy_stock WHERE location = ? AND is_sold = 0",
            (location,),
        )
        await db.commit()

    await log_admin_action(
        query.from_user.id,
        "clear_proxy_stock",
        detail=f"loc={location}, count={count}",
    )
    await query.edit_message_text(
        f"✅ <b>{count}</b> پروکسی از انبار {loc_name} حذف شد.",
        reply_markup=InlineKeyboardMarkup([
            [back_button("admin_proxy_stock")],
            [back_button("admin_panel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


async def admin_proxy_tariffs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇳🇱 پروکسی لوکیشن هلند", callback_data="admin_proxy_price_holland")],
        [InlineKeyboardButton("🇺🇸 پروکسی لوکیشن آمریکا", callback_data="admin_proxy_price_america")],
        [InlineKeyboardButton("🇸🇬 پروکسی لوکیشن سنگاپور", callback_data="admin_proxy_price_singapore")],
        [InlineKeyboardButton("📅 قیمت هر روز پروکسی", callback_data="admin_proxy_price_day")],
        [back_button("admin_panel")]
    ])
    await query.edit_message_text(
        "💰 <b>تعرفه پروکسی‌ها</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "لوکیشن مورد نظر را برای مشاهده/تغییر قیمت انتخاب کنید:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

async def admin_proxy_price_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return

    data = query.data.replace("admin_proxy_price_", "")
    if data == "day":
        current = await get_proxy_day_price()
        context.user_data["admin_proxy_price_key"] = "proxy_price_per_day"
        context.user_data["admin_proxy_price_label"] = "قیمت هر روز پروکسی"
        text = (
            f"📅 <b>قیمت هر روز پروکسی</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"قیمت فعلی: <b>{current:,}</b> تومان\n\n"
            f"برای تغییر، روی دکمه زیر بزنید:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغییر قیمت", callback_data="admin_proxy_change_price")],
            [back_button("admin_proxy_tariffs")]
        ])
    else:
        location = data
        if location not in PROXY_LOCATIONS:
            await query.answer("نامعتبر", show_alert=True)
            return
        info = PROXY_LOCATIONS[location]
        current = await get_proxy_unit_price(location)
        context.user_data["admin_proxy_price_key"] = info["key"]
        context.user_data["admin_proxy_price_label"] = f"قیمت پروکسی {info['name']}"
        text = (
            f"🌐 <b>پروکسی {info['name']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"قیمت فعلی هر عدد: <b>{current:,}</b> تومان\n\n"
            f"برای تغییر، روی دکمه زیر بزنید:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغییر قیمت پروکسی", callback_data="admin_proxy_change_price")],
            [back_button("admin_proxy_tariffs")]
        ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_proxy_change_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    label = context.user_data.get("admin_proxy_price_label", "قیمت")
    await query.edit_message_text(
        f"✏️ <b>تغییر {label}</b>\n\n"
        f"قیمت جدید را به تومان وارد کنید (مثال: 50000):",
        parse_mode=ParseMode.HTML
    )
    return ADMIN_PROXY_SET_PRICE

async def admin_proxy_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(",", ""))
        if price < 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ عدد معتبر وارد کنید:")
        return ADMIN_PROXY_SET_PRICE

    key = context.user_data.get("admin_proxy_price_key")
    label = context.user_data.get("admin_proxy_price_label", "قیمت")
    if not key:
        await update.message.reply_text("خطا. دوباره تلاش کنید.", reply_markup=main_keyboard(True))
        return ConversationHandler.END

    await set_setting(key, str(price))
    await update.message.reply_text(
        f"✅ {label} به <b>{price:,}</b> تومان تغییر یافت.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(True)
    )
    context.user_data.pop("admin_proxy_price_key", None)
    context.user_data.pop("admin_proxy_price_label", None)
    return ConversationHandler.END

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ==================== main ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            # خرید سرویس — برای کار کردن حتی وسط conversation ادمین
            CallbackQueryHandler(buy_service, pattern="^buy_service$"),
            CallbackQueryHandler(show_tariffs, pattern="^server_(holland|multi|unlimited)$"),
            CallbackQueryHandler(start_custom_plan, pattern="^server_custom$"),
            CallbackQueryHandler(select_tariff, pattern="^select_tariff_"),
            CallbackQueryHandler(adjust_days, pattern="^days_adj_"),
            CallbackQueryHandler(confirm_days, pattern="^days_confirm$"),
            CallbackQueryHandler(back_main, pattern="^back_main$"),
            CallbackQueryHandler(my_services, pattern="^my_services$"),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
            CallbackQueryHandler(transfer_start, pattern="^transfer_"),
            CallbackQueryHandler(enter_username, pattern="^enter_username$"),
            CallbackQueryHandler(auto_username, pattern="^auto_username$"),
            CallbackQueryHandler(test_enter_name, pattern="^test_enter_name$"),
            CallbackQueryHandler(apply_discount, pattern="^apply_discount$"),
            CallbackQueryHandler(change_discount, pattern="^change_discount$"),
            CallbackQueryHandler(send_receipt, pattern="^send_receipt$"),
            CallbackQueryHandler(charge_wallet, pattern="^charge_wallet$"),
            CallbackQueryHandler(wallet_send_receipt, pattern="^wallet_send_receipt$"),
            CallbackQueryHandler(admin_add_tariff, pattern="^admin_add_tariff$"),
            CallbackQueryHandler(admin_welcome, pattern="^admin_welcome$"),
            CallbackQueryHandler(admin_rules, pattern="^admin_rules$"),
            CallbackQueryHandler(admin_faq, pattern="^admin_faq$"),
            CallbackQueryHandler(track_order_start, pattern="^track_order$"),
            CallbackQueryHandler(faq_menu, pattern="^faq$"),
            CallbackQueryHandler(service_status, pattern="^service_status$"),
            CallbackQueryHandler(order_history, pattern="^order_history$"),
            CallbackQueryHandler(quick_renew, pattern="^quick_renew$"),
            CallbackQueryHandler(admin_new_discount, pattern="^admin_new_discount$"),
            CallbackQueryHandler(admin_new_gift, pattern="^admin_new_gift$"),
            CallbackQueryHandler(redeem_gift_start, pattern="^redeem_gift$"),
            CallbackQueryHandler(admin_ban, pattern="^admin_ban$"),
            CallbackQueryHandler(admin_unban, pattern="^admin_unban$"),
            CallbackQueryHandler(admin_warn_user, pattern="^admin_warn_user$"),
            CallbackQueryHandler(admin_clear_warn, pattern="^admin_clear_warn$"),
            CallbackQueryHandler(reject_order, pattern="^reject_order_"),
            CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"),
            CallbackQueryHandler(admin_msg_user, pattern="^admin_msg_user$"),
            CallbackQueryHandler(admin_broadcast_admins, pattern="^admin_broadcast_admins$"),
            CallbackQueryHandler(admin_msg_admin, pattern="^admin_msg_admin$"),
            CallbackQueryHandler(admin_test_recharge, pattern="^admin_test_recharge$"),
            CallbackQueryHandler(admin_add_balance, pattern="^admin_add_balance$"),
            CallbackQueryHandler(admin_all_balance, pattern="^admin_all_balance$"),
            CallbackQueryHandler(admin_deduct_balance, pattern="^admin_deduct_balance$"),
            CallbackQueryHandler(admin_deduct_all, pattern="^admin_deduct_all$"),
            CallbackQueryHandler(admin_search_user, pattern="^admin_search_user$"),
            CallbackQueryHandler(admin_search_tracking, pattern="^admin_search_tracking$"),
            CallbackQueryHandler(admin_search_proxy_tracking, pattern="^admin_search_proxy_tracking$"),
            CallbackQueryHandler(admin_set_referral, pattern="^admin_set_referral$"),
            CallbackQueryHandler(admin_set_min_charge, pattern="^admin_set_min_charge$"),
            CallbackQueryHandler(admin_set_service_days, pattern="^admin_set_service_days$"),
            CallbackQueryHandler(admin_set_test_volume, pattern="^admin_set_test_volume$"),
            CallbackQueryHandler(admin_panel_cfg_search_start, pattern="^admin_panel_cfg_search$"),
            CallbackQueryHandler(admin_panel_cfg_delete_start, pattern="^admin_panel_cfg_delete$"),
            CallbackQueryHandler(maint_timed_start, pattern="^maint_timed$"),
            CallbackQueryHandler(sqa_add_start, pattern="^sqa_add$"),
            CallbackQueryHandler(sqa_edit_start, pattern="^sqa_edit_"),

            CallbackQueryHandler(admin_add_channel, pattern="^admin_add_channel$"),
            CallbackQueryHandler(admin_add_panel, pattern="^admin_add_panel$"),
            CallbackQueryHandler(edit_tariff, pattern="^edit_tariff_"),
            CallbackQueryHandler(new_ticket, pattern="^new_ticket$"),
            CallbackQueryHandler(write_ticket, pattern="^write_ticket$"),
            CallbackQueryHandler(support_ready_qa, pattern="^support_ready_qa$"),
            CallbackQueryHandler(reply_ticket_start, pattern="^reply_ticket_"),
            CallbackQueryHandler(renew_send_receipt, pattern="^renew_send_receipt$"),
            CallbackQueryHandler(admin_add_admin, pattern="^admin_add_admin$"),
            # پروکسی
            CallbackQueryHandler(proxy_send_receipt, pattern="^proxy_send_receipt$"),
            CallbackQueryHandler(admin_proxy_charge_loc, pattern="^admin_proxy_charge_(holland|america|singapore)$"),
            CallbackQueryHandler(admin_proxy_change_price_start, pattern="^admin_proxy_change_price$"),
        ],
        states={
            WAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)],
            WAITING_DURATION: [
                CallbackQueryHandler(adjust_days, pattern="^days_adj_"),
                CallbackQueryHandler(confirm_days, pattern="^days_confirm$"),
            ],
            CUSTOM_WAITING_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_receive_gb)],
            CUSTOM_WAITING_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_receive_days)],
            TRANSFER_WAITING_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_receive_target)],
            TRANSFER_CONFIRM: [
                CallbackQueryHandler(transfer_confirm, pattern="^transfer_confirm$"),
            ],
            WAITING_DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_discount)],
            WAITING_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_receipt)],
            WAITING_WALLET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wallet_amount)],
            WAITING_WALLET_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_wallet_receipt)],
            ADMIN_ADD_TARIFF_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_tariff_gb)],
            ADMIN_ADD_TARIFF_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_tariff_price)],
            ADMIN_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_welcome)],
            ADMIN_RULES: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_rules)],
            ADMIN_FAQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_faq)],
            TRACK_ORDER_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, track_order_receive)],
            ADMIN_DISCOUNT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_discount_code)],
            ADMIN_DISCOUNT_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_discount_percent)],
            ADMIN_DISCOUNT_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_discount_limit)],
            ADMIN_DISCOUNT_EXPIRE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_discount_expire),
                CallbackQueryHandler(admin_discount_expire_btn, pattern="^disc_exp_"),
            ],
            ADMIN_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_ban)],
            ADMIN_UNBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_unban)],
            ADMIN_WARN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_warn_target)],
            ADMIN_WARN_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_warn_text),
                CallbackQueryHandler(admin_warn_no_note, pattern="^warn_no_note$")
            ],
            ADMIN_CLEAR_WARN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_clear_warn)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_broadcast)],
            ADMIN_MSG_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_msg_user_id)],
            ADMIN_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_msg_text)],
            ADMIN_BROADCAST_ADMINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_broadcast_admins)],
            ADMIN_MSG_ADMIN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_msg_admin_target)],
            ADMIN_MSG_ADMIN_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_msg_admin_text)],
            ADMIN_TEST_RECHARGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_test_recharge)],
            ADMIN_ADD_BALANCE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_id)],
            ADMIN_ADD_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_amount)],
            ADMIN_ADD_BALANCE_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_note),
                CallbackQueryHandler(admin_bal_no_note, pattern="^bal_no_note$")
            ],
            ADMIN_ALL_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_all_balance)],
            ADMIN_DEDUCT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deduct_id)],
            ADMIN_DEDUCT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_deduct_amount),
                CallbackQueryHandler(deduct_full_balance, pattern="^deduct_full_balance$")
            ],
            ADMIN_SEARCH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_search_user)],
            ADMIN_TRACKING_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_search_tracking)],
            ADMIN_SET_REFERRAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_set_referral)],
            ADMIN_SET_MIN_CHARGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_set_min_charge)],
            ADMIN_SET_SERVICE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_set_service_days)],
            ADMIN_SET_TEST_VOLUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_set_test_volume)],
            ADMIN_PANEL_CFG_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_cfg_search_do)],
            ADMIN_PANEL_CFG_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_cfg_delete_do)],
            ADMIN_MAINT_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, maint_timed_hours)],
            ADMIN_SQA_ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sqa_add_title)],
            ADMIN_SQA_ADD_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, sqa_add_answer)],
            ADMIN_SQA_EDIT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, sqa_edit_answer)],

            ADMIN_SET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_set_channel)],
            ADMIN_PANEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_name)],
            ADMIN_PANEL_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_url)],
            ADMIN_PANEL_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_user)],
            ADMIN_PANEL_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_pass)],
            ADMIN_EDIT_TARIFF_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_tariff_gb)],
            ADMIN_EDIT_TARIFF_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_tariff_price)],
            WAITING_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ticket)],
            ADMIN_REPLY_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_ticket)],
            RENEW_WAITING_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_renew_receipt)],
            ADMIN_ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_admin_id)],
            # پروکسی
            PROXY_WAITING_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_proxy_receipt)],
            ADMIN_PROXY_CHARGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_proxies),
                MessageHandler(filters.Document.ALL, admin_receive_proxies),
            ],
            ADMIN_PROXY_SET_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_proxy_set_price)],
            ADMIN_REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reject_order_with_reason),
                CallbackQueryHandler(reject_order_no_note, pattern="^reject_no_note"),
                CallbackQueryHandler(reject_order_preset, pattern="^reject_preset_"),
            ],
            # کد هدیه
            ADMIN_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_code)],
            ADMIN_GIFT_VOLUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_volume)],
            ADMIN_GIFT_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_days)],
            ADMIN_GIFT_SERVER: [CallbackQueryHandler(admin_gift_server, pattern="^gift_server_")],
            ADMIN_GIFT_MAX_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_gift_max_uses)],
            WAITING_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_gift_code)],
        },
        fallbacks=[
            CommandHandler("start", start),
            # خروج از conversation با دکمه‌های اصلی منو
            CallbackQueryHandler(buy_service, pattern="^buy_service$"),
            CallbackQueryHandler(show_tariffs, pattern="^server_(holland|multi|unlimited)$"),
            CallbackQueryHandler(show_tariffs_list, pattern="^tariffs_menu$"),
            CallbackQueryHandler(start_custom_plan, pattern="^server_custom$"),
            CallbackQueryHandler(back_main, pattern="^back_main$"),
            CallbackQueryHandler(my_services, pattern="^my_services$"),
            CallbackQueryHandler(service_status, pattern="^service_status$"),
            CallbackQueryHandler(order_history, pattern="^order_history$"),
            CallbackQueryHandler(quick_renew, pattern="^quick_renew$"),
            CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
            CallbackQueryHandler(proxy_menu, pattern="^proxy_menu$"),
            CallbackQueryHandler(wallet, pattern="^wallet$"),
            CallbackQueryHandler(redeem_gift_start, pattern="^redeem_gift$"),
            CallbackQueryHandler(test_account, pattern="^test_account$"),
            CallbackQueryHandler(support, pattern="^support$"),
            CallbackQueryHandler(my_account, pattern="^my_account$"),
            CallbackQueryHandler(support_quick_answer, pattern="^sqa_"),
            CallbackQueryHandler(support_ready_qa, pattern="^support_ready_qa$"),
            CallbackQueryHandler(new_ticket, pattern="^new_ticket$"),
            CallbackQueryHandler(write_ticket, pattern="^write_ticket$"),
            CallbackQueryHandler(referral, pattern="^referral$"),
            CallbackQueryHandler(rules, pattern="^rules$"),
        ],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    application.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
    application.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    application.add_handler(CallbackQueryHandler(buy_service, pattern="^buy_service$"))
    application.add_handler(CallbackQueryHandler(show_tariffs, pattern="^server_(holland|multi|unlimited)$"))
    application.add_handler(CallbackQueryHandler(remove_discount, pattern="^remove_discount$"))
    application.add_handler(CallbackQueryHandler(my_services, pattern="^my_services$"))
    application.add_handler(CallbackQueryHandler(order_detail, pattern="^order_detail_"))
    application.add_handler(CallbackQueryHandler(test_account, pattern="^test_account$"))
    application.add_handler(CallbackQueryHandler(test_auto_name, pattern="^test_auto_name$"))
    application.add_handler(CallbackQueryHandler(wallet, pattern="^wallet$"))
    application.add_handler(CallbackQueryHandler(wallet_history, pattern="^wallet_history$"))
    application.add_handler(CallbackQueryHandler(support, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(my_account, pattern="^my_account$"))
    application.add_handler(CallbackQueryHandler(support_quick_answer, pattern="^sqa_"))
    application.add_handler(CallbackQueryHandler(support_ready_qa, pattern="^support_ready_qa$"))
    application.add_handler(CallbackQueryHandler(new_ticket, pattern="^new_ticket$"))
    application.add_handler(CallbackQueryHandler(write_ticket, pattern="^write_ticket$"))
    application.add_handler(CallbackQueryHandler(my_tickets, pattern="^my_tickets$"))
    application.add_handler(CallbackQueryHandler(referral, pattern="^referral$"))
    application.add_handler(CallbackQueryHandler(rules, pattern="^rules$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_tariff_list, pattern="^admin_tariff_"))
    application.add_handler(CallbackQueryHandler(toggle_tariff, pattern="^toggle_tariff_"))
    application.add_handler(CallbackQueryHandler(delete_tariff, pattern="^delete_tariff_"))
    application.add_handler(CallbackQueryHandler(admin_discounts, pattern="^admin_discounts$"))
    application.add_handler(CallbackQueryHandler(toggle_disc, pattern="^toggle_disc_"))
    application.add_handler(CallbackQueryHandler(del_disc, pattern="^del_disc_"))
    application.add_handler(CallbackQueryHandler(admin_gift_codes, pattern="^admin_gift_codes$"))
    application.add_handler(CallbackQueryHandler(toggle_gift, pattern="^toggle_gift_"))
    application.add_handler(CallbackQueryHandler(del_gift, pattern="^del_gift_"))
    application.add_handler(CallbackQueryHandler(toggle_auto_renew, pattern="^toggle_auto_renew_"))
    application.add_handler(CallbackQueryHandler(redeem_gift_start, pattern="^redeem_gift$"))
    application.add_handler(CallbackQueryHandler(approve_order, pattern="^approve_order_"))
    # reject_order از طریق ConversationHandler + هندلرهای سراسری (دکمه‌های دلیل)
    application.add_handler(CallbackQueryHandler(reject_order_preset, pattern="^reject_preset_"))
    application.add_handler(CallbackQueryHandler(reject_order_no_note, pattern="^reject_no_note"))
    application.add_handler(CallbackQueryHandler(approve_charge, pattern="^approve_charge_"))
    application.add_handler(CallbackQueryHandler(reject_charge, pattern="^reject_charge_"))
    application.add_handler(CallbackQueryHandler(reject_charge_preset, pattern="^rejch_preset_"))
    application.add_handler(CallbackQueryHandler(reject_charge_no_note, pattern="^rejch_no_note_"))
    application.add_handler(CallbackQueryHandler(reject_proxy_preset, pattern="^rejpx_preset_"))
    application.add_handler(CallbackQueryHandler(reject_proxy_no_note, pattern="^rejpx_no_note_"))
    application.add_handler(CallbackQueryHandler(admin_view_logs, pattern="^admin_logs$"))

    application.add_handler(CallbackQueryHandler(confirm_deduct_all, pattern="^confirm_deduct_all$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^finance_"))
    application.add_handler(CallbackQueryHandler(send_config_file, pattern="^dlcfg_"))
    application.add_handler(CallbackQueryHandler(admin_all_users, pattern="^admin_all_users"))
    application.add_handler(CallbackQueryHandler(admin_active_users, pattern="^admin_active_users$"))
    application.add_handler(CallbackQueryHandler(admin_active_users_page, pattern="^admin_active_users_page_"))
    application.add_handler(CallbackQueryHandler(admin_active_configs_page, pattern="^admin_active_configs_page_"))
    application.add_handler(CallbackQueryHandler(admin_export_all_users, pattern="^admin_export_all_users$"))
    application.add_handler(CallbackQueryHandler(admin_user_orders, pattern="^admin_user_orders_"))
    application.add_handler(CallbackQueryHandler(admin_pending_orders, pattern="^admin_pending_orders$"))
    application.add_handler(CallbackQueryHandler(faq_menu, pattern="^faq$"))
    application.add_handler(CallbackQueryHandler(service_status, pattern="^service_status$"))
    application.add_handler(CallbackQueryHandler(order_history, pattern="^order_history$"))
    application.add_handler(CallbackQueryHandler(show_tariffs_list, pattern="^tariffs_menu$"))
    application.add_handler(CallbackQueryHandler(tariffs_list_handler, pattern="^tariff_list_"))
    application.add_handler(CallbackQueryHandler(quick_renew, pattern="^quick_renew$"))
    application.add_handler(CallbackQueryHandler(track_order_start, pattern="^track_order$"))
    application.add_handler(CallbackQueryHandler(admin_pending_charges, pattern="^admin_pending_charges$"))
    application.add_handler(CallbackQueryHandler(admin_backup, pattern="^admin_backup$"))
    application.add_handler(CallbackQueryHandler(admin_settings, pattern="^admin_settings$"))
    application.add_handler(CallbackQueryHandler(admin_reset_all_tests, pattern="^admin_reset_all_tests$"))
    application.add_handler(CallbackQueryHandler(admin_maintenance_menu, pattern="^admin_toggle_maintenance$"))
    application.add_handler(CallbackQueryHandler(maint_on_manual, pattern="^maint_on_manual$"))
    application.add_handler(CallbackQueryHandler(maint_off, pattern="^maint_off$"))
    application.add_handler(CallbackQueryHandler(panel_del_cfg_confirm, pattern="^panel_del_cfg_"))
    application.add_handler(CallbackQueryHandler(admin_manage_sqa, pattern="^admin_manage_sqa$"))
    application.add_handler(CallbackQueryHandler(sqa_del, pattern="^sqa_del_"))
    application.add_handler(CallbackQueryHandler(sqa_reset_defaults, pattern="^sqa_reset_defaults$"))
    application.add_handler(CallbackQueryHandler(admin_panel_cfg_search_start, pattern="^admin_panel_cfg_search$"))
    application.add_handler(CallbackQueryHandler(admin_panel_cfg_delete_start, pattern="^admin_panel_cfg_delete$"))

    application.add_handler(CallbackQueryHandler(pay_with_wallet, pattern="^pay_with_wallet$"))
    application.add_handler(CallbackQueryHandler(admin_panels, pattern="^admin_panels$"))
    application.add_handler(CallbackQueryHandler(admin_test_panels, pattern="^admin_test_panels$"))
    application.add_handler(CallbackQueryHandler(admin_panel_type, pattern="^panel_type_"))
    application.add_handler(CallbackQueryHandler(toggle_panel, pattern="^toggle_panel_"))
    application.add_handler(CallbackQueryHandler(del_panel, pattern="^del_panel_"))
    application.add_handler(CallbackQueryHandler(send_qr, pattern="^qr_"))
    application.add_handler(CallbackQueryHandler(guide_menu, pattern=r"^guide_(?:[0-9]+|test)$"))
    application.add_handler(CallbackQueryHandler(guide_detail, pattern=r"^guide_(?:v2box|v2ray|npv)$"))
    application.add_handler(CallbackQueryHandler(guide_menu, pattern=r"^guide_menu$"))
    application.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))
    application.add_handler(CallbackQueryHandler(renew_service, pattern="^renew_"))
    application.add_handler(CallbackQueryHandler(renew_pay_wallet, pattern="^renew_pay_wallet$"))
    application.add_handler(CallbackQueryHandler(approve_renew, pattern="^approve_renew_"))
    application.add_handler(CallbackQueryHandler(admin_open_tickets, pattern="^admin_open_tickets$"))
    application.add_handler(CallbackQueryHandler(admin_manage_admins, pattern="^admin_manage_admins$"))
    application.add_handler(CallbackQueryHandler(toggle_admin, pattern="^toggle_admin_"))
    application.add_handler(CallbackQueryHandler(admin_grant_perms, pattern="^admin_grant_perms$"))
    application.add_handler(CallbackQueryHandler(admin_grant_perm_user, pattern="^grant_perm_user_"))
    application.add_handler(CallbackQueryHandler(toggle_perm_add, pattern="^toggle_perm_add_"))
    application.add_handler(CallbackQueryHandler(toggle_perm_toggle, pattern="^toggle_perm_toggle_"))
    application.add_handler(CallbackQueryHandler(toggle_perm_finance, pattern="^toggle_perm_finance_"))
    application.add_handler(CallbackQueryHandler(toggle_perm_support, pattern="^toggle_perm_support_"))
    application.add_handler(CallbackQueryHandler(admin_search_proxy_tracking, pattern="^admin_search_proxy_tracking$"))
    application.add_handler(CallbackQueryHandler(admin_manage_channels, pattern="^admin_manage_channels$"))
    application.add_handler(CallbackQueryHandler(toggle_channel, pattern="^toggle_channel_"))
    application.add_handler(CallbackQueryHandler(del_channel, pattern="^del_channel_"))

    # پروکسی
    application.add_handler(CallbackQueryHandler(proxy_menu, pattern="^proxy_menu$"))
    application.add_handler(CallbackQueryHandler(proxy_select_location, pattern="^proxy_loc_"))
    application.add_handler(CallbackQueryHandler(proxy_adjust_qty, pattern="^proxy_qty_"))
    application.add_handler(CallbackQueryHandler(proxy_adjust_days, pattern="^proxy_days_"))
    application.add_handler(CallbackQueryHandler(proxy_show_invoice, pattern="^proxy_show_invoice$"))
    application.add_handler(CallbackQueryHandler(proxy_pay_wallet, pattern="^proxy_pay_wallet$"))
    application.add_handler(CallbackQueryHandler(approve_proxy, pattern="^approve_proxy_"))
    application.add_handler(CallbackQueryHandler(reject_proxy, pattern="^reject_proxy_"))
    application.add_handler(CallbackQueryHandler(admin_proxy_charge, pattern="^admin_proxy_charge$"))
    application.add_handler(CallbackQueryHandler(admin_proxy_tariffs, pattern="^admin_proxy_tariffs$"))
    application.add_handler(CallbackQueryHandler(admin_proxy_price_view, pattern="^admin_proxy_price_"))
    application.add_handler(CallbackQueryHandler(admin_proxy_stock, pattern="^admin_proxy_stock$"))
    application.add_handler(CallbackQueryHandler(admin_proxy_stock_list, pattern="^admin_proxy_stock_list_"))
    application.add_handler(CallbackQueryHandler(del_proxy_stock, pattern="^del_proxy_stock_"))
    application.add_handler(CallbackQueryHandler(admin_proxy_clear_confirm, pattern="^admin_proxy_clear_confirm_"))
    application.add_handler(CallbackQueryHandler(admin_proxy_clear_do, pattern="^admin_proxy_clear_do_"))

    async def post_init(app):
        await init_db()
        # جاب‌های پس‌زمینه
        if app.job_queue:
            app.job_queue.run_repeating(check_usage_and_expire, interval=3600, first=60)
            app.job_queue.run_repeating(cleanup_old_tests, interval=86400, first=120)
            app.job_queue.run_repeating(cleanup_expired_configs, interval=21600, first=300)  # هر ۶ ساعت
            try:
                from datetime import time as dt_time
                # گزارش مالی روزانه ساعت ۲۳:۵۵
                app.job_queue.run_daily(
                    send_daily_finance_report,
                    time=dt_time(hour=23, minute=55, second=0),
                    name="daily_finance_report",
                )
                # بک‌آپ خودکار دیتابیس هر روز ساعت ۰۳:۰۰
                app.job_queue.run_daily(
                    auto_backup_db,
                    time=dt_time(hour=3, minute=0, second=0),
                    name="daily_db_backup",
                )
            except Exception as e:
                logger.error(f"schedule daily jobs: {e}")
            logger.info("Background jobs started.")

    application.post_init = post_init
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
