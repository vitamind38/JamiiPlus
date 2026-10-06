"""Template setup, CSRF and flash messages for the officer web app."""

import secrets
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from jamii_api import messages
from jamii_api.config import get_settings
from jamii_api.models import IssueStatus, Level, ReportStatus
from jamii_api.security import pseudonym
from jamii_api.services import scope

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_LABELS = {
    IssueStatus.RECEIVED: "Received",
    IssueStatus.ESCALATED: "Escalated",
    IssueStatus.ACTION_TAKEN: "Action taken",
    IssueStatus.RESOLVED: "Resolved",
    ReportStatus.NEEDS_REDACTION: "Needs redaction",
    ReportStatus.NEEDS_TRANSCRIPTION: "Needs transcript",
    ReportStatus.NEEDS_TAGGING: "Needs theme",
    ReportStatus.PROCESSING: "Processing",
    ReportStatus.GROUPED: "In an issue",
    ReportStatus.WITHDRAWN: "Withdrawn",
    "recheck": "Weekly re-check",
}
LEVEL_LABELS = {
    Level.CHA: "CHA",
    Level.SUBCOUNTY: "Sub-county",
    Level.COUNTY: "County",
    Level.NATIONAL: "National",
}

templates.env.globals.update(
    pseudonym=pseudonym,
    status_label=lambda s: STATUS_LABELS.get(s, s),
    level_label=lambda s: LEVEL_LABELS.get(s, s),
    level_name=messages.level_name,
    can_review=scope.can_review,
    is_admin=scope.is_admin,
    can_act_on=scope.can_act_on,
    demo_mode=lambda: get_settings().demo_mode,
)

# Shown on the demo's login page. Synthetic accounts created by seed.demo_data().
DEMO_LOGINS = [
    ("0700 000 004", "County officer", "sees the whole county, answers any issue"),
    ("0700 000 003", "Sub-county officer", "answers and escalates issues"),
    ("0700 000 002", "Community health assistant", "one unit; also reviews reports"),
    ("0700 000 005", "Reviewer", "tags reports in the review queue"),
    ("0700 000 001", "Admin", "units, people and themes"),
]
templates.env.globals["demo_logins"] = DEMO_LOGINS


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def check_csrf(request: Request) -> None:
    """Dependency for every state-changing form post."""
    form = await request.form()
    sent = form.get("csrf", "")
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(str(sent), expected):
        raise HTTPException(400, "The form expired. Go back, reload the page and try again.")


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, message])


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", None)
    ctx["csrf"] = csrf_token(request)
    ctx["flashes"] = request.session.pop("flash", [])
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
