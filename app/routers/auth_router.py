"""Auth router: login, change password, me."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..core import auth, config, settings
from .deps import require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])
_LOGIN_WINDOW_SECONDS = 900
_LOGIN_MAX_FAILURES = 10
_login_failures: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_login_rate(ip: str, username: str) -> None:
    key = f"{ip}:{username}"
    now = time.monotonic()
    attempts = [at for at in _login_failures.get(key, []) if now - at < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_MAX_FAILURES:
        raise HTTPException(429, "尝试次数过多，请稍后再试")
    _login_failures[key] = attempts


def _record_login_failure(ip: str, username: str) -> None:
    key = f"{ip}:{username}"
    _login_failures.setdefault(key, []).append(time.monotonic())


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePwdBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(body: LoginBody, response: Response, request: Request):
    ip = _client_ip(request)
    _check_login_rate(ip, body.username)
    admin_user = await settings.get("admin_username") or config.ADMIN_USER
    if body.username != admin_user:
        _record_login_failure(ip, body.username)
        raise HTTPException(401, "wrong username or password")
    stored = await settings.get("admin_password_hash")
    if not auth.verify_password(body.password, stored):
        _record_login_failure(ip, body.username)
        raise HTTPException(401, "wrong username or password")
    _login_failures.pop(f"{ip}:{body.username}", None)
    token = auth.create_token(body.username)
    response.set_cookie("fa_token", token, httponly=True, samesite="lax",
                        max_age=config.JWT_EXPIRE_HOURS * 3600)
    return {"ok": True, "token": token}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("fa_token")
    return {"ok": True}


@router.get("/me")
async def me(_: None = Depends(require_admin)):
    return {"ok": True}


@router.post("/change-password")
async def change_password(body: ChangePwdBody, _: None = Depends(require_admin)):
    stored = await settings.get("admin_password_hash")
    if not auth.verify_password(body.old_password, stored):
        raise HTTPException(400, "old password incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(400, "new password must be >= 6 chars")
    await settings.set_value("admin_password_hash", auth.hash_password(body.new_password))
    return {"ok": True}
