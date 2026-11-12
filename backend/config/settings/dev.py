"""Local development settings.

Safe defaults so `python manage.py runserver` works out of the box.
Never import prod settings here; each environment imports base directly.
"""

import os

from .base import *  # noqa: F403

# Pinned on: a developer wants the tracebacks and auto-reload, and the module
# name (config.settings.dev) is itself the signal that this is not production.
DEBUG = True

_dev_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = (
    [host.strip() for host in _dev_hosts.split(",") if host.strip()]
    if _dev_hosts
    else ["localhost", "127.0.0.1", "0.0.0.0", "testserver"]
)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

from config.logging import get_logging_config  # noqa: E402

LOGGING = get_logging_config()
