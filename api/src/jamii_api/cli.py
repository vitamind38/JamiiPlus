"""Operator commands: `jamii <command>`."""

import argparse
import csv
import json
import sys

from sqlalchemy import select

from jamii_api.config import get_settings
from jamii_api.db import Base, get_engine, session_scope
from jamii_api.models import Classification, Report, ReportStatus, Role, Theme, Transcript, User
from jamii_api.security import normalize_phone
from jamii_api.seed import demo_data, seed_themes


def cmd_init_local(_: argparse.Namespace) -> None:
    """Create tables directly. Local SQLite development only; deployments use Alembic."""
    if get_settings().environment != "local":
        sys.exit("init-local is for local development. Run `alembic upgrade head` instead.")
    Base.metadata.create_all(get_engine())
    print("Tables created.")


def cmd_seed_themes(_: argparse.Namespace) -> None:
    with session_scope() as db:
        print(f"{seed_themes(db)} theme(s) added.")


def cmd_create_admin(args: argparse.Namespace) -> None:
    phone = normalize_phone(args.phone)
    with session_scope() as db:
        if db.scalar(select(User).where(User.phone == phone)):
            sys.exit("That phone number already has an account.")
        db.add(User(phone=phone, name=args.name, role=Role.ADMIN))
    print(f"Admin {args.name} created. Log in at {get_settings().base_url}/login")


def cmd_demo_data(args: argparse.Namespace) -> None:
    if get_settings().environment == "production":
        sys.exit("Demo data is never loaded into production.")
    with session_scope() as db:
        print(demo_data(db, reports_per_chp=args.per_chp))


def cmd_export_labelled(args: argparse.Namespace) -> None:
    """Human-labelled reports for training and evaluation. No CHP identifiers leave the database."""
    with session_scope() as db, open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "report_id",
                "language",
                "channel",
                "text",
                "final_theme",
                "model_theme",
                "model_confidence",
                "model_version",
                "human_reviewed",
                "created_at",
            ]
        )
        rows = db.scalars(
            select(Report)
            .join(Classification)
            .where(Report.status == ReportStatus.GROUPED, Classification.final_theme.isnot(None))
            .order_by(Report.id)
        ).unique()
        n = 0
        for r in rows:
            c = r.classification
            human = c.reviewed_by is not None or c.rechecked_by is not None
            if args.human_only and not human:
                continue
            w.writerow(
                [
                    r.id,
                    r.language,
                    r.channel,
                    r.readable_text,
                    c.final_theme,
                    c.theme or "",
                    "" if c.confidence is None else round(c.confidence, 4),
                    c.model_version or "",
                    int(human),
                    r.created_at.isoformat(),
                ]
            )
            n += 1
    print(f"{n} labelled report(s) written to {args.out}")


def cmd_export_transcripts(args: argparse.Namespace) -> None:
    """Pairs of model and human transcripts, for word error rate."""
    with session_scope() as db, open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["report_id", "language", "machine_model_version", "machine_text", "human_text"])
        n = 0
        for t in db.scalars(select(Transcript).where(Transcript.machine_text.isnot(None))):
            w.writerow([t.report_id, t.report.language, t.machine_model_version, t.machine_text, t.text])
            n += 1
    print(f"{n} transcript pair(s) written to {args.out}")


def cmd_export_themes(args: argparse.Namespace) -> None:
    """Active themes and keywords, for evaluating the keyword baseline offline."""
    with session_scope() as db:
        themes = [{"code": t.code, "keywords": t.keywords} for t in db.scalars(select(Theme).where(Theme.active))]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(themes, f, ensure_ascii=False, indent=2)
    print(f"{len(themes)} theme(s) written to {args.out}")


def cmd_e2e(args: argparse.Namespace) -> None:
    """Scripted end-to-end run: voice note in, SMS out (staging)."""
    from jamii_api import e2e

    e2e.main(args.base_url, args.allow_production)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="jamii")
    sub = p.add_subparsers(required=True)
    sub.add_parser("init-local", help=cmd_init_local.__doc__).set_defaults(fn=cmd_init_local)
    sub.add_parser("seed-themes", help="Load the draft barrier taxonomy").set_defaults(fn=cmd_seed_themes)
    a = sub.add_parser("create-admin", help="Create the first admin")
    a.add_argument("--phone", required=True)
    a.add_argument("--name", required=True)
    a.set_defaults(fn=cmd_create_admin)
    d = sub.add_parser("demo-data", help="Synthetic units, people and reports (not production)")
    d.add_argument("--per-chp", type=int, default=6)
    d.set_defaults(fn=cmd_demo_data)
    e = sub.add_parser("export-labelled", help=cmd_export_labelled.__doc__)
    e.add_argument("--out", required=True)
    e.add_argument("--human-only", action="store_true")
    e.set_defaults(fn=cmd_export_labelled)
    t = sub.add_parser("export-transcripts", help=cmd_export_transcripts.__doc__)
    t.add_argument("--out", required=True)
    t.set_defaults(fn=cmd_export_transcripts)
    th = sub.add_parser("export-themes", help=cmd_export_themes.__doc__)
    th.add_argument("--out", required=True)
    th.set_defaults(fn=cmd_export_themes)
    e2 = sub.add_parser("e2e", help=cmd_e2e.__doc__)
    e2.add_argument("--base-url", default="http://127.0.0.1:8000")
    e2.add_argument("--allow-production", action="store_true")
    e2.set_defaults(fn=cmd_e2e)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
