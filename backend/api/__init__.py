from fastapi import APIRouter

from backend.api import accounts, demo, people, reports, schedules, system, vision

router = APIRouter()
for module in (accounts, demo, people, schedules, reports, system, vision):
    router.include_router(module.router)
