import logging

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://platform-api.max.ru"


class MaxAPI:
    def __init__(self, token: str):
        self.token = token
        self.session: aiohttp.ClientSession | None = None

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{BASE_URL}{path}"
        params = kwargs.pop("params", {})
        params["access_token"] = self.token
        try:
            async with self.session.request(
                method, url, params=params, **kwargs
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"MAX API {method} {path}: {resp.status} {data}")
                return data
        except Exception as e:
            logger.error(f"MAX API error: {e}")
            return {}

    # ── Updates ──

    async def get_updates(self, marker: int | None = None,
                          timeout: int = 30) -> dict:
        params = {"timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    # ── Messages ──

    async def send_message(
        self,
        text: str,
        chat_id: int | None = None,
        user_id: int | None = None,
        attachments: list | None = None,
        notify: bool = True,
    ) -> dict:
        payload = {"text": text}
        if attachments:
            payload["attachments"] = attachments
        if not notify:
            payload["notify"] = False

        params = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id

        return await self._request("POST", "/messages", params=params,
                                   json=payload)

    async def edit_message(self, message_id: str, text: str,
                           attachments: list | None = None) -> dict:
        payload = {"text": text}
        if attachments:
            payload["attachments"] = attachments
        return await self._request(
            "PUT", "/messages", params={"message_id": message_id},
            json=payload,
        )

    async def delete_message(self, message_id: str) -> dict:
        return await self._request(
            "DELETE", "/messages", params={"message_id": message_id},
        )

    # ── Callbacks ──

    async def answer_callback(
        self,
        callback_id: str,
        message: dict | None = None,
        notification: str | None = None,
    ) -> dict:
        payload = {}
        if message:
            payload["message"] = message
        if notification:
            payload["notification"] = notification
        # callback_id is a query parameter, not body
        return await self._request(
            "POST", "/answers",
            params={"callback_id": callback_id},
            json=payload,
        )

    # ── Chats ──

    async def add_member(self, chat_id: int, user_id: int) -> dict:
        return await self._request(
            "POST", f"/chats/{chat_id}/members",
            json={"user_ids": [user_id]},
        )

    async def remove_member(self, chat_id: int, user_id: int) -> dict:
        return await self._request(
            "DELETE", f"/chats/{chat_id}/members",
            params={"user_id": user_id},
        )

    async def get_chat(self, chat_id: int) -> dict:
        return await self._request("GET", f"/chats/{chat_id}")

    async def get_invite_link(self, chat_id: int) -> str | None:
        data = await self.get_chat(chat_id)
        return data.get("link") or data.get("invite_link")

    # ── Keyboard builders ──

    @staticmethod
    def inline_keyboard(buttons: list[list[dict]]) -> dict:
        return {
            "type": "inline_keyboard",
            "payload": {"buttons": buttons},
        }

    @staticmethod
    def callback_button(text: str, payload: str) -> dict:
        return {"type": "callback", "text": text, "payload": payload}

    @staticmethod
    def link_button(text: str, url: str) -> dict:
        return {"type": "link", "text": text, "url": url}

    @staticmethod
    def photo_attachment(token: str = "", url: str = "") -> dict:
        payload = {}
        if token:
            payload["token"] = token
        if url:
            payload["url"] = url
        return {"type": "image", "payload": payload}
