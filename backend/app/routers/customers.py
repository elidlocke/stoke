from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

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


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: Annotated[str, Path(pattern=r"^[0-9a-f]{24}$")],
) -> CustomerProfileResponse:
    try:
        return await service.customer_profile(customer_id)
    except service.UnknownCustomer:
        raise HTTPException(404, "Customer not found")
