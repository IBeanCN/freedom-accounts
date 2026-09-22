"""Auth router: login, change password, me."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..core import auth, database, settings
from .deps import require_admin

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePwdBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(body: LoginBody, response: Response):
    db = await database.get_db()
    admin_user = await settings.get("admin_username") or "admin"
    if body.username != admin_user:
        raise HTTPException(401, "wrong username or password")
    stored = await settings.get("admin_password_hash")
    if not auth.verify_password(body.password, stored):
        raise HTTPException(401, "wrong username or password")
    token = auth.create_token(body.username)
    response.set_cookie("fa_token", token, httponly=True, samesite="lax",
                        max_age=24 * 3600)
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
