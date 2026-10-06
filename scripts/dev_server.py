"""Run the API on SQLite with synthetic data, no Docker needed.

    python scripts/dev_server.py            # http://localhost:8000
    python scripts/dev_server.py --reset    # start from an empty database

SMS are printed to the console and login codes are shown on the login page. This is for
trying the UI on a laptop; the real stack is `docker compose` in infra/.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "var" / "dev"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    VAR.mkdir(parents=True, exist_ok=True)
    if args.reset:
        for f in ("jamii.db", "audit.db"):
            (VAR / f).unlink(missing_ok=True)
    os.environ.setdefault("JAMII_ENVIRONMENT", "local")
    os.environ.setdefault("JAMII_DATABASE_URL", f"sqlite:///{(VAR / 'jamii.db').as_posix()}")
    os.environ.setdefault("JAMII_AUDIT_DATABASE_URL", f"sqlite:///{(VAR / 'audit.db').as_posix()}")
    os.environ.setdefault("JAMII_STORAGE_BACKEND", "local")
    os.environ.setdefault("JAMII_STORAGE_LOCAL_DIR", str(VAR / "audio"))
    os.environ.setdefault("JAMII_SMS_BACKEND", "console")
    os.environ.setdefault("JAMII_QUEUE_ENABLED", "false")
    os.environ.setdefault("JAMII_DEV_SHOW_OTP", "true")
    os.environ.setdefault("JAMII_BASE_URL", f"http://localhost:{args.port}")
    sys.path.insert(0, str(ROOT / "api" / "src"))

    from sqlalchemy import select

    from jamii_api.db import Base, get_engine, session_scope
    from jamii_api.models import Report
    from jamii_api.seed import demo_data, seed_themes

    Base.metadata.create_all(get_engine())
    with session_scope() as db:
        seed_themes(db)
        if db.scalar(select(Report.id).limit(1)) is None:
            print("Loading synthetic demo data:", demo_data(db))
    print(
        "\nDemo logins (codes appear on the login page):\n"
        "  admin       0700 000 001\n"
        "  CHA         0700 000 002  (also reviews)\n"
        "  sub-county  0700 000 003\n"
        "  county      0700 000 004\n"
        "  reviewer    0700 000 005\n"
    )
    import uvicorn

    uvicorn.run("jamii_api.main:app", host="127.0.0.1", port=args.port, reload=False)


if __name__ == "__main__":
    main()
