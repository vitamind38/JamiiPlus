from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from jamii_api.db import get_db
from jamii_api.models import Chp, User
from jamii_api.security import read_token

DB = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str | None:
    # Caddy sets X-Forwarded-For; uvicorn runs with --proxy-headers behind it.
    return request.client.host if request.client else None


def current_chp(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Chp:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in again", {"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        claims = read_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized from None
    if claims.get("typ") != "chp":
        raise unauthorized
    chp = db.get(Chp, int(claims["sub"]))
    if chp is None or not chp.active or chp.token_version != claims.get("ver"):
        raise unauthorized
    return chp


CurrentChp = Annotated[Chp, Depends(current_chp)]


class LoginRequired(Exception):
    """Raised by web pages; the app turns it into a redirect to /login."""


def session_user(request: Request, db: DB) -> User:
    data = request.session.get("user")
    if not data:
        raise LoginRequired
    user = db.get(User, data.get("id"))
    if user is None or not user.active or user.token_version != data.get("ver"):
        request.session.clear()
        raise LoginRequired
    return user


SessionUser = Annotated[User, Depends(session_user)]
