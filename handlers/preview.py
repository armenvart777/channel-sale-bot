from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import TARIFFS
from database import db
from keyboards import back_kb

router = Router()


@router.callback_query(F.data == "preview")
async def show_preview(callback: CallbackQuery):
    messages = await db.get_preview_messages()

    if not messages:
        try:
            await callback.message.edit_text(
                "👀 Превью пока не настроено.",
                reply_markup=back_kb(),
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer(
                "👀 Превью пока не настроено.",
                reply_markup=back_kb(),
            )
        await callback.answer()
        return

    # Delete current message
    await callback.message.delete()

    # Send preview messages
    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        kb = back_kb() if is_last else None

        if msg.get("photo_id"):
            await callback.message.answer_photo(
                photo=msg["photo_id"],
                caption=msg.get("text"),
                reply_markup=kb,
            )
        elif msg.get("video_id"):
            await callback.message.answer_video(
                video=msg["video_id"],
                caption=msg.get("text"),
                reply_markup=kb,
            )
        elif msg.get("text"):
            await callback.message.answer(
                msg["text"],
                reply_markup=kb,
            )

    await callback.answer()


@router.callback_query(F.data == "my_sub")
async def show_my_subscription(callback: CallbackQuery):
    sub = await db.get_active_subscription(callback.from_user.id)

    if not sub:
        text = "📋 У вас нет активной подписки."
    else:
        from datetime import datetime
        expires = datetime.fromisoformat(sub["expires_at"])
        tariff_name = TARIFFS.get(sub["tariff_key"], {}).get("name", sub["tariff_key"])
        text = (
            f"📋 <b>Ваша подписка</b>\n\n"
            f"Тариф: {tariff_name}\n"
            f"Активна до: <b>{expires.strftime('%d.%m.%Y %H:%M')}</b>"
        )

    try:
        await callback.message.edit_text(
            text, reply_markup=back_kb(), parse_mode="HTML",
        )
    except Exception:
        await callback.message.delete()
        await callback.message.answer(
            text, reply_markup=back_kb(), parse_mode="HTML",
        )
    await callback.answer()
