from aiogram import Bot
from config import REFERRAL_TIERS
from database import db


def get_referral_percent(ref_count: int) -> int:
    for max_refs, percent in REFERRAL_TIERS:
        if max_refs is None or ref_count <= max_refs:
            return percent
    return REFERRAL_TIERS[-1][1]


async def grant_access(bot: Bot, user_id: int, tariff_key: str,
                       payment_id: str, platform: str = "tg"):
    # Выдача доступа в канал + запись подписки в БД
    ...


async def revoke_access(bot: Bot, user_id: int, platform: str = "tg"):
    ...


async def process_referral(bot: Bot, user_id: int, amount: int):
    # Начисление реферального бонуса с прогрессивным процентом
    ...


async def check_expirations(bot: Bot):
    # Уведомление за 3 дня и 1 день до конца, кик при истечении
    ...
