from aiogram import Router

from .start import router as start_router
from .tariffs import router as tariffs_router
from .payment import router as payment_router
from .referral import router as referral_router
from .promo import router as promo_router
from .preview import router as preview_router
from .admin import router as admin_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(admin_router)  # admin first for priority
    root.include_router(start_router)
    root.include_router(tariffs_router)
    root.include_router(payment_router)
    root.include_router(referral_router)
    root.include_router(promo_router)
    root.include_router(preview_router)
    return root
