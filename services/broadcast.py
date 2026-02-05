import asyncio
import logging

from aiogram import Bot

from database import db

logger = logging.getLogger(__name__)


async def send_broadcast(
    bot: Bot,
    message,
    segment: str,
    sender_id: int,
) -> dict:
    """
    Broadcast a message to TG users.
    message must have copy_to(chat_id) method.
    """
    if segment == "buyers":
        user_ids = await db.get_buyers(platform="tg")
    elif segment == "non_buyers":
        user_ids = await db.get_non_buyers(platform="tg")
    else:
        user_ids = await db.get_all_user_ids(platform="tg")

    sent = 0
    failed = 0

    for uid in user_ids:
        if uid == sender_id:
            continue
        try:
            await asyncio.wait_for(message.copy_to(uid), timeout=10)
            sent += 1
        except Exception:
            failed += 1

        if (sent + failed) % 25 == 0:
            await asyncio.sleep(1)

    return {"sent": sent, "failed": failed, "total": len(user_ids)}
