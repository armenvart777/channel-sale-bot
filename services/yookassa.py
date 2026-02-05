from yookassa import Configuration, Payment

YOOKASSA_IPS = {
    "185.71.76.0/27", "185.71.77.0/27",
    "77.75.153.0/25", "77.75.156.11",
}


def init_yookassa():
    ...


async def create_payment(amount: int, description: str,
                         return_url: str) -> dict:
    # Создание платежа через ЮКасса API
    ...


async def check_payment_status(payment_id: str) -> str:
    ...


def is_yookassa_ip(ip: str) -> bool:
    ...


def parse_webhook(data: dict) -> dict | None:
    ...
