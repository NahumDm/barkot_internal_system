# Adding an API Endpoint

This guide is the implementation checklist for adding a new Barkot domain
endpoint. It is based on the shipped Products and Sales verticals. The
architecture specification, client decisions, and ADRs remain authoritative
when this guide and an implementation disagree.

## Before Writing Code

1. Confirm that the resource and workflow are defined by the architecture
   specification and `docs/business/client-decisions.md`. Do not invent a
   business concept to fill an empty screen.
2. Identify the use case, actor, permission, state transitions, financial or
   stock effects, audit event, and idempotency requirement.
3. Check `backend/apps/accounts/permissions.py` for the existing permission
   class. Add a role-matrix entry and permission class only when the use case
   is genuinely new; views must never branch on `user.role`.
4. Decide whether the endpoint is a read, a state-changing write, or a
   compensating action. Historical financial and stock records are voided or
   reversed, never deleted or edited in place.

## Backend Layers

Use the owning Django app under `backend/apps/<domain>/`. Keep each layer's
responsibility narrow.

### Model

Add or update the model in `models.py` when the domain needs persistence.

- Put domain constraints in `Meta.constraints` and model validation where they
  apply to every caller.
- Use `Decimal`/`NUMERIC` for money and quantities; never use floats.
- Store `currency` explicitly as `ETB` where money is present.
- Store the price used on each transaction line; never reconstruct history from
  the current catalogue price.
- Prefer status transitions and reversal records to deletion.
- Add `created_by`, `updated_by`, or the appropriate actor fields when the
  specification requires accountability.

Create the migration from `backend` and inspect it before committing:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations
```

### Service

Put business behavior in `<domain>/services.py`, not in a view. Services
should follow this order:

1. Validate all business preconditions before writing.
2. Enter one `transaction.atomic` block for the complete business event.
3. Write the domain records and all linked ledger records.
4. Record the audit event with `AuditLog.record(...)`.
5. Return the saved object after the transaction succeeds.

Raise a specific `BarkotDomainError` subclass from
`backend/apps/core/exceptions.py` for expected domain failures. The global
exception handler maps it to the standard error envelope; do not construct
ad-hoc error responses in a view.

For writes that create a financial, stock, or otherwise retryable business
event, use the idempotency helpers in `backend/apps/core/idempotency.py` at the
service layer. A required HTTP header is not part of the current contract.

### Serializer

Add request and response serializers in `<domain>/serializers.py`.

- Validate shape, types, field limits, choices, and cross-field input here.
- Use `DecimalField(max_digits=14, decimal_places=2)` for money.
- Keep success serializers separate from write serializers when their shapes
  differ, as in `ProductCreateSerializer` and `SaleCreateSerializer`.
- Return only stable response fields. The global handler owns the error
  envelope: `{"error": {"code", "message", "details"}}`.

### Viewset

Add a viewset in `<domain>/views.py` and make the contract explicit.

- Use `IsAuthenticated` plus the domain permission class for every action.
- Resolve permissions in `get_permissions()` per action. List/retrieve and
  state-changing actions normally have different permissions.
- Set `pagination_class = BarkotPagination` and `paginator = BarkotPagination()`
  on list-capable viewsets.
- Keep query filtering in `get_queryset()` and business writes in services.
- Use `@extend_schema`/`@extend_schema_view` with a domain tag and explicit
  request/response serializers.
- Pass `request.user` as the actor to the service.
- Do not add `AllowAny`, browsable renderers, a custom paginator, or a direct
  role check.

The automatic contract suite enforces the mounted endpoint rules:

- private by default;
- session authentication only;
- no browsable API;
- `BarkotPagination` for paginated resources; and
- a `/api/v1/` path.

### URLs

Create `<domain>/urls.py` with a `DefaultRouter`, and register it from
`backend/config/api_urls.py`:

```python
path("<domain>/", include("apps.<domain>.urls")),
```

Use an explicit basename. Register fixed path segments before an empty-prefix
resource route. For example, Products registers `categories` before `""`,
otherwise `products/categories/` is swallowed by the product detail wildcard.

After mounting the router, the contract suite discovers the endpoint
automatically. Do not add an exemption to hide a violation.

## Tests

Start with acceptance evidence, then implement the endpoint.

- Add a focused domain or API test for the business invariant.
- Test permission behavior through the permission matrix, not view-level role
  branches.
- For a financial or stock write, verify the linked records and exactly-once
  behavior, including an idempotent retry.
- Verify failure before commit leaves no partial records or movements.
- Add audit assertions for every state-changing path.
- Add filtering, pagination, error-envelope, and serializer validation cases as
  appropriate.

The contract suite in `backend/tests/api/test_contract.py` covers every
registered endpoint, so a new endpoint must satisfy the global rules without a
new endpoint-specific exemption.

## Frontend Integration

Add the typed client in `frontend/src/lib/api/<domain>.ts` using `apiFetch` from
`frontend/src/lib/api/client.ts`. Define response and input interfaces there;
keep API paths trailing-slash terminated. Surface `ApiError.code` for UI
branching rather than parsing error messages. Export the client from
`frontend/src/lib/api/index.ts` when the local convention requires it.

Put reusable domain logic in `frontend/src/features/<domain>/`. Put protected
screens under `frontend/src/app/(app)/`; that route group is the structural
authentication boundary. Follow the existing UI/UX specification for layout,
permissions, loading, empty, validation, and unavailable-session states.

Add both kinds of browser evidence when the behavior is user-facing:

- a stubbed test under `frontend/tests/e2e/` for deterministic error and auth
  states;
- a live test under `frontend/tests/live/` for the real API and database
  invariant.

Keep the stubbed and live Playwright projects as separate invocations. Browser
route interception does not intercept server-side rendering requests.

## Verification

Run the focused tests first, then the full gates from the relevant directory.
The backend commands require the development database on port `5433` and the
local database password; do not commit credentials.

```powershell
# From backend
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest -q

# From frontend
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Before declaring the endpoint complete, inspect the generated schema at
`/api/schema/`, confirm the route appears under the expected domain tag, and
verify `git status` contains only the intended changes.
