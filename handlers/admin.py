import logging

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import settings, TARIFFS
from database import db
from keyboards import (
    admin_menu_kb, broadcast_segment_kb, confirm_broadcast_kb, back_kb,
)
from states import (
    BroadcastStates, AdminPromo, AdminOnboarding, AdminManualAccess,
)
from services.broadcast import send_broadcast
from services.subscription import grant_access, revoke_access

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


# ── Admin menu ──

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🔧 <b>Админ-панель</b>", reply_markup=admin_menu_kb(),
                         parse_mode="HTML")


@router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "🔧 <b>Админ-панель</b>",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Statistics ──

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    stats = await db.get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['total_users']}</b>\n"
        f"✅ Активных подписок: <b>{stats['active_subscriptions']}</b>\n"
        f"💰 Выручка: <b>{stats['total_revenue']}₽</b>\n"
        f"🧾 Оплат: <b>{stats['total_payments']}</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_kb("admin_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Broadcast ──

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(BroadcastStates.choose_segment)
    await callback.message.edit_text(
        "📨 Выберите сегмент для рассылки:",
        reply_markup=broadcast_segment_kb(),
    )
    await callback.answer()


@router.callback_query(
    BroadcastStates.choose_segment,
    F.data.in_({"bcast_all", "bcast_buyers", "bcast_non_buyers"}),
)
async def choose_segment(callback: CallbackQuery, state: FSMContext):
    segment_map = {
        "bcast_all": "all",
        "bcast_buyers": "buyers",
        "bcast_non_buyers": "non_buyers",
    }
    segment = segment_map[callback.data]
    await state.update_data(segment=segment)
    await state.set_state(BroadcastStates.waiting_message)

    await callback.message.edit_text(
        "📝 Отправьте сообщение для рассылки.\n"
        "Можно: текст, фото, видео, кружочек."
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_message)
async def receive_broadcast_message(message: Message, state: FSMContext):
    await state.update_data(message_id=message.message_id,
                            chat_id=message.chat.id)
    await state.set_state(BroadcastStates.confirm)

    # Forward preview
    await message.copy_to(message.chat.id)
    await message.answer(
        "👆 Превью рассылки.\nОтправить?",
        reply_markup=confirm_broadcast_kb(),
    )


@router.callback_query(BroadcastStates.confirm, F.data == "bcast_confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext,
                            bot: Bot):
    data = await state.get_data()
    segment = data["segment"]
    message_id = data["message_id"]
    chat_id = data["chat_id"]

    await state.clear()
    await callback.message.edit_text("📨 Рассылка запущена...")

    # Get original message to copy
    # We need to use the stored message
    class FakeMessage:
        """Wrapper to use copy_to from stored message."""
        def __init__(self, bot, chat_id, message_id):
            self._bot = bot
            self._chat_id = chat_id
            self._message_id = message_id

        async def copy_to(self, target_id):
            await self._bot.copy_message(target_id, self._chat_id,
                                         self._message_id)

    fake_msg = FakeMessage(bot, chat_id, message_id)
    result = await send_broadcast(bot, fake_msg, segment,
                                  callback.from_user.id)

    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"📨 Отправлено: {result['sent']}\n"
        f"❌ Ошибок: {result['failed']}\n"
        f"📊 Всего в сегменте: {result['total']}",
        reply_markup=back_kb("admin_menu"),
    )
    await callback.answer()


@router.callback_query(BroadcastStates.confirm, F.data == "bcast_cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Рассылка отменена.",
        reply_markup=back_kb("admin_menu"),
    )
    await callback.answer()


# ── Promo codes ──

@router.callback_query(F.data == "admin_promos")
async def admin_promos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    promos = await db.get_all_promos()
    text = "🏷 <b>Промокоды:</b>\n\n"

    if not promos:
        text += "Пока нет промокодов."
    else:
        for p in promos:
            status = "✅" if p["is_active"] else "❌"
            uses = f"{p['used_count']}"
            if p["max_uses"] > 0:
                uses += f"/{p['max_uses']}"
            text += f"{status} <code>{p['code']}</code> — {p['discount_percent']}% (исп: {uses})\n"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    if promos:
        for p in promos:
            if p["is_active"]:
                buttons.append([InlineKeyboardButton(
                    text=f"🗑 Удалить {p['code']}",
                    callback_data=f"admin_promo_del:{p['code']}",
                )])
    buttons.append(InlineKeyboardButton(text="➕ Создать промокод",
                              callback_data="admin_promo_create"))
    buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu"))
    # Wrap single buttons in lists
    kb_buttons = []
    for b in buttons:
        if isinstance(b, list):
            kb_buttons.append(b)
        else:
            kb_buttons.append([b])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin_promo_del:"))
async def admin_promo_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    code = callback.data.split(":", 1)[1]
    await db.delete_promo(code)
    await callback.answer(f"Промокод {code} удалён", show_alert=True)
    try:
        await admin_promos(callback)
    except Exception:
        pass


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminPromo.waiting_code)
    await callback.message.edit_text("Введите код промокода (латиницей):")
    await callback.answer()


@router.message(AdminPromo.waiting_code)
async def admin_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    existing = await db.get_promo(code)
    if existing:
        await message.answer("Такой промокод уже есть. Введите другой:")
        return
    await state.update_data(code=code)
    await state.set_state(AdminPromo.waiting_discount)
    await message.answer(f"Промокод: <b>{code}</b>\nВведите скидку в %:",
                         parse_mode="HTML")


@router.message(AdminPromo.waiting_discount)
async def admin_promo_discount(message: Message, state: FSMContext):
    try:
        discount = int(message.text)
        if not 1 <= discount <= 99:
            raise ValueError
    except ValueError:
        await message.answer("Введите число от 1 до 99:")
        return

    await state.update_data(discount=discount)
    await state.set_state(AdminPromo.waiting_max_uses)
    await message.answer("Макс. кол-во использований (0 = безлимит):")


@router.message(AdminPromo.waiting_max_uses)
async def admin_promo_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
    except ValueError:
        await message.answer("Введите число:")
        return

    data = await state.get_data()
    await db.create_promo(data["code"], data["discount"], max_uses)
    await state.clear()

    await message.answer(
        f"✅ Промокод <b>{data['code']}</b> создан!\n"
        f"Скидка: {data['discount']}%\n"
        f"Лимит: {'безлимит' if max_uses == 0 else max_uses}",
        reply_markup=back_kb("admin_menu"),
        parse_mode="HTML",
    )


# ── Onboarding management ──

@router.callback_query(F.data == "admin_onboarding")
async def admin_onboarding(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    steps = await db.get_onboarding_steps()
    text = "📝 <b>Онбординг:</b>\n\n"

    if not steps:
        text += "Шаги не настроены."
    else:
        for s in steps:
            media = ""
            if s.get("photo_id"):
                media = " 📷"
            elif s.get("video_id"):
                media = " 🎥"
            preview = s["text"][:50] + "..." if len(s["text"]) > 50 else s["text"]
            text += f"{s['step']}. {preview}{media}\n"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    if steps:
        for s in steps:
            buttons.append([InlineKeyboardButton(
                text=f"🗑 Удалить шаг {s['step']}",
                callback_data=f"admin_onboard_del:{s['step']}",
            )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить шаг",
                              callback_data="admin_onboard_add")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("admin_onboard_del:"))
async def admin_onboard_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    step = int(callback.data.split(":", 1)[1])
    await db.delete_onboarding_step(step)
    await callback.answer(f"Шаг {step} удалён", show_alert=True)
    try:
        await admin_onboarding(callback)
    except Exception:
        pass


@router.callback_query(F.data == "admin_onboard_add")
async def admin_onboard_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    steps = await db.get_onboarding_steps()
    next_step = (steps[-1]["step"] + 1) if steps else 1

    await state.update_data(step=next_step)
    await state.set_state(AdminOnboarding.waiting_text)
    await callback.message.edit_text(
        f"Шаг #{next_step}\n"
        f"Отправьте текст (можно с фото/видео):"
    )
    await callback.answer()


@router.message(AdminOnboarding.waiting_text)
async def admin_onboard_text(message: Message, state: FSMContext):
    data = await state.get_data()
    step = data["step"]

    text = message.text or message.caption or ""
    photo_id = None
    video_id = None

    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.video:
        video_id = message.video.file_id

    await db.set_onboarding_step(step, text, photo_id, video_id)
    await state.clear()

    await message.answer(
        f"✅ Шаг #{step} сохранён!",
        reply_markup=back_kb("admin_onboarding"),
    )


# ── Tariffs info ──

@router.callback_query(F.data == "admin_tariffs")
async def admin_tariffs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    text = "🎯 <b>Текущие тарифы:</b>\n\n"
    for key, t in TARIFFS.items():
        text += f"• <b>{t['name']}</b> ({key}) — {t['price']}₽ / {t['days']} дн.\n"

    text += "\n<i>Для изменения тарифов измените config.py</i>"

    await callback.message.edit_text(
        text,
        reply_markup=back_kb("admin_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Manual access ──

@router.callback_query(F.data == "admin_access")
async def admin_access(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать доступ",
                              callback_data="admin_grant")],
        [InlineKeyboardButton(text="❌ Отозвать доступ",
                              callback_data="admin_revoke")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")],
    ])

    await callback.message.edit_text(
        "👤 Управление доступом:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_grant")
async def admin_grant_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminManualAccess.waiting_user_id)
    await state.update_data(action="grant")
    await callback.message.edit_text("Введите user_id пользователя:")
    await callback.answer()


@router.callback_query(F.data == "admin_revoke")
async def admin_revoke_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminManualAccess.waiting_user_id)
    await state.update_data(action="revoke")
    await callback.message.edit_text("Введите user_id пользователя:")
    await callback.answer()


@router.message(AdminManualAccess.waiting_user_id)
async def admin_access_user_id(message: Message, state: FSMContext, bot: Bot):
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("Введите числовой user_id:")
        return

    data = await state.get_data()
    action = data["action"]

    if action == "revoke":
        await revoke_access(bot, target_id)
        # Deactivate subscription in DB
        sub = await db.get_active_subscription(target_id)
        if sub:
            await db.deactivate_subscription(sub["id"])
        await state.clear()
        await message.answer(
            f"✅ Доступ для {target_id} отозван.",
            reply_markup=back_kb("admin_menu"),
        )
    else:
        await state.update_data(target_id=target_id)
        await state.set_state(AdminManualAccess.waiting_tariff)

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{t['name']} ({t['days']} дн.)",
                callback_data=f"mgrant_{key}",
            )]
            for key, t in TARIFFS.items()
        ])
        await message.answer("Выберите тариф:", reply_markup=kb)


@router.callback_query(AdminManualAccess.waiting_tariff, F.data.startswith("mgrant_"))
async def admin_grant_tariff(callback: CallbackQuery, state: FSMContext,
                             bot: Bot):
    if not is_admin(callback.from_user.id):
        return

    tariff_key = callback.data[7:]
    data = await state.get_data()
    target_id = data.get("target_id")
    await state.clear()

    if not target_id:
        await callback.answer("Ошибка", show_alert=True)
        return

    invite_link, expires_at = await grant_access(
        bot, target_id, tariff_key, f"manual_{callback.from_user.id}"
    )

    result_text = f"✅ Доступ выдан для {target_id}\n"
    result_text += f"Тариф: {TARIFFS[tariff_key]['name']}\n"
    result_text += f"До: {expires_at.strftime('%d.%m.%Y')}"

    if invite_link:
        try:
            await bot.send_message(
                target_id,
                f"🎉 Вам выдан доступ!\n"
                f"Тариф: {TARIFFS[tariff_key]['name']}\n"
                f"До: {expires_at.strftime('%d.%m.%Y')}\n\n"
                f"👉 <a href=\"{invite_link}\">Вступить в канал</a>",
                parse_mode="HTML",
            )
            result_text += "\n📨 Ссылка отправлена пользователю"
        except Exception:
            result_text += f"\n🔗 Ссылка: {invite_link}"

    await callback.message.edit_text(
        result_text,
        reply_markup=back_kb("admin_menu"),
    )
    await callback.answer()


# ── Withdrawals ──

@router.callback_query(F.data == "admin_withdrawals")
async def admin_withdrawals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    pending = await db.get_pending_withdrawals()
    if not pending:
        await callback.message.edit_text(
            "💸 Нет заявок на вывод.",
            reply_markup=back_kb("admin_menu"),
        )
        await callback.answer()
        return

    text = "💸 <b>Заявки на вывод:</b>\n\n"
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []

    for w in pending:
        text += (
            f"#{w['id']} — {w['full_name']} (@{w['username']})\n"
            f"💰 {w['amount']}₽ → {w['card_info']}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ #{w['id']} выполнено",
                callback_data=f"wd_done_{w['id']}",
            ),
            InlineKeyboardButton(
                text=f"❌ #{w['id']} отказ",
                callback_data=f"wd_reject_{w['id']}",
            ),
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад",
                                         callback_data="admin_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("wd_done_"))
async def withdrawal_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    wid = int(callback.data[8:])
    await db.complete_withdrawal(wid)
    await callback.answer("✅ Отмечено как выполнено", show_alert=True)
    try:
        await admin_withdrawals(callback)
    except Exception:
        pass


@router.callback_query(F.data.startswith("wd_reject_"))
async def withdrawal_reject(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        return

    wid = int(callback.data[10:])
    # Get withdrawal info before rejecting
    pending = await db.get_pending_withdrawals()
    withdrawal = next((w for w in pending if w["id"] == wid), None)

    await db.reject_withdrawal(wid)

    # Notify user about rejection
    if withdrawal:
        try:
            await bot.send_message(
                withdrawal["user_id"],
                f"❌ Ваша заявка на вывод {withdrawal['amount']}₽ отклонена.\n"
                f"Средства возвращены на реферальный баланс.",
            )
        except Exception:
            pass

    await callback.answer("❌ Отклонено", show_alert=True)
    try:
        await admin_withdrawals(callback)
    except Exception:
        pass
