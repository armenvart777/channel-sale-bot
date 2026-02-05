from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from database import db
from services.yookassa import create_payment, check_payment_status
from services.subscription import grant_access

router = Router()


@router.callback_query(F.data.startswith("pay_yookassa_"))
async def pay_yookassa(callback: CallbackQuery):
    # Создание платежа в ЮКасса, отправка ссылки
    ...


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    # Проверка статуса оплаты
    ...


async def process_successful_payment(bot: Bot, payment_id: str):
    # Вызывается из webhook ЮКасса: выдача доступа, реферальный бонус
    ...
