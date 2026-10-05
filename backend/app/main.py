import logging

import stripe
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import service
from app.config import get_settings
from app.routers import customers
from app.stripe_client import MissingPermission, NoCredentials

log = logging.getLogger("stoke")

app = FastAPI(title="Stoke")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().cors_origin],
    allow_methods=["GET"],
    allow_headers=[],
)
app.include_router(customers.router)


# Stripe error bodies can include request details; log them server-side, return a generic message.
@app.exception_handler(stripe.StripeError)
async def stripe_error(_: Request, exc: stripe.StripeError) -> JSONResponse:
    log.error("Stripe error: %s (request id %s)", exc.user_message or exc, exc.request_id)
    return JSONResponse({"detail": "Error talking to Stripe"}, status_code=502)


@app.exception_handler(NoCredentials)
async def no_credentials(_: Request, exc: NoCredentials) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(MissingPermission)
async def missing_permission(_: Request, exc: MissingPermission) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(service.UnknownAccount)
async def unknown_account(_: Request, exc: service.UnknownAccount) -> JSONResponse:
    return JSONResponse({"detail": "Unknown account"}, status_code=404)


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error", exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)
