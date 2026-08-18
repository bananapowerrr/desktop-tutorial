# config.py

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DB_PATH = Path(os.getenv("DB_PATH", "./data/bot.db"))
LOG_PATH = Path(os.getenv("LOG_PATH", "./logs/bot.log"))
GOOGLE_CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "crypto_referral_bot/service-account.json")
GOOGLE_SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "")

SPAM_LIMIT_SECONDS = 120
CACHE_TTL_SECONDS = 3600
OLLAMA_VISION_MODEL = "llava"
OLLAMA_DETECT_TIMEOUT_SECONDS = 30
OLLAMA_ANALYZE_TIMEOUT_SECONDS = 120
SHEET_SYNC_INTERVAL_MINUTES = 30
SUPPORTED_EXCHANGES = ["binance", "bybit", "okx", "bingx", "mexc"]
FREE_TRIALS_LIMIT = 3
PREMIUM_MIN_EXCHANGES = 2

CHART_ANALYSIS_PROMPT = """
Ты — профессиональный технический аналитик.

Вход:
- Скриншот графика
- Название биржи

Выход:
1. Паттерны
2. Уровни
3. Вероятность
4. Риски
5. Дисклеймер: "Не является финансовой рекомендацией"
"""