"""Role → permission matrix (spec §9.2, principle P06).

This module is the authoritative answer to "what may this role do?". The matrix
is declared as data so that:

- it is reviewable by the Owner in one place rather than scattered across view
  ``if`` statements;
- a missing permission fails a test (:mod:`apps.accounts.tests.test_permissions`)
  rather than silently denying access at 2am, and ``manage.py bootstrap_roles
  --check`` fails in CI;
- the seed migration and the test both read the same constant, so they cannot
  disagree.

Call sites must enforce with :meth:`django.contrib.auth.models.User.has_perm`
using the ``"app_label.codename"`` form. Checking ``user.role.code == "OWNER"``
inline is a bug waiting to happen: it bypasses the matrix the moment a capability
is reassigned.

Which permissions a domain exposes is owned by that domain's model, declared via
``Meta.permissions``. This module only says who gets them.
"""

from __future__ import annotations

from typing import Final

from django.contrib.auth.models import Permission
from django.db.models import Q, QuerySet

from apps.accounts.models import Role

# ── Capability catalogue ────────────────────────────────────────────────────
# Grouped by domain, in the order a staff member meets them during a shift.
# Every entry must exist as a ``Meta.permissions`` entry on the named model; the
# matrix test enforces that.

INVENTORY_PERMISSIONS: Final[tuple[str, ...]] = (
    "inventory.view_inventory",
    "inventory.receive_stock",
    "inventory.record_breakage",
    "inventory.complete_stock_count",
    "inventory.approve_adjustment",
)

SALES_PERMISSIONS: Final[tuple[str, ...]] = (
    "sales.view_sales",
    "sales.create_sale",
    "sales.void_sale",
)

PRODUCT_PERMISSIONS: Final[tuple[str, ...]] = (
    "products.view_products",
    "products.manage_categories",
    "products.manage_products",
    "products.change_prices",
)

FINANCE_PERMISSIONS: Final[tuple[str, ...]] = (
    "finance.view_reports",
    "finance.create_expense",
    "finance.approve_expense",
    "finance.manage_expense_categories",
)

PAYROLL_PERMISSIONS: Final[tuple[str, ...]] = (
    "payroll.view_payroll",
    "payroll.generate_run",
    "payroll.approve_run",
    "payroll.mark_paid",
    "payroll.create_deduction",
    "payroll.manage_payroll_employees",
)

ADMINISTRATION_PERMISSIONS: Final[tuple[str, ...]] = (
    "users.manage_employees",
    "audit.view_audit_log",
    "accounts.manage_users",
    "accounts.manage_roles",
    "accounts.manage_settings",
)

#: Every permission the system knows about, in one flat tuple.
ALL_PERMISSIONS: Final[tuple[str, ...]] = (
    INVENTORY_PERMISSIONS
    + SALES_PERMISSIONS
    + PRODUCT_PERMISSIONS
    + FINANCE_PERMISSIONS
    + PAYROLL_PERMISSIONS
    + ADMINISTRATION_PERMISSIONS
)

_CASHIER_SHOPFLOOR: Final[tuple[str, ...]] = (
    "products.view_products",
    "inventory.view_inventory",
    "inventory.complete_stock_count",
    "sales.view_sales",
    "sales.create_sale",
)

_MANAGER: Final[tuple[str, ...]] = (
    *_CASHIER_SHOPFLOOR,
    "inventory.receive_stock",
    "inventory.record_breakage",
    "inventory.approve_adjustment",
    "sales.void_sale",
    "finance.view_reports",
    "finance.create_expense",
    "finance.approve_expense",
    "finance.manage_expense_categories",
    "payroll.view_payroll",
    "payroll.generate_run",
    "payroll.create_deduction",
    "payroll.manage_payroll_employees",
    "users.manage_employees",
    "audit.view_audit_log",
)

#: Role code → permission codenames. The Owner is given everything explicitly
#: rather than through a wildcard: an "all permissions" shortcut hides a missing
#: permission from review, and a newly added capability would silently become
#: available to the Owner without anyone deciding that.
ROLE_MATRIX: Final[dict[str, tuple[str, ...]]] = {
    Role.Code.BARMAN: (
        "products.view_products",
        "inventory.view_inventory",
        "inventory.receive_stock",
        "inventory.record_breakage",
        "sales.view_sales",
    ),
    Role.Code.CASHIER: _CASHIER_SHOPFLOOR,
    Role.Code.MANAGER: _MANAGER,
    Role.Code.OWNER: ALL_PERMISSIONS,
}

#: Descriptive text for each role, used by the seed migration.
ROLE_DESCRIPTIONS: Final[dict[str, str]] = {
    Role.Code.BARMAN: (
        "Receives stock and records breakage or waste. Does not sell, count stock or "
        "approve adjustments."
    ),
    Role.Code.CASHIER: (
        "Records individual sales and completes stock counts. Cannot void sales or "
        "approve variances."
    ),
    Role.Code.MANAGER: (
        "Reviews and approves counts and variances, records and approves expenses, "
        "generates payroll, manages employees and views reports. Generates but does "
        "not approve payroll."
    ),
    Role.Code.OWNER: (
        "Full access. Sole approver of payroll runs and the only role that manages "
        "users, roles, products and system settings."
    ),
}

#: A well-known permission name, for type-safe reference at call sites.
ViewSales = "sales.view_sales"
CreateSale = "sales.create_sale"
VoidSale = "sales.void_sale"
ReceiveStock = "inventory.receive_stock"
RecordBreakage = "inventory.record_breakage"
CompleteStockCount = "inventory.complete_stock_count"
ApproveAdjustment = "inventory.approve_adjustment"
CreateExpense = "finance.create_expense"
ApproveExpense = "finance.approve_expense"
ViewReports = "finance.view_reports"
GeneratePayrollRun = "payroll.generate_run"
ApprovePayrollRun = "payroll.approve_run"
MarkPayrollPaid = "payroll.mark_paid"
ManageUsers = "accounts.manage_users"


def split_permission(permission: str) -> tuple[str, str]:
    """Split ``"app.codename"`` into its two halves.

    Raises:
        ValueError: If the string is not in ``app.codename`` form.
    """
    app_label, separator, codename = permission.partition(".")
    if not separator or not app_label or not codename:
        raise ValueError(f"Permission {permission!r} must be in 'app_label.codename' form.")
    return app_label, codename


def filter_existing(permissions: tuple[str, ...]) -> QuerySet[Permission]:
    """Return a queryset selecting the named ``auth.Permission`` rows.

    Args:
        permissions: ``"app_label.codename"`` strings.

    Returns:
        A queryset of matching permissions. Absent rows are simply missing from
        the result; :mod:`apps.accounts.tests.test_permissions` is what turns a
        genuinely missing permission into a failure.
    """
    query = Q()
    for permission in permissions:
        app_label, codename = split_permission(permission)
        query |= Q(content_type__app_label=app_label, codename=codename)
    return Permission.objects.filter(query).distinct()
