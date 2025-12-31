import asyncio
import logging
from datetime import datetime, timedelta, timezone

from max.api import MaxAPI
from config import settings, TARIFFS, REFERRAL_TIERS, MIN_WITHDRAWAL
from database import db
from services.yookassa import create_payment, check_payment_status
from services.subscription import get_referral_percent

logger = logging.getLogger(__name__)

# ── FSM ──
user_states: dict[int, dict] = {}


def set_state(user_id: int, state: str, **data):
    user_states[user_id] = {"state": state, **data}


def get_state(user_id: int) -> str | None:
    return user_states.get(user_id, {}).get("state")


def get_data(user_id: int) -> dict:
    return user_states.get(user_id, {})


def clear_state(user_id: int):
    user_states.pop(user_id, None)


def is_admin(user_id: int) -> bool:
    return user_id in settings.max_admin_ids


# States
ST_PROMO_INPUT = "promo_input"
ST_WITHDRAW_AMOUNT = "withdraw_amount"
ST_WITHDRAW_CARD = "withdraw_card"
ST_ADMIN_PROMO_CODE = "admin_promo_code"
ST_ADMIN_PROMO_DISCOUNT = "admin_promo_discount"
ST_ADMIN_PROMO_MAXUSES = "admin_promo_maxuses"
ST_ADMIN_ONBOARD_TEXT = "admin_onboard_text"
ST_ADMIN_GRANT_USER = "admin_grant_user"
ST_ADMIN_GRANT_TARIFF = "admin_grant_tariff"
ST_ADMIN_REVOKE_USER = "admin_revoke_user"
ST_BCAST_MESSAGE = "bcast_message"


# ── Keyboards ──

def main_menu_kb(api: MaxAPI) -> dict:
    return api.inline_keyboard([
        [api.callback_button("🔥 Тарифы", "tariffs")],
        [api.callback_button("👀 Что внутри?", "preview")],
        [api.callback_button("🎁 Промокод", "enter_promo")],
        [api.callback_button("👥 Реферальная программа", "referral")],
        [api.callback_button("📋 Моя подписка", "my_sub")],
    ])


def tariffs_kb(api: MaxAPI, promo_code: str | None = None) -> dict:
    buttons = []
    for key, t in TARIFFS.items():
        payload = f"buy_{key}"
        if promo_code:
            payload += f":{promo_code}"
        buttons.append([api.callback_button(
            f"{t['name']} — {t['price']}₽", payload
        )])
    buttons.append([api.callback_button("⬅️ Назад", "main_menu")])
    return api.inline_keyboard(buttons)


def admin_menu_kb(api: MaxAPI) -> dict:
    return api.inline_keyboard([
        [api.callback_button("📊 Статистика", "admin_stats")],
        [api.callback_button("📨 Рассылка", "admin_broadcast")],
        [api.callback_button("🏷 Промокоды", "admin_promos")],
        [api.callback_button("📝 Онбординг", "admin_onboarding")],
        [api.callback_button("🎯 Тарифы", "admin_tariffs")],
        [api.callback_button("👤 Выдать/Отозвать доступ", "admin_access")],
        [api.callback_button("💸 Заявки на вывод", "admin_withdrawals")],
    ])


def back_kb(api: MaxAPI, payload: str = "main_menu") -> dict:
    return api.inline_keyboard([
        [api.callback_button("⬅️ Назад", payload)],
    ])


# ── Update router ──

async def handle_update(update: dict, api: MaxAPI):
    update_type = update.get("update_type")
    if update_type == "bot_started":
        await handle_bot_started(update, api)
    elif update_type == "message_created":
        await handle_message(update, api)
    elif update_type == "message_callback":
        await handle_callback(update, api)


# ── Bot started ──

async def handle_bot_started(update: dict, api: MaxAPI):
    user = update.get("user", {})
    user_id = user.get("user_id")
    user_name = user.get("name", "")

    await db.add_user(user_id, "", user_name, None, platform="max")

    steps = await db.get_onboarding_steps()
    if steps:
        await send_onboarding_step(api, user_id, steps, 0)
    else:
        await api.send_message(
            "👋 Добро пожаловать!\n\nВыберите действие:",
            user_id=user_id,
            attachments=[main_menu_kb(api)],
        )


async def send_onboarding_step(api: MaxAPI, user_id: int,
                                steps: list[dict], index: int):
    step = steps[index]
    is_last = index >= len(steps) - 1

    if is_last:
        kb = api.inline_keyboard([
            [api.callback_button("🔥 Смотреть тарифы", "tariffs")],
            [api.callback_button("👀 Что внутри?", "preview")],
        ])
    else:
        kb = api.inline_keyboard([
            [api.callback_button("Далее ➡️", f"onboard_{index + 1}")],
        ])

    attachments = []
    if step.get("photo_id"):
        attachments.append(api.photo_attachment(token=step["photo_id"]))
    attachments.append(kb)  # keyboard last

    await api.send_message(
        step["text"],
        user_id=user_id,
        attachments=attachments,
    )


# ── Message handler (FSM text input) ──

async def handle_message(update: dict, api: MaxAPI):
    message = update.get("message", {})
    sender = message.get("sender", {})
    user_id = sender.get("user_id")
    body = message.get("body", {})
    text = body.get("text", "").strip()

    if not user_id:
        return

    if text == "/admin" and is_admin(user_id):
        await api.send_message(
            "🔧 Админ-панель", user_id=user_id,
            attachments=[admin_menu_kb(api)],
        )
        return

    state = get_state(user_id)
    if not state:
        return

    handlers = {
        ST_PROMO_INPUT: lambda: on_promo_input(user_id, text, api),
        ST_WITHDRAW_AMOUNT: lambda: on_withdraw_amount(user_id, text, api),
        ST_WITHDRAW_CARD: lambda: on_withdraw_card(user_id, text, api),
        ST_ADMIN_PROMO_CODE: lambda: on_admin_promo_code(user_id, text, api),
        ST_ADMIN_PROMO_DISCOUNT: lambda: on_admin_promo_discount(user_id, text, api),
        ST_ADMIN_PROMO_MAXUSES: lambda: on_admin_promo_maxuses(user_id, text, api),
        ST_ADMIN_ONBOARD_TEXT: lambda: on_admin_onboard_text(
            user_id, text,
            _extract_photo_token(body),
            api,
        ),
        ST_ADMIN_GRANT_USER: lambda: on_admin_grant_user(user_id, text, api),
        ST_ADMIN_REVOKE_USER: lambda: on_admin_revoke_user(user_id, text, api),
        ST_BCAST_MESSAGE: lambda: on_bcast_message(user_id, message, api),
    }

    handler = handlers.get(state)
    if handler:
        await handler()


def _extract_photo_token(body: dict) -> str | None:
    for att in body.get("attachments") or []:
        if att.get("type") == "image":
            return att.get("payload", {}).get("token")
    return None


# ── Callback handler ──

async def handle_callback(update: dict, api: MaxAPI):
    callback = update.get("callback", {})
    callback_id = callback.get("callback_id", "")
    payload = callback.get("payload", "")
    user = callback.get("user", {})
    user_id = user.get("user_id")
    message = callback.get("message", {})
    message_id = message.get("mid", "")

    if not user_id:
        return

    # Navigation — clear FSM state
    if payload in ("main_menu", "tariffs"):
        clear_state(user_id)

    # Route
    if payload == "main_menu":
        await api.edit_message(message_id, "Выберите действие:",
                               attachments=[main_menu_kb(api)])

    elif payload == "tariffs":
        await show_tariffs(user_id, message_id, api)

    elif payload.startswith("buy_"):
        await select_tariff(user_id, payload[4:], message_id, api)

    elif payload.startswith("pay_yk_"):
        await pay_yookassa(user_id, payload[7:], message_id, api)

    elif payload.startswith("check_pay:"):
        await check_payment_btn(user_id, payload[10:], message_id, api)

    elif payload == "preview":
        await show_preview(user_id, message_id, api)

    elif payload == "my_sub":
        await show_my_sub(user_id, message_id, api)

    elif payload == "enter_promo":
        set_state(user_id, ST_PROMO_INPUT)
        await api.edit_message(message_id, "🎁 Введите промокод:")

    elif payload == "referral":
        await show_referral(user_id, message_id, api)

    elif payload == "withdraw":
        await start_withdraw(user_id, message_id, api)

    elif payload.startswith("onboard_"):
        index = int(payload.split("_")[1])
        steps = await db.get_onboarding_steps()
        if index >= len(steps):
            await api.edit_message(message_id, "Выберите действие:",
                                   attachments=[main_menu_kb(api)])
        else:
            await api.delete_message(message_id)
            await send_onboarding_step(api, user_id, steps, index)

    # ── Admin ──
    elif payload == "admin_menu" and is_admin(user_id):
        clear_state(user_id)
        await api.edit_message(message_id, "🔧 Админ-панель",
                               attachments=[admin_menu_kb(api)])

    elif payload == "admin_stats" and is_admin(user_id):
        await admin_stats(user_id, message_id, api)

    elif payload == "admin_broadcast" and is_admin(user_id):
        await admin_broadcast_start(user_id, message_id, api)

    elif payload.startswith("bcast_") and is_admin(user_id):
        await on_bcast_segment(user_id, payload, message_id, api)

    elif payload == "admin_promos" and is_admin(user_id):
        await admin_promos(user_id, message_id, api)

    elif payload == "admin_promo_create" and is_admin(user_id):
        set_state(user_id, ST_ADMIN_PROMO_CODE)
        await api.edit_message(message_id, "Введите код промокода (латиницей):")

    elif payload.startswith("admin_promo_del:") and is_admin(user_id):
        code = payload.split(":", 1)[1]
        await db.delete_promo(code)
        try:
            await admin_promos(user_id, message_id, api)
        except Exception:
            await api.send_message(f"Промокод {code} удалён.", user_id=user_id)

    elif payload == "admin_onboarding" and is_admin(user_id):
        await admin_onboarding_list(user_id, message_id, api)

    elif payload == "admin_onboard_add" and is_admin(user_id):
        steps = await db.get_onboarding_steps()
        next_step = (steps[-1]["step"] + 1) if steps else 1
        set_state(user_id, ST_ADMIN_ONBOARD_TEXT, step=next_step)
        await api.edit_message(message_id,
                               f"Шаг #{next_step}\nОтправьте текст (можно с фото):")

    elif payload == "admin_tariffs" and is_admin(user_id):
        await admin_tariffs_info(user_id, message_id, api)

    elif payload == "admin_access" and is_admin(user_id):
        kb = api.inline_keyboard([
            [api.callback_button("✅ Выдать доступ", "admin_grant")],
            [api.callback_button("❌ Отозвать доступ", "admin_revoke")],
            [api.callback_button("⬅️ Назад", "admin_menu")],
        ])
        await api.edit_message(message_id, "👤 Управление доступом:",
                               attachments=[kb])

    elif payload == "admin_grant" and is_admin(user_id):
        set_state(user_id, ST_ADMIN_GRANT_USER)
        await api.edit_message(message_id, "Введите user_id пользователя:")

    elif payload == "admin_revoke" and is_admin(user_id):
        set_state(user_id, ST_ADMIN_REVOKE_USER)
        await api.edit_message(message_id, "Введите user_id пользователя:")

    elif payload.startswith("mgrant_") and is_admin(user_id):
        await admin_grant_tariff(user_id, payload[7:], message_id, api)

    elif payload == "admin_withdrawals" and is_admin(user_id):
        await admin_withdrawals(user_id, message_id, api)

    elif payload.startswith("wd_done_") and is_admin(user_id):
        wid = int(payload[8:])
        await db.complete_withdrawal(wid)
        await api.answer_callback(callback_id, notification="✅ Выполнено")
        await admin_withdrawals(user_id, message_id, api)
        return  # already answered

    elif payload.startswith("wd_reject_") and is_admin(user_id):
        wid = int(payload[10:])
        # Get withdrawal info before rejecting
        pending = await db.get_pending_withdrawals()
        withdrawal = next((w for w in pending if w["id"] == wid), None)

        await db.reject_withdrawal(wid)

        # Notify user about rejection
        if withdrawal:
            try:
                await api.send_message(
                    user_id=withdrawal["user_id"],
                    text=(
                        f"❌ Ваша заявка на вывод {withdrawal['amount']}₽ отклонена.\n"
                        f"Средства возвращены на реферальный баланс."
                    ),
                )
            except Exception:
                pass

        await api.answer_callback(callback_id, notification="❌ Отклонено")
        await admin_withdrawals(user_id, message_id, api)
        return

    await api.answer_callback(callback_id)


# ═══════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════

async def show_tariffs(user_id: int, message_id: str, api: MaxAPI):
    text = "📋 Выберите тариф:\n\n"
    for key, t in TARIFFS.items():
        text += f"• {t['name']} — {t['price']}₽\n"
    await api.edit_message(message_id, text, attachments=[tariffs_kb(api)])


async def select_tariff(user_id: int, raw: str, message_id: str, api: MaxAPI):
    parts = raw.split(":", 1)
    tariff_key = parts[0]
    promo_code = parts[1] if len(parts) > 1 else None

    if tariff_key not in TARIFFS:
        return

    tariff = TARIFFS[tariff_key]
    price = tariff["price"]
    discount_text = ""

    if promo_code:
        promo = await db.get_promo(promo_code)
        if promo and (promo["max_uses"] == 0 or
                      promo["used_count"] < promo["max_uses"]):
            discount = price * promo["discount_percent"] // 100
            price -= discount
            discount_text = f"\n🏷 Промокод: {promo_code} (-{promo['discount_percent']}%)"
        else:
            promo_code = None

    suffix = f":{promo_code}" if promo_code else ""
    kb = api.inline_keyboard([
        [api.callback_button("💳 ЮКасса", f"pay_yk_{tariff_key}{suffix}")],
        [api.callback_button("⬅️ Назад", "tariffs")],
    ])

    await api.edit_message(
        message_id,
        f"🛒 {tariff['name']}\n\n"
        f"💰 Стоимость: {price}₽{discount_text}\n\n"
        f"Выберите способ оплаты:",
        attachments=[kb],
    )


async def pay_yookassa(user_id: int, raw: str, message_id: str, api: MaxAPI):
    parts = raw.split(":", 1)
    tariff_key = parts[0]
    promo_code = parts[1] if len(parts) > 1 else None

    if tariff_key not in TARIFFS:
        return

    tariff = TARIFFS[tariff_key]
    price = tariff["price"]

    if promo_code:
        promo = await db.get_promo(promo_code)
        if promo and (promo["max_uses"] == 0 or
                      promo["used_count"] < promo["max_uses"]):
            discount = price * promo["discount_percent"] // 100
            price -= discount
        else:
            promo_code = None

    if price <= 0:
        await api.send_message("Ошибка: сумма 0₽.", user_id=user_id)
        return

    # return_url for MAX — not t.me
    return_url = f"https://max.ru/bot/{settings.max_bot_name}" if settings.max_bot_name else "https://max.ru"

    try:
        result = await create_payment(
            user_id, tariff_key, price, return_url, promo_code
        )
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        await api.send_message("Ошибка создания платежа", user_id=user_id)
        return

    await db.create_payment(user_id, tariff_key, price,
                            result["payment_id"], promo_code, platform="max")

    kb = api.inline_keyboard([
        [api.link_button("💳 Оплатить", result["confirmation_url"])],
        [api.callback_button("✅ Я оплатил",
                             f"check_pay:{result['payment_id']}")],
        [api.callback_button("⬅️ Назад", "tariffs")],
    ])

    await api.edit_message(
        message_id,
        f"💳 Оплата: {price}₽\n\nНажмите кнопку ниже для оплаты.\n"
        f"После оплаты нажмите «Я оплатил».",
        attachments=[kb],
    )


async def check_payment_btn(user_id: int, payment_id: str,
                            message_id: str, api: MaxAPI):
    payment = await db.get_payment(payment_id)
    if not payment or payment["status"] == "succeeded":
        return

    status = await check_payment_status(payment_id)
    if status != "succeeded":
        return

    success = await process_max_payment(payment_id, api)
    if success:
        await api.edit_message(
            message_id,
            "✅ Оплата подтверждена! Доступ выдан.",
            attachments=[main_menu_kb(api)],
        )


async def process_max_payment(payment_id: str, api: MaxAPI) -> bool:
    """Atomically claim and process payment for MAX."""
    payment = await db.claim_payment(payment_id)
    if not payment:
        return False

    user_id = payment["user_id"]
    tariff_key = payment["tariff_key"]
    amount = payment["amount"]
    promo_code = payment["promo_code"]

    if promo_code:
        await db.use_promo(promo_code)

    tariff = TARIFFS[tariff_key]
    days = tariff["days"]

    expires_iso = await db.extend_or_create_subscription(
        user_id, tariff_key, days, payment_id, platform="max"
    )
    expires_at = datetime.fromisoformat(expires_iso)

    # Add to MAX channel
    max_link = None
    if settings.max_channel_id:
        result = await api.add_member(settings.max_channel_id, user_id)
        failed = result.get("failed_user_ids") or []
        failed_details = result.get("failed_user_details") or []
        already = any(d.get("error_code") == "already.member" for d in failed_details)

        if user_id in failed and not result.get("success") and not already:
            max_link = await api.get_invite_link(settings.max_channel_id)

    # Also grant TG channel access (one subscription = both platforms)
    tg_link = None
    if settings.bot_token and settings.channel_id:
        try:
            from services.cross_platform import grant_tg_access_from_max
            tg_link = await grant_tg_access_from_max(
                settings.bot_token, user_id, settings.channel_id
            )
        except Exception as e:
            logger.error(f"Failed to grant TG access for {user_id}: {e}")

    # Build message with both links
    msg = (
        f"🎉 Добро пожаловать!\n\n"
        f"Тариф: {tariff['name']}\n"
        f"Действует до: {expires_at.strftime('%d.%m.%Y')}\n"
    )
    if not max_link:
        msg += "\nВы добавлены в MAX канал!"
    else:
        msg += f"\n💬 MAX: {max_link}"
    if tg_link:
        msg += f"\n📱 Telegram: {tg_link}"

    await api.send_message(user_id=user_id, text=msg)

    # Referral bonus (progressive)
    user = await db.get_user(user_id)
    if user and user.get("referrer_id"):
        referrer_id = user["referrer_id"]
        ref_count = await db.get_referral_count(referrer_id)
        percent = get_referral_percent(ref_count)
        bonus = amount * percent // 100
        if bonus > 0:
            await db.add_referral_bonus(referrer_id, bonus)
            try:
                await api.send_message(
                    user_id=referrer_id,
                    text=f"🎉 Ваш реферал оплатил подписку!\nВам начислено: {bonus}₽ ({percent}%)",
                )
            except Exception:
                pass

    # Notify admins
    for admin_id in settings.max_admin_ids:
        try:
            name = user["full_name"] if user else str(user_id)
            await api.send_message(
                user_id=admin_id,
                text=(
                    f"💰 Новая оплата (MAX)!\n"
                    f"👤 {name}\n"
                    f"📦 {tariff['name']}\n"
                    f"💵 {amount}₽"
                ),
            )
        except Exception:
            pass

    return True


# ── Preview / Subscription ──

async def show_preview(user_id: int, message_id: str, api: MaxAPI):
    messages = await db.get_preview_messages()
    if not messages:
        await api.edit_message(message_id, "👀 Превью пока не настроено.",
                               attachments=[back_kb(api)])
        return

    await api.delete_message(message_id)
    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        attachments = []
        if msg.get("photo_id"):
            attachments.append(api.photo_attachment(token=msg["photo_id"]))
        if is_last:
            attachments.append(back_kb(api))
        await api.send_message(
            msg.get("text", ""),
            user_id=user_id,
            attachments=attachments or None,
        )


async def show_my_sub(user_id: int, message_id: str, api: MaxAPI):
    sub = await db.get_active_subscription(user_id)
    if not sub:
        text = "📋 У вас нет активной подписки."
    else:
        expires = datetime.fromisoformat(sub["expires_at"])
        tariff_name = TARIFFS.get(sub["tariff_key"], {}).get(
            "name", sub["tariff_key"]
        )
        text = (
            f"📋 Ваша подписка\n\n"
            f"Тариф: {tariff_name}\n"
            f"Активна до: {expires.strftime('%d.%m.%Y %H:%M')}"
        )
    await api.edit_message(message_id, text, attachments=[back_kb(api)])


async def show_referral(user_id: int, message_id: str, api: MaxAPI):
    ref_count = await db.get_referral_count(user_id)
    balance = await db.get_referral_earnings(user_id)
    current_percent = get_referral_percent(ref_count)

    tiers_text = ""
    for max_refs, percent in REFERRAL_TIERS:
        if max_refs is None:
            tiers_text += f"  • от 6 рефералов — {percent}%\n"
        else:
            tiers_text += f"  • до {max_refs} рефералов — {percent}%\n"

    text = (
        f"👥 Реферальная программа\n\n"
        f"Ваш реферальный код: ref_{user_id}\n"
        f"(Передайте друзьям, они скажут его при старте бота)\n\n"
        f"👤 Приглашено: {ref_count}\n"
        f"💰 Баланс: {balance}₽\n"
        f"📊 Ваш бонус: {current_percent}% с каждой оплаты\n\n"
        f"Шкала бонусов:\n{tiers_text}\n"
        f"Минимальная сумма вывода: {MIN_WITHDRAWAL}₽"
    )

    kb = api.inline_keyboard([
        [api.callback_button("💰 Вывести", "withdraw")],
        [api.callback_button("⬅️ Назад", "main_menu")],
    ])
    await api.edit_message(message_id, text, attachments=[kb])


async def start_withdraw(user_id: int, message_id: str, api: MaxAPI):
    balance = await db.get_referral_earnings(user_id)
    if balance < MIN_WITHDRAWAL:
        return
    set_state(user_id, ST_WITHDRAW_AMOUNT)
    await api.edit_message(
        message_id,
        f"💰 Баланс: {balance}₽\n\nВведите сумму для вывода (мин. {MIN_WITHDRAWAL}₽):",
    )


# ── FSM text handlers ──

async def on_promo_input(user_id: int, text: str, api: MaxAPI):
    clear_state(user_id)
    code = text.upper()
    promo = await db.get_promo(code)

    if not promo or (promo["max_uses"] > 0 and
                     promo["used_count"] >= promo["max_uses"]):
        await api.send_message(
            "❌ Промокод не найден или неактивен.",
            user_id=user_id,
            attachments=[main_menu_kb(api)],
        )
        return

    await api.send_message(
        f"✅ Промокод {code} применён!\n"
        f"Скидка: {promo['discount_percent']}%\n\nВыберите тариф:",
        user_id=user_id,
        attachments=[tariffs_kb(api, promo_code=code)],
    )


async def on_withdraw_amount(user_id: int, text: str, api: MaxAPI):
    try:
        amount = int(text)
    except ValueError:
        await api.send_message("Введите число:", user_id=user_id)
        return

    balance = await db.get_referral_earnings(user_id)
    if amount < MIN_WITHDRAWAL:
        await api.send_message(f"Минимальная сумма — {MIN_WITHDRAWAL}₽", user_id=user_id)
        return
    if amount > balance:
        await api.send_message(
            f"Недостаточно средств. Баланс: {balance}₽", user_id=user_id
        )
        return

    set_state(user_id, ST_WITHDRAW_CARD, amount=amount)
    await api.send_message("Введите номер карты для вывода:", user_id=user_id)


async def on_withdraw_card(user_id: int, text: str, api: MaxAPI):
    data = get_data(user_id)
    amount = data.get("amount", 0)
    card_info = text.strip()

    success = await db.create_withdrawal(user_id, amount, card_info)
    clear_state(user_id)

    if not success:
        await api.send_message("❌ Недостаточно средств.", user_id=user_id,
                               attachments=[main_menu_kb(api)])
        return

    await api.send_message(
        f"✅ Заявка на вывод {amount}₽ создана!\n"
        f"Деньги поступят в течение 24 часов.",
        user_id=user_id,
        attachments=[main_menu_kb(api)],
    )

    user = await db.get_user(user_id)
    for admin_id in settings.max_admin_ids:
        try:
            await api.send_message(
                user_id=admin_id,
                text=(
                    f"💸 Заявка на вывод (MAX)!\n"
                    f"👤 {user['full_name'] if user else user_id}\n"
                    f"💰 {amount}₽\n💳 {card_info}"
                ),
            )
        except Exception:
            pass


# ── Admin handlers ──

async def admin_stats(user_id: int, message_id: str, api: MaxAPI):
    stats = await db.get_stats()
    text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"✅ Активных подписок: {stats['active_subscriptions']}\n"
        f"💰 Выручка: {stats['total_revenue']}₽\n"
        f"🧾 Оплат: {stats['total_payments']}"
    )
    await api.edit_message(message_id, text,
                           attachments=[back_kb(api, "admin_menu")])


async def admin_broadcast_start(user_id: int, message_id: str, api: MaxAPI):
    kb = api.inline_keyboard([
        [api.callback_button("📢 Все", "bcast_all")],
        [api.callback_button("✅ Купившие", "bcast_buyers")],
        [api.callback_button("❌ Не купившие", "bcast_non_buyers")],
        [api.callback_button("⬅️ Назад", "admin_menu")],
    ])
    await api.edit_message(message_id, "📨 Выберите сегмент:",
                           attachments=[kb])


async def on_bcast_segment(user_id: int, payload: str, message_id: str,
                           api: MaxAPI):
    segment_map = {
        "bcast_all": "all",
        "bcast_buyers": "buyers",
        "bcast_non_buyers": "non_buyers",
    }
    segment = segment_map.get(payload)
    if not segment:
        return
    set_state(user_id, ST_BCAST_MESSAGE, segment=segment)
    await api.edit_message(message_id, "📝 Отправьте сообщение для рассылки.")


async def on_bcast_message(user_id: int, message: dict, api: MaxAPI):
    data = get_data(user_id)
    segment = data.get("segment", "all")
    clear_state(user_id)

    body = message.get("body", {})
    text = body.get("text", "")
    attachments_to_forward = []

    # Extract media attachments from the message
    for att in body.get("attachments") or []:
        att_type = att.get("type")
        if att_type in ("image", "video"):
            token = att.get("payload", {}).get("token", "")
            if token:
                attachments_to_forward.append(
                    {"type": att_type, "payload": {"token": token}}
                )

    if segment == "buyers":
        user_ids = await db.get_buyers(platform="max")
    elif segment == "non_buyers":
        user_ids = await db.get_non_buyers(platform="max")
    else:
        user_ids = await db.get_all_user_ids(platform="max")

    await api.send_message("📨 Рассылка запущена...", user_id=user_id)

    sent = 0
    failed = 0
    for uid in user_ids:
        if uid == user_id:
            continue
        try:
            await api.send_message(
                text, user_id=uid,
                attachments=attachments_to_forward or None,
            )
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 25 == 0:
            await asyncio.sleep(1)

    await api.send_message(
        f"✅ Рассылка завершена!\n\n"
        f"📨 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"📊 Всего: {len(user_ids)}",
        user_id=user_id,
        attachments=[back_kb(api, "admin_menu")],
    )


async def admin_promos(user_id: int, message_id: str, api: MaxAPI):
    promos = await db.get_all_promos()
    text = "🏷 Промокоды:\n\n"
    if not promos:
        text += "Пока нет промокодов."
    else:
        for p in promos:
            status = "✅" if p["is_active"] else "❌"
            uses = f"{p['used_count']}"
            if p["max_uses"] > 0:
                uses += f"/{p['max_uses']}"
            text += f"{status} {p['code']} — {p['discount_percent']}% (исп: {uses})\n"

    buttons = []
    for p in promos:
        if p["is_active"]:
            buttons.append([api.callback_button(
                f"🗑 Удалить {p['code']}", f"admin_promo_del:{p['code']}"
            )])
    buttons.append([api.callback_button("➕ Создать промокод", "admin_promo_create")])
    buttons.append([api.callback_button("⬅️ Назад", "admin_menu")])
    kb = api.inline_keyboard(buttons)
    await api.edit_message(message_id, text, attachments=[kb])


async def on_admin_promo_code(user_id: int, text: str, api: MaxAPI):
    code = text.strip().upper()
    existing = await db.get_promo(code)
    if existing:
        await api.send_message("Такой промокод уже есть. Введите другой:",
                               user_id=user_id)
        return
    set_state(user_id, ST_ADMIN_PROMO_DISCOUNT, code=code)
    await api.send_message(f"Промокод: {code}\nВведите скидку в %:",
                           user_id=user_id)


async def on_admin_promo_discount(user_id: int, text: str, api: MaxAPI):
    try:
        discount = int(text)
        if not 1 <= discount <= 99:  # max 99% to prevent 0₽ payments
            raise ValueError
    except ValueError:
        await api.send_message("Введите число от 1 до 99:", user_id=user_id)
        return
    data = get_data(user_id)
    set_state(user_id, ST_ADMIN_PROMO_MAXUSES,
              code=data.get("code"), discount=discount)
    await api.send_message("Макс. кол-во использований (0 = безлимит):",
                           user_id=user_id)


async def on_admin_promo_maxuses(user_id: int, text: str, api: MaxAPI):
    try:
        max_uses = int(text)
    except ValueError:
        await api.send_message("Введите число:", user_id=user_id)
        return
    data = get_data(user_id)
    await db.create_promo(data["code"], data["discount"], max_uses)
    clear_state(user_id)
    await api.send_message(
        f"✅ Промокод {data['code']} создан!\n"
        f"Скидка: {data['discount']}%\n"
        f"Лимит: {'безлимит' if max_uses == 0 else max_uses}",
        user_id=user_id,
        attachments=[back_kb(api, "admin_menu")],
    )


async def admin_onboarding_list(user_id: int, message_id: str, api: MaxAPI):
    steps = await db.get_onboarding_steps()
    text = "📝 Онбординг:\n\n"
    if not steps:
        text += "Шаги не настроены."
    else:
        for s in steps:
            media = " 📷" if s.get("photo_id") else ""
            preview = s["text"][:50] + "..." if len(s["text"]) > 50 else s["text"]
            text += f"{s['step']}. {preview}{media}\n"

    kb = api.inline_keyboard([
        [api.callback_button("➕ Добавить шаг", "admin_onboard_add")],
        [api.callback_button("⬅️ Назад", "admin_menu")],
    ])
    await api.edit_message(message_id, text, attachments=[kb])


async def on_admin_onboard_text(user_id: int, text: str,
                                photo_token: str | None, api: MaxAPI):
    data = get_data(user_id)
    step = data.get("step", 1)
    await db.set_onboarding_step(step, text, photo_token, None)
    clear_state(user_id)
    await api.send_message(
        f"✅ Шаг #{step} сохранён!",
        user_id=user_id,
        attachments=[back_kb(api, "admin_onboarding")],
    )


async def admin_tariffs_info(user_id: int, message_id: str, api: MaxAPI):
    text = "🎯 Текущие тарифы:\n\n"
    for key, t in TARIFFS.items():
        text += f"• {t['name']} ({key}) — {t['price']}₽ / {t['days']} дн.\n"
    await api.edit_message(message_id, text,
                           attachments=[back_kb(api, "admin_menu")])


async def on_admin_grant_user(user_id: int, text: str, api: MaxAPI):
    try:
        target_id = int(text.strip())
    except ValueError:
        await api.send_message("Введите числовой user_id:", user_id=user_id)
        return

    set_state(user_id, ST_ADMIN_GRANT_TARIFF, target_id=target_id)
    buttons = [
        [api.callback_button(f"{t['name']} ({t['days']} дн.)", f"mgrant_{key}")]
        for key, t in TARIFFS.items()
    ]
    kb = api.inline_keyboard(buttons)
    await api.send_message("Выберите тариф:", user_id=user_id, attachments=[kb])


async def admin_grant_tariff(user_id: int, tariff_key: str,
                             message_id: str, api: MaxAPI):
    data = get_data(user_id)
    target_id = data.get("target_id")
    clear_state(user_id)

    if not target_id or tariff_key not in TARIFFS:
        return

    tariff = TARIFFS[tariff_key]
    expires_iso = await db.extend_or_create_subscription(
        target_id, tariff_key, tariff["days"],
        f"manual_{user_id}", platform="max"
    )
    expires_at = datetime.fromisoformat(expires_iso)

    if settings.max_channel_id:
        await api.add_member(settings.max_channel_id, target_id)

    result_text = (
        f"✅ Доступ выдан для {target_id}\n"
        f"Тариф: {tariff['name']}\n"
        f"До: {expires_at.strftime('%d.%m.%Y')}"
    )

    try:
        await api.send_message(
            user_id=target_id,
            text=(
                f"🎉 Вам выдан доступ!\n"
                f"Тариф: {tariff['name']}\n"
                f"До: {expires_at.strftime('%d.%m.%Y')}"
            ),
        )
        result_text += "\n📨 Уведомление отправлено"
    except Exception:
        pass

    await api.edit_message(message_id, result_text,
                           attachments=[back_kb(api, "admin_menu")])


async def on_admin_revoke_user(user_id: int, text: str, api: MaxAPI):
    try:
        target_id = int(text.strip())
    except ValueError:
        await api.send_message("Введите числовой user_id:", user_id=user_id)
        return

    clear_state(user_id)

    if settings.max_channel_id:
        await api.remove_member(settings.max_channel_id, target_id)

    sub = await db.get_active_subscription(target_id)
    if sub:
        await db.deactivate_subscription(sub["id"])

    await api.send_message(
        f"✅ Доступ для {target_id} отозван.",
        user_id=user_id,
        attachments=[back_kb(api, "admin_menu")],
    )


async def admin_withdrawals(user_id: int, message_id: str, api: MaxAPI):
    pending = await db.get_pending_withdrawals()
    if not pending:
        await api.edit_message(message_id, "💸 Нет заявок на вывод.",
                               attachments=[back_kb(api, "admin_menu")])
        return

    text = "💸 Заявки на вывод:\n\n"
    buttons = []
    for w in pending:
        text += (
            f"#{w['id']} — {w['full_name']} (@{w['username']})\n"
            f"💰 {w['amount']}₽ → {w['card_info']}\n\n"
        )
        buttons.append([
            api.callback_button(f"✅ #{w['id']}", f"wd_done_{w['id']}"),
            api.callback_button(f"❌ #{w['id']}", f"wd_reject_{w['id']}"),
        ])
    buttons.append([api.callback_button("⬅️ Назад", "admin_menu")])
    kb = api.inline_keyboard(buttons)
    await api.edit_message(message_id, text, attachments=[kb])
