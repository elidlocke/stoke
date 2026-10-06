import logging
from contextlib import asynccontextmanager

import stripe
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app import credentials, db, service
from app.auth import Unauthenticated
from app.config import get_settings
from app.crypto import DecryptionError
from app.routers import customers, settings
from app.stripe_client import MissingPermission, NoCredentials

log = logging.getLogger("stoke")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await db.dispose()


app = FastAPI(title="Stoke", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().cors_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
# Rejects requests whose Host isn't ours, so a malicious page can't reach the API via DNS rebinding.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().allowed_host_list)
app.include_router(customers.router)
app.include_router(settings.router)


# Every response carries customer data or account details: keep it out of browser and proxy caches.
@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Unauthenticated)
async def unauthenticated(_: Request, exc: Unauthenticated) -> JSONResponse:
    return JSONResponse({"detail": "Not signed in"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})


# FastAPI's default 422 echoes the rejected input, which for /api/credentials would be the key.
@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)


@app.exception_handler(credentials.DuplicateAccount)
async def duplicate_account(_: Request, exc: credentials.DuplicateAccount) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(credentials.CredentialError)
async def credential_error(_: Request, exc: credentials.CredentialError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(credentials.CredentialNotFound)
async def credential_not_found(_: Request, exc: credentials.CredentialNotFound) -> JSONResponse:
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.exception_handler(DecryptionError)
async def decryption_error(_: Request, exc: DecryptionError) -> JSONResponse:
    log.error("Can't decrypt a stored Stripe key: %s", exc)
    return JSONResponse({"detail": "A stored key can't be read. Check the encryption key configuration."}, status_code=500)


# Stripe error bodies can include request details; log them server-side, return a generic message.
@app.exception_handler(stripe.StripeError)
async def stripe_error(_: Request, exc: stripe.StripeError) -> JSONResponse:
    log.error("Stripe error: %s (request id %s)", exc.user_message or exc, exc.request_id)
    return JSONResponse({"detail": "Error talking to Stripe"}, status_code=502)


@app.exception_handler(NoCredentials)
async def no_credentials(_: Request, exc: NoCredentials) -> JSONResponse:
    # The code tells the frontend to send the user to Settings.
    return JSONResponse({"detail": str(exc), "code": "no_credentials"}, status_code=503)


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
