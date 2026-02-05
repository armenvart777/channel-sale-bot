from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import MIN_WITHDRAWAL, REFERRAL_TIERS
from database import db
from states import WithdrawStates

router = Router()


@router.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    # Реферальная ссылка, баланс, прогрессивный процент
    ...


@router.callback_query(F.data == "withdraw")
async def start_withdraw(callback: CallbackQuery, state: FSMContext):
    ...


@router.message(WithdrawStates.amount)
async def withdraw_amount(message: Message, state: FSMContext):
    ...


@router.message(WithdrawStates.card)
async def withdraw_card(message: Message, state: FSMContext):
    ...
