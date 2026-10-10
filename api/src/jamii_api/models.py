"""The MVP data model. No table holds a patient identity.

Core: chp, community_health_unit, report, transcript, classification, issue, response.
Supporting: theme, app_user, sms_outbox, otp_challenge, spike_alert.
The audit log lives in a separate database (see audit.py).
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jamii_api.db.base import Base, GeometryType, TZDateTime, utcnow


class Channel(StrEnum):
    APP = "app"  # tap-to-categorise and/or typed text in the Flutter app
    VOICE = "voice"  # voice note recorded in the Flutter app
    SMS = "sms"
    USSD = "ussd"


class ReportStatus(StrEnum):
    PROCESSING = "processing"  # waiting for workers (assisted mode only)
    NEEDS_REDACTION = "needs_redaction"  # automatic redaction failed: held for a person
    NEEDS_TRANSCRIPTION = "needs_transcription"
    NEEDS_TAGGING = "needs_tagging"
    GROUPED = "grouped"  # theme is final and the report belongs to an issue
    WITHDRAWN = "withdrawn"  # the CHP asked for removal; content deleted


HUMAN_QUEUES = (ReportStatus.NEEDS_REDACTION, ReportStatus.NEEDS_TRANSCRIPTION, ReportStatus.NEEDS_TAGGING)


class IssueStatus(StrEnum):
    RECEIVED = "received"
    ESCALATED = "escalated"
    ACTION_TAKEN = "action_taken"
    RESOLVED = "resolved"


class Level(StrEnum):
    CHA = "cha"
    SUBCOUNTY = "subcounty"
    COUNTY = "county"
    NATIONAL = "national"

    def next(self) -> "Level | None":
        order = list(Level)
        i = order.index(self)
        return order[i + 1] if i + 1 < len(order) else None


class Role(StrEnum):
    CHA = "cha"
    SUBCOUNTY = "subcounty"
    COUNTY = "county"
    NATIONAL = "national"
    REVIEWER = "reviewer"  # central review team; tags reports, does not answer issues
    ADMIN = "admin"  # manages people, units and themes


class Resolution(StrEnum):
    ACTIONED = "actioned"
    NOT_ACTIONED = "not_actioned"  # CHPs are still told why


class ResponseKind(StrEnum):
    ESCALATED = "escalated"
    ACTION_TAKEN = "action_taken"
    RESOLVED = "resolved"


class CommunityHealthUnit(Base):
    __tablename__ = "community_health_unit"
    __table_args__ = (Index("ix_community_health_unit_geom", "geom", postgresql_using="gist"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    ward: Mapped[str] = mapped_column(String(120), index=True)
    sub_county: Mapped[str] = mapped_column(String(120), index=True)
    county: Mapped[str] = mapped_column(String(120), index=True)
    geom: Mapped[str | None] = mapped_column(GeometryType, nullable=True)  # point or polygon
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class Chp(Base):
    """A reporting Community Health Promoter. Supervisors only ever see a pseudonym."""

    __tablename__ = "chp"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)  # E.164: the login, and where SMS go
    email: Mapped[str | None] = mapped_column(String(254))  # where codes and replies go by email
    chu_id: Mapped[int] = mapped_column(ForeignKey("community_health_unit.id"), index=True)
    language: Mapped[str] = mapped_column(String(8), default="sw")
    role: Mapped[str] = mapped_column(String(20), default="chp")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consented_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    chu: Mapped[CommunityHealthUnit] = relationship(lazy="joined")


class User(Base):
    """Officers, reviewers and admins. Named, because a named person releases anything that leaves the system."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Scope: a CHA has a unit; sub-county and county officers have the matching name.
    chu_id: Mapped[int | None] = mapped_column(ForeignKey("community_health_unit.id"))
    sub_county: Mapped[str | None] = mapped_column(String(120))
    county: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    chu: Mapped[CommunityHealthUnit | None] = relationship(lazy="joined")


class Theme(Base):
    """The barrier taxonomy. It is data, not code: people add themes after reviewing clusters."""

    __tablename__ = "theme"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    label_en: Mapped[str] = mapped_column(String(120))
    label_sw: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)  # feeds the keyword baseline
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    def label(self, language: str) -> str:
        return self.label_sw if language == "sw" else self.label_en


class Issue(Base):
    """A cluster of reports about the same problem in the same ward."""

    __tablename__ = "issue"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_code: Mapped[str] = mapped_column(ForeignKey("theme.code"), index=True)
    ward: Mapped[str] = mapped_column(String(120), index=True)
    sub_county: Mapped[str] = mapped_column(String(120), index=True)
    county: Mapped[str] = mapped_column(String(120), index=True)
    level: Mapped[str] = mapped_column(String(20), default=Level.CHA)
    status: Mapped[str] = mapped_column(String(20), default=IssueStatus.RECEIVED, index=True)
    resolution: Mapped[str | None] = mapped_column(String(20))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    first_reported_at: Mapped[datetime] = mapped_column(TZDateTime)
    last_reported_at: Mapped[datetime] = mapped_column(TZDateTime)
    first_response_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)

    theme: Mapped[Theme] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined")


class Report(Base):
    """One barrier report. Location is kept to ward level, never a household."""

    __tablename__ = "report"
    __table_args__ = (UniqueConstraint("chp_id", "client_id", name="uq_report_chp_client"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chp_id: Mapped[int] = mapped_column(ForeignKey("chp.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(64))  # idempotency key from the app
    channel: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(8), default="sw")
    chu_id: Mapped[int] = mapped_column(ForeignKey("community_health_unit.id"), index=True)
    ward: Mapped[str] = mapped_column(String(120), index=True)
    sub_county: Mapped[str] = mapped_column(String(120), index=True)
    county: Mapped[str] = mapped_column(String(120), index=True)
    chp_theme_code: Mapped[str | None] = mapped_column(String(40))  # the category the CHP tapped
    # Text as submitted, after rule-based redaction. Unredacted text is never written.
    raw_text: Mapped[str | None] = mapped_column(Text)
    redaction: Mapped[str] = mapped_column(String(20), default="none")  # none | rules | rules+ner | manual
    audio_key: Mapped[str | None] = mapped_column(String(200))
    audio_mime: Mapped[str | None] = mapped_column(String(60))
    audio_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    text_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    hold_reason: Mapped[str | None] = mapped_column(String(200))
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("issue.id"), index=True)
    reported_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)  # phone clock, may be offline
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)  # server receipt
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow, index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    chp: Mapped[Chp] = relationship(lazy="joined")
    issue: Mapped[Issue | None] = relationship(lazy="joined")
    transcript: Mapped["Transcript | None"] = relationship(back_populates="report", uselist=False, lazy="joined")
    classification: Mapped["Classification | None"] = relationship(
        back_populates="report", uselist=False, lazy="joined"
    )

    @property
    def readable_text(self) -> str:
        """What an officer reads: typed text plus the transcript, both redacted."""
        parts = [p for p in (self.raw_text, self.transcript.text if self.transcript else None) if p]
        return "\n\n".join(parts)


class Transcript(Base):
    __tablename__ = "transcript"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id", ondelete="CASCADE"), unique=True)
    text: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(String(80))  # "human" when typed or corrected by a reviewer
    confidence: Mapped[float | None] = mapped_column(Float)
    # The model's original output, kept when a reviewer corrects it, to measure word error rate.
    machine_text: Mapped[str | None] = mapped_column(Text)
    machine_model_version: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)

    report: Mapped[Report] = relationship(back_populates="transcript")


class Classification(Base):
    """The model's theme guess (if any) and the human decision. final_theme is the label."""

    __tablename__ = "classification"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id", ondelete="CASCADE"), unique=True)
    theme: Mapped[str | None] = mapped_column(String(40))  # model guess
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(80))
    final_theme: Mapped[str | None] = mapped_column(ForeignKey("theme.code"), index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))  # null = accepted from model
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Weekly random re-check of model-accepted reports.
    recheck_theme: Mapped[str | None] = mapped_column(String(40))
    rechecked_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    rechecked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    recheck_requested_at: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    report: Mapped[Report] = relationship(back_populates="classification")


class Response(Base):
    """What an officer did, sent back to the CHPs whose reports make up the issue."""

    __tablename__ = "response"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issue.id"), index=True)
    officer_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    kind: Mapped[str] = mapped_column(String(20))
    action_text: Mapped[str] = mapped_column(Text)
    sms_text: Mapped[str] = mapped_column(Text)
    recipients: Mapped[int] = mapped_column(Integer, default=0)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    officer: Mapped[User] = relationship(lazy="joined")


class SmsOutbox(Base):
    """Every outbound SMS except one-time codes, so a dead queue never loses a message."""

    __tablename__ = "sms_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    chp_id: Mapped[int | None] = mapped_column(ForeignKey("chp.id"), index=True)
    phone: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))  # ack | status
    response_id: Mapped[int | None] = mapped_column(ForeignKey("response.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)  # queued | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    provider_id: Mapped[str | None] = mapped_column(String(80))
    delivery_status: Mapped[str | None] = mapped_column(String(40))
    next_attempt_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class OtpChallenge(Base):
    __tablename__ = "otp_challenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)


class SpikeAlert(Base):
    """A sudden rise in one theme in one ward. A person confirms it before anyone acts."""

    __tablename__ = "spike_alert"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_code: Mapped[str] = mapped_column(ForeignKey("theme.code"))
    ward: Mapped[str] = mapped_column(String(120))
    sub_county: Mapped[str] = mapped_column(String(120), index=True)
    county: Mapped[str] = mapped_column(String(120), index=True)
    window_start: Mapped[datetime] = mapped_column(TZDateTime)
    window_end: Mapped[datetime] = mapped_column(TZDateTime)
    count: Mapped[int] = mapped_column(Integer)
    baseline: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="proposed", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    theme: Mapped[Theme] = relationship(lazy="joined")
