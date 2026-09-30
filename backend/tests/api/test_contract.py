"""Parameterised contract tests applied to every registered endpoint (A3).

Two halves, and the second is the one that matters:

* ``test_every_endpoint_satisfies_every_rule`` runs the rules over the live
  URLconf. This is the gate that fails when a non-compliant endpoint is added.
* ``test_each_rule_rejects_a_deliberately_non_compliant_endpoint`` feeds each
  rule a view built to break exactly that rule. Without it, a rule that always
  returned None would pass every endpoint and be indistinguishable from a
  working suite.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import BrowsableAPIRenderer, JSONRenderer
from rest_framework.views import APIView

from apps.core.authentication import BarkotSessionAuthentication
from apps.core.pagination import BarkotPagination
from tests.api.contract import (
    EXEMPTIONS,
    RULES,
    Endpoint,
    check,
    describe,
    discover_endpoints,
    ignoring_exemptions,
    violations_for,
)

ENDPOINTS = discover_endpoints()


def _ids() -> list[str]:
    return [f"{e.method}-{e.path}" for e in ENDPOINTS]


class TestRealEndpoints:
    """The gate. Every registered endpoint against every rule."""

    def test_the_urlconf_exposes_at_least_one_endpoint(self) -> None:
        """Guard the parameterisation below against silently testing nothing.

        A discovery bug that returned an empty list would make every other
        test in this class pass vacuously, and the suite would report green
        while checking nothing.
        """
        assert ENDPOINTS, "no DRF endpoints were discovered; the contract suite would be inert"

    @pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids())
    @pytest.mark.parametrize("rule_name", list(RULES))
    def test_every_endpoint_satisfies_every_rule(self, endpoint: Endpoint, rule_name: str) -> None:
        """No registered endpoint may break any rule.

        Args:
            endpoint: One HTTP method on one view, from the live URLconf.
            rule_name: The rule under test.

        Raises:
            AssertionError: If the endpoint violates the rule.
        """
        problem = check(endpoint, RULES[rule_name])
        assert problem is None, f"{endpoint.label} breaks [{rule_name}]: {problem}"

    def test_the_whole_suite_is_clean_in_one_shot(self) -> None:
        """Report every violation at once, not just the first.

        A developer who adds one endpoint that breaks three rules should learn
        all three from one run rather than fixing them one per invocation.
        """
        found = violations_for(ENDPOINTS)
        assert not found, f"contract violations:\n{describe(found)}"


class TestRulesHaveTeeth:
    """Each rule must reject the endpoint it exists to reject."""

    @pytest.mark.parametrize("rule_name", list(RULES))
    def test_each_rule_rejects_a_deliberately_non_compliant_endpoint(self, rule_name: str) -> None:
        """A rule that cannot fail is not a rule.

        Args:
            rule_name: The rule under test.

        Raises:
            AssertionError: If the rule accepts a view built to break it.
        """
        bad = _non_compliant_endpoint(rule_name)
        assert bad is not None, f"no deliberately non-compliant view defined for {rule_name}"

        # Suppress exemptions so the rule under test is the only thing deciding
        # the verdict. Otherwise a view keyed like an exempt one would pass for
        # the wrong reason.
        with ignoring_exemptions():
            problem = check(bad, RULES[rule_name])

        assert problem is not None, (
            f"[{rule_name}] accepted a deliberately non-compliant endpoint "
            f"{bad.label}: {_describe_view(bad.view)}"
        )

    def test_discovery_rejects_a_non_drf_view(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovery must raise on a view it cannot read permissions from.

        DRF's ``as_view()`` attaches the class as ``.cls``. A plain Django
        function view has no such attribute. The tempting one-liner,
        ``getattr(view, "cls", view)``, would return the function itself - an
        object with no ``permission_classes`` - so every rule would report
        "declares no permission class" instead of the real problem, and any
        rule reading a different attribute would pass it silently.

        Raises:
            TypeError: If discovery accepts a view it cannot contract.
        """
        import tests.api.contract as contract_module

        def plain_django_view(request: object) -> str:  # pragma: no cover - never called
            return ""

        class FakeEnumerator:
            """Yields one non-DRF callback, as a mis-registered view would."""

            def get_api_endpoints(self) -> Iterator[tuple[str, str, object]]:
                return iter([("/api/v1/plain/", "GET", plain_django_view)])

        # monkeypatch.setattr rather than assignment: mypy rejects rebinding a
        # module-level name to an unrelated type, and pytest undoes it even if
        # the assertion raises.
        monkeypatch.setattr(contract_module, "EndpointEnumerator", FakeEnumerator)
        with pytest.raises(TypeError, match="not a DRF APIView"):
            contract_module.discover_endpoints()

    def test_every_rule_has_a_non_compliant_fixture(self) -> None:
        """No rule may ship without a case that proves it can fail.

        This is what stops a future rule from being added and quietly passing.
        """
        missing = [name for name in RULES if _non_compliant_endpoint(name) is None]
        assert not missing, f"rules with no non-compliant fixture: {missing}"


def _describe_view(view: type[APIView]) -> str:
    """Render the DRF attributes a rule reads, for failure messages.

    A rule that starts failing should say what the view actually declared. This
    uses ``getattr`` with defaults because ``paginator`` only exists on
    ``GenericAPIView``; reading it off a bare ``APIView`` would raise before the
    assertion could report anything.

    Args:
        view: The view class to describe.

    Returns:
        A one-line summary of its contract-relevant attributes.
    """

    def names(attribute: str) -> str:
        value = getattr(view, attribute, None) or []
        return ", ".join(getattr(item, "__name__", repr(item)) for item in value)

    paginator = getattr(view, "paginator", None)
    return (
        f"{view.__name__} permission_classes=[{names('permission_classes')}] "
        f"authentication_classes=[{names('authentication_classes')}] "
        f"renderer_classes=[{names('renderer_classes')}] "
        f"paginator={getattr(paginator, '__name__', None)}"
    )


def _non_compliant_endpoint(rule_name: str) -> Endpoint | None:
    """Build a view that breaks exactly one rule.

    Kept next to the tests rather than in the engine so the engine has no
    knowledge of what it is supposed to catch.

    Args:
        rule_name: The rule to violate.

    Returns:
        An endpoint that breaks it, or None if the rule name is unknown.
    """

    class PublicByAccident(APIView):
        """Private-by-default violated: someone typed AllowAny for debugging."""

        permission_classes = [AllowAny]

    class NoAuthentication(APIView):
        """Session-auth violated: credentials are never checked."""

        permission_classes = [IsAuthenticated]
        authentication_classes: list[type] = []

    class BrowsableApi(APIView):
        """Browsable API violated: HTML renders every field."""

        permission_classes = [IsAuthenticated]
        renderer_classes = [JSONRenderer, BrowsableAPIRenderer]

    class ForeignPaginator(APIView):
        """Paginator violated: DRF's own, which omits the resolved page_size."""

        permission_classes = [IsAuthenticated]
        paginator = None

        def get(self, request: object) -> object:  # pragma: no cover - never dispatched
            return None

    class Unversioned(APIView):
        """Versioning violated: mounted outside /api/v1/."""

        permission_classes = [IsAuthenticated]

    fixtures = {
        "private_by_default": ("/api/v1/leaky/", PublicByAccident),
        "session_auth_only": ("/api/v1/anonymous/", NoAuthentication),
        "no_browsable_api": ("/api/v1/pretty/", BrowsableApi),
        "versioned_path": ("/widgets/", Unversioned),
    }
    if rule_name in fixtures:
        path, view = fixtures[rule_name]
        return Endpoint(path=path, method="GET", view=view)
    if rule_name == "project_paginator":
        # A subclass of DRF's PageNumberPagination, not ours.
        from rest_framework.pagination import PageNumberPagination

        class WrongPaginator(PageNumberPagination):
            """Close enough to look right, wrong exactly where it counts."""

        class UsesWrongPaginator(APIView):
            permission_classes = [IsAuthenticated]
            paginator = WrongPaginator

        return Endpoint(path="/api/v1/lists/", method="GET", view=UsesWrongPaginator)
    return None


class TestExemptionsAreHonest:
    """An exemption is a claim. These check the claim is still true."""

    def test_each_exemption_names_only_real_rules(self) -> None:
        """A waiver for a deleted rule would hide a real failure.

        Raises:
            AssertionError: If any exemption waives an unknown rule.
        """
        unknown = {
            ex.view_key: sorted(ex.waives - set(RULES))
            for ex in EXEMPTIONS
            if ex.waives - set(RULES)
        }
        assert not unknown, f"exemptions waive rules that do not exist: {unknown}"

    def test_each_exemption_matches_a_real_endpoint(self) -> None:
        """An exemption for a deleted view is dead weight that hides intent.

        Raises:
            AssertionError: If no discovered endpoint carries the exempted key.
        """
        keys = {e.key for e in ENDPOINTS}
        orphaned = [ex.view_key for ex in EXEMPTIONS if ex.view_key not in keys]
        assert not orphaned, f"exemptions for endpoints that no longer exist: {orphaned}"

    def test_each_exemption_waives_exactly_what_it_needs(self) -> None:
        """An exemption may not cover a rule the endpoint would have passed.

        Without this the exemptions widen until the suite enforces nothing:
        waiving ``versioned_path`` on the API root would also waive a future
        rule that root has no business breaking.

        Raises:
            AssertionError: If any exemption waives an unnecessary rule.
        """
        over_waived: dict[str, dict[str, str]] = {}
        for exemption in EXEMPTIONS:
            endpoint = next((e for e in ENDPOINTS if e.key == exemption.view_key), None)
            if endpoint is None:
                continue
            unnecessary = {}
            for rule_name in sorted(exemption.waives):
                # With exemptions suppressed, `check` returns the rule's own
                # verdict. Leaving them on would make every waived rule look
                # satisfied and this test would fail on all three exemptions
                # for the same false reason.
                with ignoring_exemptions():
                    passes_unassisted = check(endpoint, RULES[rule_name]) is None
                if passes_unassisted:
                    unnecessary[rule_name] = "the endpoint passes this rule unaided"
            if unnecessary:
                over_waived[exemption.view_key] = unnecessary
        assert not over_waived, (
            "exemptions waive rules their endpoint satisfies anyway:\n"
            + "\n".join(f"  {k}: {sorted(v)}" for k, v in over_waived.items())
        )

    def test_each_exemption_states_a_reason(self) -> None:
        """An unexplained exemption is indistinguishable from a bug."""
        for exemption in EXEMPTIONS:
            assert exemption.reason.strip(), f"{exemption.view_key} has no stated reason"


class TestEngineInternals:
    """Small units the larger tests lean on."""

    def test_the_api_root_is_public_and_the_suite_accepts_it(self) -> None:
        """The one deliberate public endpoint is genuinely public.

        If this stops being true the docstring in ``api_root.py`` is a lie, and
        the exemption would be hiding a behaviour change rather than a
        documented exception.
        """
        root = next(e for e in ENDPOINTS if e.view.__name__ == "ApiRootView")
        assert AllowAny in root.view.permission_classes
        assert check(root, RULES["private_by_default"]) is None
        assert check(root, RULES["session_auth_only"]) is None

    def test_health_endpoints_are_not_part_of_the_api_contract(self) -> None:
        """Health probes stay out of the DRF surface.

        They are consumed by Docker and Nginx and are not part of the business
        contract; documenting them would invite the frontend to depend on them.
        """
        paths = {e.path for e in ENDPOINTS}
        assert not any(p.startswith("/health") for p in paths), paths

    def test_violations_for_returns_empty_for_a_compliant_endpoint(self) -> None:
        """A clean endpoint produces no findings under any rule."""

        class Compliant(APIView):
            permission_classes = [IsAuthenticated]
            authentication_classes = [BarkotSessionAuthentication]
            renderer_classes = [JSONRenderer]
            paginator = BarkotPagination

        endpoint = Endpoint(path="/api/v1/fine/", method="GET", view=Compliant)
        assert violations_for([endpoint]) == {}

    def test_endpoint_key_disambiguates_same_named_views(self) -> None:
        """Two views sharing a ``__name__`` must not share a key.

        Two domains may each add a ``ListView``. If the key were ``__name__``,
        an exemption written for one would silently cover the other, and the
        leak would not surface until a permission was actually wrong.
        """
        one = type("ListView", (APIView,), {"__module__": "apps.sales.views"})
        two = type("ListView", (APIView,), {"__module__": "apps.products.views"})
        first = Endpoint(path="/api/v1/sales/", method="GET", view=one)
        second = Endpoint(path="/api/v1/products/", method="GET", view=two)
        assert first.view.__name__ == second.view.__name__ == "ListView"
        assert first.key != second.key
        assert first.label != second.label

    def test_discovery_is_not_vacuous_when_the_urlconf_has_no_api(self) -> None:
        """An empty discovery must not masquerade as a clean bill of health.

        The parameterised tests iterate over what discovery returned. If that
        were empty for any reason, they would report success having checked
        nothing - which is the failure mode most dangerous in a gate.
        """
        assert ENDPOINTS, "discovery returned nothing; the parameterised tests are inert"
        assert len(ENDPOINTS) >= 1
        # Every discovered endpoint must actually be inspectable, or the rules
        # below are reading defaults off a closure.
        for endpoint in ENDPOINTS:
            assert issubclass(endpoint.view, APIView), endpoint.label
            assert endpoint.view.permission_classes is not None, endpoint.label
