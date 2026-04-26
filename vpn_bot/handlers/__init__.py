"""aiogram routers for the VPN bot."""

from .admin import router as admin_router
from .payments import router as payments_router
from .user import router as user_router

__all__ = ["admin_router", "payments_router", "user_router"]
