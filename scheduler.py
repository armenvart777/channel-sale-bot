import asyncio
from aiogram import Bot
from services.subscription import check_expirations


async def run_scheduler(bot: Bot):
    # Check every 60 minutes
    interval = 3600
    while True:
        await check_expirations(bot)
        await asyncio.sleep(interval)
