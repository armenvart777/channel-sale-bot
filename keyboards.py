from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TARIFFS


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="👀 Что внутри?", callback_data="preview")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="enter_promo")],
        [InlineKeyboardButton(text="👥 Реферальная программа", callback_data="referral")],
        [InlineKeyboardButton(text="📋 Моя подписка", callback_data="my_sub")],
    ])


def onboarding_next_kb(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Далее ➡️", callback_data=f"onboard_{step}")],
    ])


def onboarding_final_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Смотреть тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="👀 Что внутри?", callback_data="preview")],
    ])


def tariffs_kb(promo_code: str | None = None,
               discount_percent: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    for key, t in TARIFFS.items():
        cd = f"buy_{key}"
        if promo_code:
            cd += f":{promo_code}"
        price = t['price']
        if discount_percent > 0:
            discounted = price - (price * discount_percent // 100)
            label = f"{t['name']} — {discounted}₽ (было {price}₽)"
        else:
            label = f"{t['name']} — {price}₽"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=cd,
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_method_kb(tariff_key: str, promo_code: str | None = None) -> InlineKeyboardMarkup:
    suffix = f":{promo_code}" if promo_code else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 ЮКасса",
            callback_data=f"pay_yookassa_{tariff_key}{suffix}",
        )],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")],
    ])


def referral_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Вывести", callback_data="withdraw")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])


def back_kb(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)],
    ])


# ── Admin ──

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏷 Промокоды", callback_data="admin_promos")],
        [InlineKeyboardButton(text="📝 Онбординг", callback_data="admin_onboarding")],
        [InlineKeyboardButton(text="🎯 Тарифы", callback_data="admin_tariffs")],
        [InlineKeyboardButton(text="👤 Выдать/Отозвать доступ", callback_data="admin_access")],
        [InlineKeyboardButton(text="💸 Заявки на вывод", callback_data="admin_withdrawals")],
    ])


def broadcast_segment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Все пользователи", callback_data="bcast_all")],
        [InlineKeyboardButton(text="✅ Купившие", callback_data="bcast_buyers")],
        [InlineKeyboardButton(text="❌ Не купившие", callback_data="bcast_non_buyers")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")],
    ])


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="bcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bcast_cancel")],
    ])
