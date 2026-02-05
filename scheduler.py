import asyncio
from aiogram import Bot
from services.subscription import check_expirations


async def run_scheduler(bot: Bot):
    while True:
        await check_expirations(bot)
        await asyncio.sleep(3600)
