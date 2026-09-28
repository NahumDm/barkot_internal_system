# Barkot backend dependency notes.
#
# base.txt  — runtime dependencies the application cannot boot without.
# prod.txt  — base + production-only additions (WSGI server, static files).
# dev.txt   — base + development/testing tooling.
#
# Version bounds in these files follow the architecture spec §5 / §26.2.
# Bounds are what we commit by hand. After a known-good install, freeze the
# exact resolved patches into a lock file:
#
#   python -m pip freeze > backend/requirements/requirements.lock
#
# so deployments are reproducible (spec P12 — pin exact production versions).