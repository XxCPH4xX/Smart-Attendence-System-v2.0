from fastapi import APIRouter

from backend.api import accounts, people, reports, schedules, system, vision

router = APIRouter()
for module in (accounts, people, schedules, reports, system, vision):
    router.include_router(module.router)
