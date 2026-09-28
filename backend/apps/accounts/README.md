# accounts

Authentication, sessions, roles and permissions.

Owns: login/logout, session lifecycle, business role assignment, permission resolution.
Depends on: `core`, `audit`.
Web MVP uses Django session auth with secure HttpOnly cookies and CSRF (spec §9.1).
