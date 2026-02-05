from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from database import db
from keyboards import tariffs_kb, main_menu_kb, back_kb
from states import PromoInput

router = Router()


@router.callback_query(F.data == "enter_promo")
async def ask_promo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PromoInput.waiting_code)
    await callback.message.edit_text(
        "🎁 Введите промокод:",
        reply_markup=back_kb(),
    )
    await callback.answer()


@router.message(PromoInput.waiting_code)
async def apply_promo(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    promo = await db.get_promo(code)

    if not promo:
        await message.answer(
            "❌ Промокод не найден или неактивен.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
        await message.answer(
            "❌ Промокод исчерпан.",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Промокод <b>{code}</b> применён!\n"
        f"Скидка: <b>{promo['discount_percent']}%</b>\n\n"
        f"Выберите тариф:",
        reply_markup=tariffs_kb(promo_code=code, discount_percent=promo['discount_percent']),
        parse_mode="HTML",
    )
