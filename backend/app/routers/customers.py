from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import EmailStr, TypeAdapter, ValidationError

from app import service
from app.models import AccountsResponse, CustomerProfileResponse, LeaderboardResponse, Period

router = APIRouter(prefix="/api")

_email = TypeAdapter(EmailStr)


@router.get("/accounts")
async def get_accounts() -> AccountsResponse:
    return await service.accounts()


@router.get("/leaderboard")
async def get_leaderboard(
    period: Period = "1m",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    account: str | None = None,
    refresh: bool = False,
) -> LeaderboardResponse:
    try:
        return await service.leaderboard(period, limit, account, refresh)
    except service.UnknownAccount:
        raise HTTPException(404, "Unknown account")


@router.get("/customers/{email}")
async def get_customer(email: str) -> CustomerProfileResponse:
    email = email.strip().lower()
    try:
        _email.validate_python(email)
    except ValidationError:
        raise HTTPException(422, "Invalid email address")
    return await service.customer_profile(email)
