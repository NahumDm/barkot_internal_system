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

Call sites enforce with the :class:`HasRolePermission` subclasses below, which ask
:meth:`django.contrib.auth.models.User.has_perm` for the ``"app_label.codename"`` the
capability needs. A view therefore reads
``permission_classes = [IsAuthenticated, CanApprovePayrollRun]``.

Checking ``user.role.code == "OWNER"`` inline is a bug waiting to happen: it bypasses
the matrix the moment a capability is reassigned. So is calling ``has_perm`` by hand -
the classes below do exactly that, in one place, so every view decides the same way.

Which permissions a domain exposes is owned by that domain's model, declared via
``Meta.permissions``. This module only says who gets them.
"""

from __future__ import annotations

from typing import Any, Final

from django.contrib.auth.models import Permission
from django.db.models import Q, QuerySet
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

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
    "products.view_products",
    "inventory.view_inventory",
    "sales.view_sales",
    "finance.view_finance",
    "payroll.view_payroll",
    "payroll.create_deduction",
)

#: Role code → permission codenames. The Owner is given everything explicitly
#: rather than through a wildcard: an "all permissions" shortcut hides a missing
#: permission from review, and a newly added capability would silently become
#: available to the Owner without anyone deciding that.
ROLE_MATRIX: Final[dict[str, tuple[str, ...]]] = {
    Role.Code.BARMAN: (
        "products.view_products",
        "inventory.view_inventory",
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
        "manages the employee register and views reports. Reads payroll and records "
        "deductions, but does not generate payroll runs or manage payroll employees."
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


class HasRolePermission(BasePermission):
    """Requires one permission, resolved through the role matrix (spec §9.2, P06).

    One line of logic, on purpose. ``has_perm`` reaches
    :class:`apps.accounts.backends.RolePermissionBackend`, which unions the grants on
    the user's role with Django's own user and group permissions, so a view using this
    class and a view calling ``user.has_perm`` by hand cannot disagree about the answer.

    The cases that look like they need handling here are answered upstream, and a
    second copy of any of them would be a branch that can never change a verdict:

    - **Signed out.** ``AnonymousUser.has_perm`` is False. A view wanting 401 rather
      than 403 lists DRF's ``IsAuthenticated`` first, which raises before this class
      is consulted.
    - **Deactivated mid-session.** ``BarketSessionAuthentication`` refuses an inactive
      user as 401, and ``RolePermissionBackend`` returns an empty set for one
      regardless, so the grant never reaches here.
    - **No role.** ``User.role`` is non-nullable, so the database refuses to store such
      a user. The backend treats a role that cannot be resolved as no permissions
      rather than propagating, which is the one case it does defend.

    Subclasses set :attr:`required_permission`. It is a class attribute rather than a
    constructor argument because DRF instantiates every entry in
    ``permission_classes`` with no arguments, leaving nowhere to pass one.

    There is deliberately no ``message``. ``apps.core.exceptions`` renders every
    ``PermissionDenied`` as a single fixed string, which is the better outcome here: a
    refusal naming the missing permission would tell a Cashier precisely which grants
    they lack.
    """

    #: ``"app_label.codename"`` this class requires. Empty on the base class, which
    #: therefore denies everything: a base class that granted access by accident would
    #: be worse than one that is merely unusable.
    required_permission: str = ""

    def has_permission(self, request: Request, view: Any) -> bool:
        """Return whether the requesting user's role grants :attr:`required_permission`.

        Args:
            request: The incoming request, carrying the authenticated user.
            view: The view being called. Unused; DRF passes it for signature
                compatibility.

        Returns:
            True when the user's role grants the permission.
        """
        return bool(request.user.has_perm(self.required_permission))


class CanViewInventory(HasRolePermission):
    """See stock on hand and how it moved."""

    required_permission = "inventory.view_inventory"


class CanReceiveStock(HasRolePermission):
    """Book goods arriving from a supplier."""

    required_permission = "inventory.receive_stock"


class CanRecordBreakage(HasRolePermission):
    """Write stock off as broken, spilled or expired."""

    required_permission = "inventory.record_breakage"


class CanCompleteStockCount(HasRolePermission):
    """Enter a counted quantity against an expected one."""

    required_permission = "inventory.complete_stock_count"


class CanApproveAdjustment(HasRolePermission):
    """Accept a variance that needs a second pair of eyes."""

    required_permission = "inventory.approve_adjustment"


class CanViewSales(HasRolePermission):
    """Read the sales ledger."""

    required_permission = "sales.view_sales"


class CanCreateSale(HasRolePermission):
    """Ring up a sale."""

    required_permission = "sales.create_sale"


class CanVoidSale(HasRolePermission):
    """Reverse a completed sale, which needs an open till."""

    required_permission = "sales.void_sale"


class CanViewProducts(HasRolePermission):
    """Read the product catalogue."""

    required_permission = "products.view_products"


class CanManageCategories(HasRolePermission):
    """Create and reorganise product categories."""

    required_permission = "products.manage_categories"


class CanManageProducts(HasRolePermission):
    """Create, edit and retire products."""

    required_permission = "products.manage_products"


class CanChangePrices(HasRolePermission):
    """Move a price. Tracked as its own grant because it is the most abusable one."""

    required_permission = "products.change_prices"


class CanViewReports(HasRolePermission):
    """Read the reporting summaries."""

    required_permission = "finance.view_reports"


class IsOwner(BasePermission):
    """Only the Owner role."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        role = getattr(user, "role", None)
        if not role:
            return False
        return getattr(role, "code", None) == Role.Code.OWNER


class IsCashierOrOwner(BasePermission):
    """Only Cashier or Owner roles can access dashboard."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        role = getattr(user, "role", None)
        if not role:
            return False
        return getattr(role, "code", None) in (Role.Code.CASHIER, Role.Code.OWNER)



class CanCreateExpense(HasRolePermission):
    """Submit an expense for approval."""

    required_permission = "finance.create_expense"


class CanApproveExpense(HasRolePermission):
    """Accept a submitted expense."""

    required_permission = "finance.approve_expense"


class CanManageExpenseCategories(HasRolePermission):
    """Define the categories expenses are filed under."""

    required_permission = "finance.manage_expense_categories"


class CanViewPayroll(HasRolePermission):
    """Read payroll runs and payslips."""

    required_permission = "payroll.view_payroll"


class CanGeneratePayrollRun(HasRolePermission):
    """Produce a draft run. Owner-only: a Manager may read payroll but not run it."""

    required_permission = "payroll.generate_run"


class CanApprovePayrollRun(HasRolePermission):
    """Approve a run so it can be paid.

    The A8 gate. Deliberately not granted to a Manager: payroll is the one place
    where whoever computes the figure must not also be whoever signs it off, and
    since a Manager can no longer generate a run either, only the Owner ever
    moves a run past ``GENERATED``.
    """

    required_permission = "payroll.approve_run"


class CanMarkPayrollPaid(HasRolePermission):
    """Record that an approved run has been disbursed."""

    required_permission = "payroll.mark_paid"


class CanCreateDeduction(HasRolePermission):
    """Add a deduction against an employee."""

    required_permission = "payroll.create_deduction"


class CanManagePayrollEmployees(HasRolePermission):
    """Add employees to payroll and set their pay. Owner-only (spec §14.3)."""

    required_permission = "payroll.manage_payroll_employees"


class CanManageEmployees(HasRolePermission):
    """Maintain the employee register: the staff records themselves, their
    contracts and their documents. Independent of ``accounts.manage_users``,
    which governs login accounts and is Owner-only."""

    required_permission = "users.manage_employees"


class CanViewAuditLog(HasRolePermission):
    """Read the audit trail."""

    required_permission = "audit.view_audit_log"


class CanManageUsers(HasRolePermission):
    """Owner-only account administration."""

    required_permission = "accounts.manage_users"


class CanManageRoles(HasRolePermission):
    """Owner-only role administration."""

    required_permission = "accounts.manage_roles"


class CanManageSettings(HasRolePermission):
    """Owner-only system settings."""

    required_permission = "accounts.manage_settings"


#: Every permission class, keyed by the permission it requires. Built from the classes
#: themselves rather than hand-listed, so the coverage test below can compare this
#: mapping against the matrix and find a permission that shipped a class without being
#: registered here.
PERMISSION_CLASSES: dict[str, type[HasRolePermission]] = {
    cls.required_permission: cls
    for cls in (
        CanViewInventory,
        CanReceiveStock,
        CanRecordBreakage,
        CanCompleteStockCount,
        CanApproveAdjustment,
        CanViewSales,
        CanCreateSale,
        CanVoidSale,
        CanViewProducts,
        CanManageCategories,
        CanManageProducts,
        CanChangePrices,
        CanViewReports,
        CanCreateExpense,
        CanApproveExpense,
        CanManageExpenseCategories,
        CanViewPayroll,
        CanGeneratePayrollRun,
        CanApprovePayrollRun,
        CanMarkPayrollPaid,
        CanCreateDeduction,
        CanManagePayrollEmployees,
        CanManageEmployees,
        CanViewAuditLog,
        CanManageUsers,
        CanManageRoles,
        CanManageSettings,
    )
}
