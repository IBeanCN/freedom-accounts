"""Shared FastAPI dependencies."""
from fastapi import Depends, HTTPException, Request

from ..core import auth


async def require_admin(request: Request) -> None:
    token = request.cookies.get("fa_token") or ""
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token or auth.decode_token(token) is None:
        raise HTTPException(status_code=401, detail="unauthorized")
