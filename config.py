import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

BIQUOTE_BASE_URL = os.getenv("BIQUOTE_BASE_URL", "https://biquote.io/api")
OANDA_API_TOKEN = os.getenv("OANDA_API_TOKEN", "")
OANDA_PRACTICE_BASE_URL = "https://api-fxpractice.oanda.com/v3"
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "BIQUOTE").upper()
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN", "")
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "")
DERIV_DEMO_ACCOUNT_ID = os.getenv("DERIV_DEMO_ACCOUNT_ID", "")
MARKET_DATA_SOURCE_LABEL = "DERIV-DEMO" if MARKET_DATA_PROVIDER == "DERIV_DEMO" else "BIQUOTE"

SYMBOLS = ["XAUUSD"]

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))
MAX_SETUP_AGE_MINUTES = max(1, int(os.getenv("MAX_SETUP_AGE_MINUTES", "60")))
MAX_MARKET_BAR_AGE_MINUTES = max(1, int(os.getenv("MAX_MARKET_BAR_AGE_MINUTES", "30")))
DASHBOARD_REFRESH_SECONDS = max(15, min(30, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "20"))))

MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "2.0"))
SIMULATION_ACCOUNT_BALANCE = float(os.getenv("SIMULATION_ACCOUNT_BALANCE", "10.0"))
SIMULATION_RR_MULTIPLE = float(os.getenv("SIMULATION_RR_MULTIPLE", "2.0"))
XAUUSD_CONTRACT_SIZE = float(os.getenv("XAUUSD_CONTRACT_SIZE") or "0") or None
BROKER_MIN_VOLUME = float(os.getenv("BROKER_MIN_VOLUME") or "0") or None
BROKER_VOLUME_STEP = float(os.getenv("BROKER_VOLUME_STEP") or "0") or None
BROKER_MAX_VOLUME = float(os.getenv("BROKER_MAX_VOLUME") or "0") or None
MAX_DAILY_DRAWDOWN = float(os.getenv("MAX_DAILY_DRAWDOWN", "3.0"))
MAX_WEEKLY_DRAWDOWN = float(os.getenv("MAX_WEEKLY_DRAWDOWN", "6.0"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))

SCORE_STANDARD = 2
SCORE_A = 4
SCORE_A_PLUS = 6
SCORE_ELITE = 8

HTF = "H4"
MTF = "H1"
LTF = "M15"

DB_PATH = os.getenv("DB_PATH", "trading_scanner.db")
SCREENSHOTS_DIR = "screenshots"
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))

# Local AI advisory layer (zero-cost, advisory-only)
AI_ADVISOR_ENABLED = os.getenv("AI_ADVISOR_ENABLED", "false").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

# News filter
NEWS_FILTER_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "true").lower() == "true"
NEWS_BLOCK_MINUTES_BEFORE = int(os.getenv("NEWS_BLOCK_MINUTES_BEFORE", "30"))
NEWS_BLOCK_MINUTES_AFTER = int(os.getenv("NEWS_BLOCK_MINUTES_AFTER", "15"))
