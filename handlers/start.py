from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from database import db

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # Регистрация пользователя, обработка реферальной ссылки, онбординг
    ...


async def _send_onboarding_step(message: Message, step: dict):
    # Отправка шага онбординга (фото/видео/текст)
    ...


@router.callback_query(F.data.startswith("onboard_next_"))
async def onboarding_next(callback: CallbackQuery):
    ...


async def show_main_menu(message: Message, user_id: int):
    # Главное меню с проверкой активной подписки
    ...
