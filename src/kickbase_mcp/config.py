"""Credential and settings resolution.

Resolution order for credentials:
1. Environment variables (KICKBASE_EMAIL / KICKBASE_PASSWORD) — this includes
   values injected by `pass-cli run --env-file ...`.
2. A `.env` file in the working directory (loaded via python-dotenv).

When using Proton Pass, put `pass://` secret references in the .env file and
launch the server through `pass-cli run` (see README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Settings:
    email: str
    password: str
    league_id: str | None = None


_MISSING = """\
Kickbase credentials are not configured.

Set KICKBASE_EMAIL and KICKBASE_PASSWORD via one of:
  * environment variables
  * a .env file next to where the server runs (plain values, or pass://...
    references if you launch through `pass-cli run --env-file .env`)

Optionally set KICKBASE_LEAGUE_ID to pin a league.\
"""


def load_settings() -> Settings:
    load_dotenv()

    email = os.environ.get("KICKBASE_EMAIL", "").strip()
    password = os.environ.get("KICKBASE_PASSWORD", "").strip()
    league_id = os.environ.get("KICKBASE_LEAGUE_ID", "").strip() or None

    if not email or not password:
        raise RuntimeError(_MISSING)
    if email.startswith("pass://") or password.startswith("pass://"):
        raise RuntimeError(
            "Unresolved pass:// secret reference detected. Launch the server via "
            "`pass-cli run --env-file .env -- <command>` so secrets get injected."
        )
    return Settings(email=email, password=password, league_id=league_id)
