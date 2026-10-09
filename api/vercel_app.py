"""Vercel entrypoint. The database is Supabase; Vercel only hosts and deploys.

The Kenyan-server deployment runs uvicorn in infra/docker instead; see docs/decisions.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jamii_api import bootstrap
from jamii_api.main import app  # noqa: F401  (Vercel serves this)

try:
    bootstrap.bootstrap()
except Exception:  # keep serving: /readyz shows the database problem instead of a crash loop
    logging.getLogger("jamii.bootstrap").exception("start-up failed")
