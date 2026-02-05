"""Cross-platform access management.
One subscription grants access to BOTH TG and MAX channels.
"""
import logging

import aiohttp

from config import settings

logger = logging.getLogger(__name__)

MAX_API_URL = "https://platform-api.max.ru"


async def grant_max_access(user_id: int, chat_id: int) -> str | None:
    """Add user to MAX channel. Returns invite link or None.
    Called from TG bot when user pays — grants MAX access too.
    Note: user_id here must be the MAX user_id, which may differ from TG.
    For cross-platform, we need the user to have started both bots.
    """
    if not settings.max_bot_token or not chat_id:
        return None

    async with aiohttp.ClientSession() as session:
        # Try to add member
        params = {"access_token": settings.max_bot_token}
        try:
            async with session.post(
                f"{MAX_API_URL}/chats/{chat_id}/members",
                params=params,
                json={"user_ids": [user_id]},
            ) as resp:
                data = await resp.json()
                if data.get("success"):
                    return None  # Added directly, no link needed

            # If add failed, get invite link
            async with session.get(
                f"{MAX_API_URL}/chats/{chat_id}",
                params=params,
            ) as resp:
                data = await resp.json()
                return data.get("link") or data.get("invite_link")
        except Exception as e:
            logger.error(f"MAX cross-platform access failed: {e}")
            return None


async def grant_tg_access_from_max(bot_token: str, user_id: int,
                                   channel_id: int) -> str | None:
    """Create TG invite link for a user who paid through MAX.
    Called from MAX bot when user pays — grants TG access too.
    """
    if not bot_token or not channel_id:
        return None

    # Use Telegram Bot API directly via HTTP
    tg_api = f"https://api.telegram.org/bot{bot_token}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{tg_api}/createChatInviteLink",
                json={
                    "chat_id": channel_id,
                    "member_limit": 1,
                    "name": f"max_user_{user_id}",
                },
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]["invite_link"]
        except Exception as e:
            logger.error(f"TG cross-platform access failed: {e}")

    return None
