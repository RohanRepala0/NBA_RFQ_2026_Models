"""Phone alerts through ntfy (https://ntfy.sh): the daily job's new tickets, fades and results.

The topic is a secret (anyone who knows it can read the alerts): it comes from NTFY_TOPIC in the
environment (a GitHub Actions secret for the daily job) or the git-ignored .env, and is never
printed, logged or written to a file. With no topic set, nothing is sent.
"""
from __future__ import annotations

import requests

from . import config

TOPIC_ENV, SERVER_ENV = "NTFY_TOPIC", "NTFY_SERVER"
DEFAULT_SERVER = "https://ntfy.sh"
MAX_BODY = 3800                    # ntfy turns longer messages into attachments


def configured() -> bool:
    return bool(config.env_value(TOPIC_ENV))


def send(title: str, body: str, priority: str = "default", post=None) -> bool:
    """Send one alert; False (never an exception) when no topic is set or the post fails."""
    topic = config.env_value(TOPIC_ENV)
    if not topic:
        return False
    server = (config.env_value(SERVER_ENV) or DEFAULT_SERVER).rstrip("/")
    post = post or requests.post
    text = body if len(body) <= MAX_BODY else body[:MAX_BODY - 20] + "\n... (see bets/)"
    try:
        r = post(f"{server}/{topic}", data=text.encode("utf-8"),
                 headers={"Title": title.encode("ascii", "replace").decode(), "Priority": priority}, timeout=20)
        return 200 <= getattr(r, "status_code", 0) < 300
    except Exception:                  # an alert never stops the job; the reason could echo the URL
        return False
