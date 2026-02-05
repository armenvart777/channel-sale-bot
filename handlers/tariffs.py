from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from config import TARIFFS

router = Router()


@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    ...


@router.callback_query(F.data.startswith("tariff_"))
async def select_tariff(callback: CallbackQuery, state: FSMContext):
    # Выбор тарифа, применение промокода если есть
    ...
