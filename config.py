import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    channel_id: int = int(os.getenv("CHANNEL_ID", "") or "0")
    admin_ids: list[int] = field(default_factory=list)

    # MAX
    max_bot_token: str = os.getenv("MAX_BOT_TOKEN", "")
    max_channel_id: int = int(os.getenv("MAX_CHANNEL_ID", "") or "0")
    max_bot_name: str = os.getenv("MAX_BOT_NAME", "")
    max_admin_ids: list[int] = field(default_factory=list)

    # YooKassa
    yookassa_shop_id: str = os.getenv("YOOKASSA_SHOP_ID", "")
    yookassa_secret_key: str = os.getenv("YOOKASSA_SECRET_KEY", "")

    # Robokassa
    robokassa_login: str = os.getenv("ROBOKASSA_LOGIN", "")
    robokassa_pass1: str = os.getenv("ROBOKASSA_PASS1", "")
    robokassa_pass2: str = os.getenv("ROBOKASSA_PASS2", "")

    # Referral
    referral_percent: int = int(os.getenv("REFERRAL_PERCENT", "") or "10")

    # Webhook
    webhook_host: str = os.getenv("WEBHOOK_HOST", "")
    webhook_path: str = os.getenv("WEBHOOK_PATH", "/payment/webhook")
    webhook_port: int = int(os.getenv("WEBHOOK_PORT", "") or "8080")

    def __post_init__(self):
        raw = os.getenv("ADMIN_IDS", "")
        self.admin_ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
        raw_max = os.getenv("MAX_ADMIN_IDS", "")
        self.max_admin_ids = [int(x.strip()) for x in raw_max.split(",") if x.strip()]


settings = Settings()

# Tariffs: name -> (days, price_rub)
TARIFFS = {
    "1month": {"name": "1 месяц", "days": 30, "price": 590},
    "3months": {"name": "3 месяца", "days": 90, "price": 990},
    "1year": {"name": "1 год", "days": 365, "price": 4968},
}

# Minimum withdrawal amount
MIN_WITHDRAWAL = 500

# Progressive referral: {max_referrals: percent}
# Up to 5 referrals = 30%, 6+ = 50%
REFERRAL_TIERS = [
    (5, 30),    # up to 5 refs → 30%
    (None, 50), # 6+ refs → 50%
]

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")
