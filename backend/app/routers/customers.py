from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import EmailStr, TypeAdapter, ValidationError

from app import service
from app.models import (
    AccountsResponse,
    AnniversariesResponse,
    CancellationsResponse,
    CustomerProfileResponse,
    LeaderboardResponse,
    NewSubscribersResponse,
    Period,
    Window,
)

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
    return await service.leaderboard(period, limit, account, refresh)


@router.get("/cancellations")
async def get_cancellations(
    window: Window = "1m", account: str | None = None, refresh: bool = False
) -> CancellationsResponse:
    return await service.cancellations(window, account, refresh)


@router.get("/anniversaries")
async def get_anniversaries(
    window: Window = "1m", account: str | None = None, refresh: bool = False
) -> AnniversariesResponse:
    return await service.anniversaries(window, account, refresh)


@router.get("/new-subscribers")
async def get_new_subscribers(
    window: Window = "1m", account: str | None = None, refresh: bool = False
) -> NewSubscribersResponse:
    return await service.new_subscribers(window, account, refresh)


@router.get("/customers/{email}")
async def get_customer(email: str) -> CustomerProfileResponse:
    email = email.strip().lower()
    try:
        _email.validate_python(email)
    except ValidationError:
        raise HTTPException(422, "Invalid email address")
    return await service.customer_profile(email)
