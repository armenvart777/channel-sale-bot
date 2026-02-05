from aiogram.fsm.state import State, StatesGroup


class PromoInput(StatesGroup):
    code = State()


class BroadcastStates(StatesGroup):
    segment = State()
    message = State()
    confirm = State()


class AdminPromo(StatesGroup):
    code = State()
    discount = State()
    max_uses = State()


class AdminOnboarding(StatesGroup):
    text = State()


class WithdrawStates(StatesGroup):
    amount = State()
    card = State()


class AdminManualAccess(StatesGroup):
    user_id = State()
    tariff = State()
