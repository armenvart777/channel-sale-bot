import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from aiohttp import web

from config import settings
from database import db
from services.yookassa import init_yookassa, parse_webhook, is_yookassa_ip
from max.api import MaxAPI
from max.handlers import handle_update, process_max_payment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("max_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

api = MaxAPI(settings.max_bot_token)
running = True


async def polling():
    global running
    marker = None

    while running:
        try:
            data = await api.get_updates(marker=marker, timeout=30)
            updates = data.get("updates", [])
            new_marker = data.get("marker")

            for update in updates:
                try:
                    await handle_update(update, api)
                except Exception as e:
                    logger.error(f"Handler error: {e}", exc_info=True)

            if new_marker is not None:
                marker = new_marker
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(5)


async def check_expirations_max():
    """Check expired subscriptions — MAX platform only."""
    while running:
        try:
            for sub in await db.get_expiring_subscriptions(3, platform="max"):
                try:
                    await api.send_message(
                        "⏰ Ваша подписка истекает через 3 дня!\n"
                        "Продлите, чтобы не потерять доступ.",
                        user_id=sub["user_id"],
                    )
                except Exception:
                    pass

            for sub in await db.get_expiring_subscriptions(1, platform="max"):
                try:
                    await api.send_message(
                        "⚠️ Ваша подписка истекает завтра!\n"
                        "Продлите сейчас, чтобы сохранить доступ.",
                        user_id=sub["user_id"],
                    )
                except Exception:
                    pass

            for sub in await db.get_expired_subscriptions(platform="max"):
                await db.deactivate_subscription(sub["id"])
                if settings.max_channel_id:
                    await api.remove_member(
                        settings.max_channel_id, sub["user_id"]
                    )
                try:
                    await api.send_message(
                        "😔 Ваша подписка истекла, доступ закрыт.\n"
                        "Вы можете продлить подписку в любое время!",
                        user_id=sub["user_id"],
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        await asyncio.sleep(3600)


async def yookassa_webhook(request: web.Request) -> web.Response:
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
            # Only process if this payment belongs to MAX
            payment = await db.get_payment(result["payment_id"])
            if payment and payment.get("platform") == "max" and payment["status"] != "succeeded":
                await process_max_payment(result["payment_id"], api)
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return web.Response(status=500)


async def main():
    global running

    await db.connect()
    init_yookassa()
    await api.start()

    app = web.Application()
    app.router.add_post(settings.webhook_path, yookassa_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()

    logger.info("MAX bot started (polling + webhook on :8081)")

    scheduler_task = asyncio.create_task(check_expirations_max())

    try:
        await polling()
    finally:
        running = False
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await runner.cleanup()
        await api.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
