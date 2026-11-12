"""Bono API URLs."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.bono.views import (
    BonoDaySummaryView,
    BonoIncidentViewSet,
    BonoIssueViewSet,
    BonoPairingViewSet,
    BonoReportViewSet,
    BonoTransferViewSet,
    BonoTypeViewSet,
)

router = DefaultRouter()
router.register(r"types", BonoTypeViewSet, basename="bono-type")
router.register(r"pairings", BonoPairingViewSet, basename="bono-pairing")
router.register(r"issues", BonoIssueViewSet, basename="bono-issue")
router.register(r"transfers", BonoTransferViewSet, basename="bono-transfer")
router.register(r"incidents", BonoIncidentViewSet, basename="bono-incident")
router.register(r"reports", BonoReportViewSet, basename="bono-report")

app_name = "bono"
urlpatterns = [
    path("summary/", BonoDaySummaryView.as_view(), name="summary"),
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
