"""Vercel entrypoint for the public demo (synthetic data only).

Real deployments run uvicorn in infra/docker on a Kenyan server; see docs/decisions.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jamii_api import demo
from jamii_api.main import app  # noqa: F401  (Vercel serves this)

try:
    demo.bootstrap()
except Exception:  # keep serving: /readyz shows the database problem instead of a crash loop
    logging.getLogger("jamii.demo").exception("demo bootstrap failed")
