import pytest
from decimal import Decimal
from datetime import date

from apps.finance.models import AdditionalIncome
from apps.finance.serializers import AdditionalIncomeCreateSerializer, AdditionalIncomeUpdateSerializer


@pytest.mark.django_db
class TestAdditionalIncomeValidation:
    def test_missing_source_rejected(self):
        s = AdditionalIncomeCreateSerializer(data={"source":"  ","amount":"10","income_date":"2026-01-01","note":"x","currency":"ETB"})
        assert not s.is_valid()
        assert "source" in s.errors

    def test_missing_note_rejected(self):
        s = AdditionalIncomeCreateSerializer(data={"source":"Broken","amount":"10","income_date":"2026-01-01","note":"  ","currency":"ETB"})
        assert not s.is_valid()

    def test_zero_amount_rejected(self):
        s = AdditionalIncomeCreateSerializer(data={"source":"Broken","amount":"0","income_date":"2026-01-01","note":"x","currency":"ETB"})
        assert not s.is_valid()

    def test_negative_amount_rejected(self):
        s = AdditionalIncomeCreateSerializer(data={"source":"Broken","amount":"-5","income_date":"2026-01-01","note":"x","currency":"ETB"})
        assert not s.is_valid()

    def test_valid_saved(self):
        s = AdditionalIncomeCreateSerializer(data={"source":"Glass","amount":"15.50","income_date":"2026-01-01","note":"Customer breakage","currency":"ETB","payment_method":"CASH"})
        assert s.is_valid()


@pytest.mark.django_db
class TestAdditionalIncomeFinancial:
    def test_total_calculated(self):
        AdditionalIncome.objects.create(source="A", amount=Decimal("10"), currency="ETB", income_date=date(2026,1,1), note="n", payment_method="CASH")
        from apps.finance.services import additional_income_total
        assert additional_income_total(start=date(2026,1,1), end=date(2026,1,1)) == Decimal("10.00")
