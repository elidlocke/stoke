import logging
from contextlib import asynccontextmanager

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import credentials, customer_id, db, service
from app.auth import Unauthenticated
from app.config import get_settings
from app.crypto import DecryptionError, get_cipher
from app.routers import customers, settings
from app.stripe_client import MissingPermission, NoCredentials

log = logging.getLogger("stoke")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail at startup, not on the first request, if a required secret is missing.
    get_cipher()
    customer_id.customer_id("startup-check")
    yield
    await db.dispose()


app = FastAPI(title="Stoke", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().cors_origin],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


class HostCheck(TrustedHostMiddleware):
    """Rejects requests whose Host isn't ours, so a malicious page can't reach the API via DNS
    rebinding. The health check is exempt: the host's checker may not send our public hostname,
    and it returns nothing."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/api/healthz":
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


app.add_middleware(HostCheck, allowed_hosts=get_settings().allowed_host_list)
app.include_router(customers.router)
app.include_router(settings.router)


@app.get("/api/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}


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


# In the production image the API also serves the built frontend, so both share one origin.
# Registered last, so the API routes above take precedence.
if (static_dir := get_settings().static_dir) is not None:
    static_root = static_dir.resolve()
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        # Files from frontend/public (e.g. favicon.svg); any other path is a client-side route.
        file = (static_root / path).resolve()
        if path and file.is_relative_to(static_root) and file.is_file():
            return FileResponse(file)
        return FileResponse(static_root / "index.html")
