import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database import db
from handlers import setup_routers
from middlewares import DbMiddleware
from scheduler import run_scheduler
from services.yookassa import init_yookassa, parse_webhook, is_yookassa_ip
from handlers.payment import process_successful_payment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


async def yookassa_webhook(request: web.Request) -> web.Response:
    """Handle YooKassa payment notifications."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.remote
    if not is_yookassa_ip(client_ip):
        logger.warning(f"Webhook from untrusted IP: {client_ip}")
        return web.Response(status=403)

    try:
        data = await request.json()
        result = parse_webhook(data)
        if result:
            bot = request.app["bot"]
            await process_successful_payment(bot, result["payment_id"])
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        # Return 500 so YooKassa retries
        return web.Response(status=500)


async def main():
    await db.connect()
    init_yookassa()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.outer_middleware(DbMiddleware())
    dp.callback_query.outer_middleware(DbMiddleware())

    # Routers
    root_router = setup_routers()
    dp.include_router(root_router)

    # Webhook server for YooKassa
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(settings.webhook_path, yookassa_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)

    logger.info("Starting bot...")

    await site.start()
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await runner.cleanup()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
