"""Payroll URL routing (spec §8.1).

Four resources, all with a non-empty prefix, so none of them can be swallowed by
another resource's detail wildcard. The ``runs`` router carries its lifecycle
actions (``approve``, ``mark-paid``, ``items``) as nested paths, which is why they
are not registered here. ``profiles`` is the roster read that fills the create
form's ``profile`` field; it has no detail route, so nothing can shadow it.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payroll.views import (
    PayrollDeductionViewSet,
    PayrollEmployeeViewSet,
    PayrollProfileViewSet,
    PayrollRunViewSet,
)

router = DefaultRouter()
router.register(r"employees", PayrollEmployeeViewSet, basename="payroll-employee")
router.register(r"runs", PayrollRunViewSet, basename="payroll-run")
router.register(r"deductions", PayrollDeductionViewSet, basename="payroll-deduction")
router.register(r"profiles", PayrollProfileViewSet, basename="payroll-profile")

app_name = "payroll"

urlpatterns = [
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
