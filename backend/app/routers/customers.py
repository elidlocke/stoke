from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app import service
from app.auth import UserDep
from app.models import (
    AccountsResponse,
    AnniversariesResponse,
    AtRiskResponse,
    CancellationsResponse,
    CustomerProfileResponse,
    LeaderboardResponse,
    NewCustomersResponse,
    TrendsResponse,
    Period,
    Window,
)

router = APIRouter(prefix="/api")

@router.get("/accounts")
async def get_accounts(user: UserDep) -> AccountsResponse:
    return await service.accounts(user)


@router.get("/leaderboard")
async def get_leaderboard(
    user: UserDep,
    period: Period = "1m",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    account: str | None = None,
    refresh: bool = False,
) -> LeaderboardResponse:
    return await service.leaderboard(user, period, limit, account, refresh)


@router.get("/cancellations")
async def get_cancellations(
    user: UserDep, window: Window = "1m", account: str | None = None, refresh: bool = False
) -> CancellationsResponse:
    return await service.cancellations(user, window, account, refresh)


@router.get("/anniversaries")
async def get_anniversaries(
    user: UserDep, window: Window = "1m", account: str | None = None, refresh: bool = False
) -> AnniversariesResponse:
    return await service.anniversaries(user, window, account, refresh)


@router.get("/new-customers")
async def get_new_customers(
    user: UserDep, window: Window = "1m", account: str | None = None, refresh: bool = False
) -> NewCustomersResponse:
    return await service.new_customers(user, window, account, refresh)


@router.get("/at-risk")
async def get_at_risk(user: UserDep, account: str | None = None, refresh: bool = False) -> AtRiskResponse:
    return await service.at_risk(user, account, refresh)


@router.get("/trends")
async def get_trends(user: UserDep, refresh: bool = False) -> TrendsResponse:
    return await service.trends(user, refresh)


@router.get("/customers/{customer_id}")
async def get_customer(
    user: UserDep,
    customer_id: Annotated[str, Path(pattern=r"^[0-9a-f]{24}$")],
) -> CustomerProfileResponse:
    try:
        return await service.customer_profile(user, customer_id)
    except service.UnknownCustomer:
        raise HTTPException(404, "Customer not found")
