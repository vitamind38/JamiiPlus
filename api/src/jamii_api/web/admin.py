"""Registering units, officers and CHPs, and managing the theme list."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from jamii_api import audit
from jamii_api.config import get_settings
from jamii_api.deps import DB, SessionUser
from jamii_api.models import Chp, CommunityHealthUnit, Role, Theme, User
from jamii_api.security import InvalidEmail, InvalidPhone, mask_email, mask_phone, normalize_email, normalize_phone
from jamii_api.services import scope
from jamii_api.web.common import check_csrf, flash, render

router = APIRouter(prefix="/admin", include_in_schema=False)
CSRF = [Depends(check_csrf)]


def _admin(user: User) -> User:
    if not scope.is_admin(user):
        raise HTTPException(403, "Admins only.")
    return user


def _back(request: Request, message: str, kind: str = "ok", anchor: str = "") -> RedirectResponse:
    flash(request, message, kind)
    return RedirectResponse("/admin" + anchor, 303)


def _commit(db, request: Request, ok: str, anchor: str) -> RedirectResponse:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _back(request, "That already exists (phone number or code is taken).", "error", anchor)
    return _back(request, ok, anchor=anchor)


@router.get("")
def index(request: Request, db: DB, user: SessionUser):
    _admin(user)
    return render(
        request,
        "admin/index.html",
        user=user,
        units=db.scalars(
            select(CommunityHealthUnit).order_by(
                CommunityHealthUnit.county, CommunityHealthUnit.sub_county, CommunityHealthUnit.name
            )
        ).all(),
        users=db.scalars(select(User).order_by(User.role, User.name)).unique().all(),
        chps=db.scalars(select(Chp).order_by(Chp.chu_id, Chp.id)).unique().all(),
        themes=db.scalars(select(Theme).order_by(Theme.sort_order, Theme.id)).all(),
        roles=list(Role),
        mask_phone=mask_phone,
        mask_email=mask_email,
        by_email=get_settings().message_channel == "email",
    )


def _optional_email(raw: str) -> str | None:
    return normalize_email(raw) if raw.strip() else None


@router.post("/units", dependencies=CSRF)
def add_unit(
    request: Request,
    db: DB,
    user: SessionUser,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    ward: Annotated[str, Form()],
    sub_county: Annotated[str, Form()],
    county: Annotated[str, Form()],
    lat: Annotated[str, Form()] = "",
    lon: Annotated[str, Form()] = "",
):
    _admin(user)
    geom = None
    if lat.strip() and lon.strip():
        try:
            geom = f"SRID=4326;POINT({float(lon)} {float(lat)})"
        except ValueError:
            return _back(request, "Latitude and longitude must be numbers.", "error", "#units")
    db.add(
        CommunityHealthUnit(
            code=code.strip(),
            name=name.strip(),
            ward=ward.strip(),
            sub_county=sub_county.strip(),
            county=county.strip(),
            geom=geom,
        )
    )
    audit.record("admin.unit_added", actor_type="user", actor_id=user.id, code=code)
    return _commit(db, request, f"Unit {name} added.", "#units")


@router.post("/users", dependencies=CSRF)
def add_user(
    request: Request,
    db: DB,
    user: SessionUser,
    phone: Annotated[str, Form()],
    name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    chu_id: Annotated[str, Form()] = "",
    sub_county: Annotated[str, Form()] = "",
    county: Annotated[str, Form()] = "",
    can_review: Annotated[str | None, Form()] = None,
    email: Annotated[str, Form()] = "",
):
    _admin(user)
    try:
        phone = normalize_phone(phone)
        role = Role(role)
        email = _optional_email(email)
    except (InvalidPhone, InvalidEmail, ValueError) as e:
        return _back(request, str(e), "error", "#users")
    unit = db.get(CommunityHealthUnit, int(chu_id)) if chu_id.isdigit() else None
    if role == Role.CHA and unit is None:
        return _back(request, "A CHA needs a community health unit.", "error", "#users")
    if role == Role.SUBCOUNTY and not (sub_county.strip() and county.strip()):
        return _back(request, "A sub-county officer needs a sub-county and county.", "error", "#users")
    if role == Role.COUNTY and not county.strip():
        return _back(request, "A county officer needs a county.", "error", "#users")
    new = User(
        phone=phone,
        email=email,
        name=name.strip(),
        role=role,
        can_review=bool(can_review) or role == Role.REVIEWER,
        chu_id=unit.id if unit else None,
        sub_county=(unit.sub_county if unit else sub_county.strip()) or None,
        county=(unit.county if unit else county.strip()) or None,
    )
    db.add(new)
    audit.record("admin.user_added", actor_type="user", actor_id=user.id, role=role.value)
    return _commit(db, request, f"{name} added as {role.value}.", "#users")


@router.post("/users/{user_id}/toggle", dependencies=CSRF)
def toggle_user(request: Request, db: DB, user: SessionUser, user_id: int):
    _admin(user)
    other = db.get(User, user_id)
    if other is None or other.id == user.id:
        return _back(request, "You cannot deactivate yourself.", "error", "#users")
    other.active = not other.active
    other.token_version += 1  # signs them out everywhere
    audit.record(
        "admin.user_toggled",
        actor_type="user",
        actor_id=user.id,
        object_type="user",
        object_id=other.id,
        active=other.active,
    )
    return _commit(db, request, f"{other.name} is now {'active' if other.active else 'inactive'}.", "#users")


@router.post("/chps", dependencies=CSRF)
def add_chp(
    request: Request,
    db: DB,
    user: SessionUser,
    phone: Annotated[str, Form()],
    chu_id: Annotated[int, Form()],
    language: Annotated[str, Form()] = "sw",
    email: Annotated[str, Form()] = "",
):
    _admin(user)
    try:
        phone = normalize_phone(phone)
        email = _optional_email(email)
    except (InvalidPhone, InvalidEmail) as e:
        return _back(request, str(e), "error", "#chps")
    if db.get(CommunityHealthUnit, chu_id) is None:
        return _back(request, "Choose a community health unit.", "error", "#chps")
    db.add(Chp(phone=phone, email=email, chu_id=chu_id, language="en" if language == "en" else "sw"))
    audit.record("admin.chp_added", actor_type="user", actor_id=user.id, chu_id=chu_id)
    return _commit(db, request, "CHP registered. They can now log in with their phone number.", "#chps")


@router.post("/chps/{chp_id}/toggle", dependencies=CSRF)
def toggle_chp(request: Request, db: DB, user: SessionUser, chp_id: int):
    _admin(user)
    chp = db.get(Chp, chp_id)
    if chp is None:
        raise HTTPException(404)
    chp.active = not chp.active
    chp.token_version += 1
    audit.record(
        "admin.chp_toggled", actor_type="user", actor_id=user.id, object_type="chp", object_id=chp.id, active=chp.active
    )
    return _commit(db, request, f"CHP is now {'active' if chp.active else 'inactive'}.", "#chps")


@router.post("/users/{user_id}/email", dependencies=CSRF)
def set_user_email(request: Request, db: DB, user: SessionUser, user_id: int, email: Annotated[str, Form()] = ""):
    _admin(user)
    other = db.get(User, user_id)
    if other is None:
        raise HTTPException(404)
    return _set_email(request, db, user, other, "user", email, "#users")


@router.post("/chps/{chp_id}/email", dependencies=CSRF)
def set_chp_email(request: Request, db: DB, user: SessionUser, chp_id: int, email: Annotated[str, Form()] = ""):
    _admin(user)
    chp = db.get(Chp, chp_id)
    if chp is None:
        raise HTTPException(404)
    return _set_email(request, db, user, chp, "chp", email, "#chps")


def _set_email(request: Request, db, user: User, account: User | Chp, kind: str, raw: str, anchor: str):
    try:
        account.email = normalize_email(raw)
    except InvalidEmail as e:
        return _back(request, str(e), "error", anchor)
    audit.record("admin.email_set", actor_type="user", actor_id=user.id, object_type=kind, object_id=account.id)
    return _commit(db, request, f"Email saved: {mask_email(account.email)}.", anchor)


@router.post("/themes", dependencies=CSRF)
def add_theme(
    request: Request,
    db: DB,
    user: SessionUser,
    code: Annotated[str, Form()],
    label_en: Annotated[str, Form()],
    label_sw: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    keywords: Annotated[str, Form()] = "",
):
    """New themes come from people reviewing clusters, never from a model."""
    _admin(user)
    code = re.sub(r"[^a-z0-9_]", "_", code.strip().lower())
    if not code:
        return _back(request, "Give the theme a short code.", "error", "#themes")
    db.add(
        Theme(
            code=code,
            label_en=label_en.strip(),
            label_sw=label_sw.strip(),
            description=description.strip(),
            keywords=[k.strip().lower() for k in keywords.split(",") if k.strip()],
            created_by=user.id,
            sort_order=90,
        )
    )
    audit.record("admin.theme_added", actor_type="user", actor_id=user.id, code=code)
    return _commit(db, request, f"Theme {label_en} added.", "#themes")


@router.post("/themes/{theme_id}/toggle", dependencies=CSRF)
def toggle_theme(request: Request, db: DB, user: SessionUser, theme_id: int):
    _admin(user)
    theme = db.get(Theme, theme_id)
    if theme is None:
        raise HTTPException(404)
    theme.active = not theme.active
    audit.record(
        "admin.theme_toggled",
        actor_type="user",
        actor_id=user.id,
        object_type="theme",
        object_id=theme.id,
        active=theme.active,
    )
    return _commit(db, request, f"{theme.label_en} is now {'active' if theme.active else 'hidden'}.", "#themes")
