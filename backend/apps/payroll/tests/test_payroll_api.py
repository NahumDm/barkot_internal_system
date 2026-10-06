"""C2 payroll API acceptance tests.

The behaviour under test is separation of duties (spec §14.1, A8): a Manager
generates a payroll run and the Owner approves it. That split is the whole reason
``GENERATED`` and ``APPROVED`` are separate states, so the tests below assert both
halves — that a Manager *can* generate, and that a Manager *cannot* approve — because
a test covering only the first would still pass if the role matrix handed everyone
every permission.

The roster tests at the end cover the read that makes the create form usable:
``GET /payroll/profiles/`` is the only source of the ``profile`` id that
``POST /payroll/employees/`` asks for, so it needs the same permission, and it
must not offer someone who is already on payroll or who has left.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.payroll.models import Employee, PayrollDeduction, PayrollItem, PayrollRun
from apps.users.models import EmployeeProfile

pytestmark = pytest.mark.django_db

EMPLOYEES_URL = "/api/v1/payroll/employees/"
PROFILES_URL = "/api/v1/payroll/profiles/"
RUNS_URL = "/api/v1/payroll/runs/"
DEDUCTIONS_URL = "/api/v1/payroll/deductions/"
BALANCE_URL = "/api/v1/finance/balance/"
PERIOD = {"start": "2026-10-01", "end": "2026-10-31"}


@pytest.fixture
def profile() -> EmployeeProfile:
    return EmployeeProfile.objects.create(
        full_name="Selam Bekele",
        position="Head Cashier",
        phone_number="+251911234567",
        start_date="2026-01-05",
    )


@pytest.fixture
def employee(profile: EmployeeProfile) -> Employee:
    return Employee.from_profile(profile, monthly_wage=Decimal("18000.00"))


def _generate(client: Client, **overrides: Any) -> Any:
    """Generate a run as the signed-in user and return the JSON body."""
    payload: dict[str, Any] = {"period": "2026-10-09", "notes": "October"}
    payload.update(overrides)
    return client.post(RUNS_URL, payload, content_type="application/json")


def test_manager_generates_a_run_and_the_owner_approves_it(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    manager = staff_login(client, Role.Code.MANAGER)

    generated = _generate(client)

    assert generated.status_code == 201, generated.content
    body = generated.json()
    assert body["status"] == "GENERATED"
    # The stored period is normalised to the first of the month so a run is
    # uniquely identified by month regardless of the day that was typed.
    assert body["period_month"] == "2026-10-01"
    assert body["gross_total"] == "18000.00"
    assert body["net_total"] == "18000.00"

    run = PayrollRun.objects.get(pk=body["id"])
    assert run.created_by == manager
    assert [item.employee_id for item in run.items.all()] == [employee.pk]

    # The Owner signs off, and only the Owner does.
    client.logout()
    owner = staff_login(client, Role.Code.OWNER)
    approved = client.post(f"{RUNS_URL}{body['id']}/approve/")

    assert approved.status_code == 200, approved.content
    assert approved.json()["status"] == "APPROVED"

    run.refresh_from_db()
    assert run.approved_by == owner
    assert run.approved_at is not None
    # Every line is approved with the run, so no payslip is left half-signed.
    assert list(PayrollItem.objects.filter(run=run).values_list("status", flat=True)) == [
        "APPROVED"
    ]


def test_manager_cannot_approve_the_run_they_generated(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """The A8 gate: whoever computes the figure must not also sign it off."""

    staff_login(client, Role.Code.MANAGER)
    generated = _generate(client)
    run_id = generated.json()["id"]

    response = client.post(f"{RUNS_URL}{run_id}/approve/")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert PayrollRun.objects.get(pk=run_id).status == "GENERATED"


def test_cashier_cannot_read_payroll(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = client.get(RUNS_URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_anonymous_access_is_refused(client: Client) -> None:
    response = client.get(RUNS_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_a_month_cannot_be_payrolled_twice(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)

    first = _generate(client)
    second = _generate(client)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_state_transition"
    assert PayrollRun.all_rows.count() == 1


def test_a_run_with_no_eligible_employees_is_refused(client: Client, staff_login: Any) -> None:
    """An empty run cannot be approved, so it is refused at generation."""

    staff_login(client, Role.Code.MANAGER)

    response = _generate(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"
    assert not PayrollRun.all_rows.exists()


def test_a_deduction_keeps_its_reason_and_reduces_net_pay(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]
    item = PayrollItem.objects.get(run_id=run_id)

    response = client.post(
        DEDUCTIONS_URL,
        {
            "payroll_item": item.pk,
            "deduction_type": "ABSENCE",
            "amount": "450.00",
            "reason": "Two days absent in October without leave",
            "occurred_on": "2026-10-14",
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["reason"] == "Two days absent in October without leave"

    deduction = PayrollDeduction.objects.get(pk=response.json()["id"])
    assert deduction.reason == "Two days absent in October without leave"

    item.refresh_from_db()
    assert item.total_deductions == Decimal("450.00")
    assert item.net_amount == Decimal("17550.00")

    run = PayrollRun.objects.get(pk=run_id)
    assert run.deduction_total == Decimal("450.00")
    assert run.net_total == Decimal("17550.00")


def test_a_deduction_is_refused_once_the_run_is_approved(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """A signed payslip is not edited; the correction goes in the next run."""

    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]
    item = PayrollItem.objects.get(run_id=run_id)

    staff_login(client, Role.Code.OWNER)
    assert client.post(f"{RUNS_URL}{run_id}/approve/").status_code == 200

    response = client.post(
        DEDUCTIONS_URL,
        {"payroll_item": item.pk, "deduction_type": "OTHER", "amount": "100.00"},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state_transition"
    assert not PayrollDeduction.objects.exists()


def test_a_deduction_cannot_exceed_gross_pay(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """Previously a bare ValueError, which the global handler would surface as a 500."""

    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]
    item = PayrollItem.objects.get(run_id=run_id)

    response = client.post(
        DEDUCTIONS_URL,
        {"payroll_item": item.pk, "deduction_type": "OTHER", "amount": "20000.00"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "excessive_deduction"
    # Refused before anything was written, so the line is untouched.
    item.refresh_from_db()
    assert item.total_deductions == Decimal("0.00")
    assert not PayrollDeduction.objects.exists()


def test_a_zero_deduction_is_refused_as_a_domain_error(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]
    item = PayrollItem.objects.get(run_id=run_id)

    response = client.post(
        DEDUCTIONS_URL,
        {"payroll_item": item.pk, "deduction_type": "OTHER", "amount": "0.00"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_deduction_amount"


def test_approved_payroll_reduces_the_finance_balance(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """The link that makes payroll a cost rather than an isolated table."""

    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]

    before = client.get(BALANCE_URL, PERIOD)
    assert Decimal(before.json()["payroll_total"]) == Decimal("0.00")

    staff_login(client, Role.Code.OWNER)
    assert client.post(f"{RUNS_URL}{run_id}/approve/").status_code == 200

    after = client.get(BALANCE_URL, PERIOD)
    assert Decimal(after.json()["payroll_total"]) == Decimal("18000.00")
    assert Decimal(after.json()["net"]) == Decimal("-18000.00")


def test_a_run_can_only_be_marked_paid_once_approved(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.OWNER)
    run_id = _generate(client).json()["id"]

    too_early = client.post(f"{RUNS_URL}{run_id}/mark-paid/")
    assert too_early.status_code == 409
    assert too_early.json()["error"]["code"] == "invalid_state_transition"

    assert client.post(f"{RUNS_URL}{run_id}/approve/").status_code == 200
    paid = client.post(f"{RUNS_URL}{run_id}/mark-paid/")

    assert paid.status_code == 200, paid.content
    assert paid.json()["status"] == "PAID"

    run = PayrollRun.objects.get(pk=run_id)
    assert run.paid_at is not None
    assert set(PayrollItem.objects.filter(run=run).values_list("status", flat=True)) == {"PAID"}


def test_cashier_cannot_generate_a_run(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = _generate(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_manager_records_a_payroll_employee_from_a_profile(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.post(
        EMPLOYEES_URL,
        {"profile": profile.pk, "monthly_wage": "22000.00", "currency": "ETB"},
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["full_name"] == "Selam Bekele"
    assert body["monthly_wage"] == "22000.00"
    assert body["status"] == "ACTIVE"


def test_a_profile_can_only_have_one_payroll_employee(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.post(
        EMPLOYEES_URL,
        {"profile": employee.profile_id, "monthly_wage": "22000.00"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_generation_requires_a_business_period(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.post(RUNS_URL, {}, content_type="application/json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "period" in response.json()["error"]["details"]


def test_runs_are_listed_newest_first_and_paginated(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    assert _generate(client, period="2026-08-09").status_code == 201
    assert _generate(client, period="2026-09-09").status_code == 201

    response = client.get(RUNS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["page_size"] == 20
    assert [run["period_month"] for run in body["results"]] == ["2026-09-01", "2026-08-01"]


def test_a_runs_payslip_lines_are_paginated(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]

    response = client.get(f"{RUNS_URL}{run_id}/items/")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 1
    assert body["page_size"] == 20
    line = body["results"][0]
    assert line["full_name"] == "Selam Bekele"
    assert line["position"] == "Head Cashier"
    assert line["gross_amount"] == "18000.00"
    assert line["net_amount"] == "18000.00"
    assert line["status"] == "PENDING"


def test_cashier_cannot_read_payslip_lines(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    run_id = _generate(client).json()["id"]

    client.logout()
    staff_login(client, Role.Code.CASHIER)

    response = client.get(f"{RUNS_URL}{run_id}/items/")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_deductions_can_be_filtered_to_one_run(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    staff_login(client, Role.Code.MANAGER)
    first_run = _generate(client, period="2026-08-09").json()["id"]
    first_item = PayrollItem.objects.get(run_id=first_run)
    client.post(
        DEDUCTIONS_URL,
        {"payroll_item": first_item.pk, "deduction_type": "ADVANCE", "amount": "500.00"},
        content_type="application/json",
    )

    second_run = _generate(client, period="2026-09-09").json()["id"]
    second_item = PayrollItem.objects.get(run_id=second_run)

    response = client.get(DEDUCTIONS_URL, {"run": second_run})

    assert response.status_code == 200
    assert response.json()["count"] == 0

    response = client.get(DEDUCTIONS_URL, {"payroll_item": first_item.pk})
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["employee_name"] == "Selam Bekele"
    assert second_item.total_deductions == Decimal("0.00")


def test_the_roster_offers_only_staff_not_already_on_payroll(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """The list behind the create form: one entry per person still to be added."""

    available = EmployeeProfile.objects.create(
        full_name="Dawit Alemu", position="Barman", start_date="2026-03-02"
    )
    archived = EmployeeProfile.objects.create(
        full_name="Hana Girma", position="Waitress", start_date="2025-06-01", is_archived=True
    )
    staff_login(client, Role.Code.MANAGER)

    response = client.get(PROFILES_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 1
    assert body["page_size"] == 20
    assert body["results"][0]["id"] == available.pk
    # The two fields the create form cannot get from anywhere else.
    assert body["results"][0]["full_name"] == "Dawit Alemu"
    assert body["results"][0]["position"] == "Barman"
    assert body["results"][0]["phone_number"] == ""
    assert body["results"][0]["start_date"] == "2026-03-02"
    # The `employee` fixture put Selam on payroll and `archived` left; neither
    # belongs in a list whose only job is to be offered.
    assert employee.profile_id not in {row["id"] for row in body["results"]}
    assert archived.pk not in {row["id"] for row in body["results"]}


def test_the_roster_still_hides_a_voided_employee(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """The link is a OneToOne, so a voided row still occupies the profile.

    Offered anyway, the create would fail on a uniqueness the serializer cannot
    express as a field error — the form would show a refusal with nothing to fix.
    """

    employee.void(reason="Record corrected", actor=None)
    staff_login(client, Role.Code.MANAGER)

    response = client.get(PROFILES_URL)

    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_a_cashier_cannot_read_the_roster(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = client.get(PROFILES_URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_anonymous_access_to_the_roster_is_refused(client: Client) -> None:
    response = client.get(PROFILES_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_a_payroll_employee_reports_the_profile_details(
    client: Client, staff_login: Any, employee: Employee
) -> None:
    """Phone and start date are read from the profile, never copied into payroll."""

    staff_login(client, Role.Code.MANAGER)

    response = client.get(EMPLOYEES_URL)

    assert response.status_code == 200, response.content
    body = response.json()["results"][0]
    assert body["full_name"] == "Selam Bekele"
    assert body["position"] == "Head Cashier"
    assert body["phone_number"] == "+251911234567"
    assert body["start_date"] == "2026-01-05"
    assert body["monthly_wage"] == "18000.00"
