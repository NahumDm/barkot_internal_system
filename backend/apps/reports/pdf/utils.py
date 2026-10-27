from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

COMPANY_NAME = "Barkot Bar & Restaurant"
COMPANY_ADDRESS = "Koye Feche"
COMPANY_PHONE = "+251 911483063"

LOGO_CANDIDATES = [
    # Backend-owned copy: resolves inside the API container (BASE_DIR=/app),
    # where the frontend tree is not mounted. This is the copy the PDF builder
    # actually finds at runtime.
    Path(settings.BASE_DIR) / "static" / "images" / "barkot-logo.png",
    # Host-side fallbacks (running the dev server outside Docker).
    Path(settings.BASE_DIR).parent / "frontend" / "public" / "images" / "barkot-logo.png",
    Path(settings.BASE_DIR) / ".." / "frontend" / "public" / "images" / "barkot-logo.png",
    Path(settings.BASE_DIR).parent / "images" / "barkot-logo.png",
]


def get_logo_path() -> Path | None:
    for candidate in LOGO_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()
    return None


def format_date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y")
    return str(value)


def format_datetime(value: Any | None = None) -> str:
    if value is None:
        value = timezone.localtime()
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y, %I:%M %p")
    return str(value)


def format_period(start: Any, end: Any) -> str:
    return f"{format_date(start)} - {format_date(end)}"
