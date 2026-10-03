"""The contract suite's rule engine (roadmap A3).

Every endpoint under ``/api/`` is discovered from the live URLconf and run
through every rule here. Adding an endpoint therefore subjects it to the same
checks as the existing ones with no edit to this file, which is the entire
point: without it, each domain in Phase C would independently decide what
"pagination looks like" and the seventh would differ from the first.

Two design choices are load-bearing.

**Rules assert on class attributes, not on responses.** A rule that issued a
request would need fixtures, a database row and a guess at what a successful
call returns for a resource that does not exist yet. Asserting on the class
keeps the suite free of setup, so it runs in milliseconds and cannot rot into a
test that passes because a mock returned the wrong shape.

**An exemption is declared, not inferred.** ``AllowAny`` on the API root is
correct and deliberate, so a blanket "no public endpoints" rule would be wrong.
Each exemption names the rules it waives, and
:func:`test_each_exemption_waives_exactly_what_it_needs` fails if a waiver
covers a rule the view would have passed anyway. Without that check the
exemptions would quietly widen until the suite enforced nothing.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass

from rest_framework.permissions import AllowAny
from rest_framework.renderers import BrowsableAPIRenderer
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.views import APIView

from apps.core.authentication import BarkotSessionAuthentication
from apps.core.pagination import BarkotPagination

#: The only path prefix a versioned business endpoint may live under. The
#: version is in the path precisely so this is checkable by string comparison.
VERSION_PREFIX = "/api/v1/"


@dataclass(frozen=True)
class Endpoint:
    """One HTTP method on one view, as found in the URLconf.

    Attributes:
        path: The URL as Django resolves it, e.g. ``/api/v1/orders/``.
        method: Upper-case HTTP method, e.g. ``"GET"``.
        view: The view *class*. DRF's ``as_view()`` hands back a closure, so
            this is ``getattr(view, "cls", view)``; the closure has no
            ``permission_classes`` of its own and asserting on it would pass
            everything.

            Typed as ``type[APIView]`` rather than bare ``type`` because every
            rule reads attributes DRF declares on ``APIView``. Under bare
            ``type`` mypy rejects those reads, which pushes the natural fix -
            wrapping them in ``getattr(..., default)`` - into the code and hides
            genuine typos in the attribute names the rules depend on.
    """

    path: str
    method: str
    view: type[APIView]

    @property
    def key(self) -> str:
        """A stable identifier for the view class.

        Dotted path rather than ``__name__`` because two domains may both have
        a ``ListView``, and an exemption that matched the wrong one would be
        invisible until a permission leaked.
        """
        return f"{self.view.__module__}.{self.view.__qualname__}"

    @property
    def label(self) -> str:
        """Human-readable identity, used in assertion messages."""
        return f"{self.method} {self.path} [{self.view.__name__}]"


@dataclass(frozen=True)
class Exemption:
    """A declared exception to one or more rules.

    Attributes:
        view_key: The :attr:`Endpoint.key` this applies to.
        waives: Names of the rules it exempts the view from.
        reason: Why. Required, not optional: an unexplained exemption is
            indistinguishable from a bug and gets waved through review.
    """

    view_key: str
    waives: frozenset[str]
    reason: str


#: Endpoints that are deliberately unlike a business endpoint. Each is public or
#: unversioned for a reason recorded in its ``reason``.
EXEMPTIONS: tuple[Exemption, ...] = (
    Exemption(
        view_key="config.api_root.ApiRootView",
        waives=frozenset({"private_by_default", "session_auth_only"}),
        reason=(
            "Answers 'am I talking to the API I think I am?'. Returns a service "
            "name and a version string that are already in the JavaScript bundle "
            "and the access log, and requiring a session would turn an expired "
            "session into a login redirect with no explanation (spec §9.2)."
        ),
    ),
    Exemption(
        view_key="apps.accounts.views.CsrfView",
        waives=frozenset({"private_by_default"}),
        reason=(
            "Hands out the CSRF token the browser client needs before its first "
            "unsafe request, including before it holds any session. It returns a "
            "salted hash of the CSRF secret with no user attached, so it discloses "
            "nothing about any account, and it is unreachable while signed out "
            "otherwise - which would make login impossible (spec 9.1, ADR-0003 D8)."
        ),
    ),
    Exemption(
        view_key="apps.accounts.views.LoginView",
        waives=frozenset({"private_by_default"}),
        reason=(
            "Signing in is how a client obtains a session, so it cannot require "
            "one; the requirement would be circular. It authenticates a username "
            "and password and returns nothing that is not already known to whoever "
            "holds those credentials. CSRF is enforced explicitly on it rather "
            "than by DRF, which skips the check for an unauthenticated request "
            "(spec 9.1, P09)."
        ),
    ),
    Exemption(
        view_key="drf_spectacular.views.SpectacularAPIView",
        waives=frozenset({"versioned_path"}),
        reason=(
            "The schema describes the API rather than being part of it. Mounted "
            "beside the version at /api/schema/ so a v1 client can read it "
            "without naming a version, and so both versions can exist during a "
            "migration."
        ),
    ),
    Exemption(
        view_key="drf_spectacular.views.SpectacularSwaggerView",
        waives=frozenset({"versioned_path"}),
        reason="Serves HTML for a human reading the schema. Same reasoning as the schema itself.",
    ),
)


def discover_endpoints() -> list[Endpoint]:
    """Enumerate every DRF endpoint reachable from the root URLconf.

    Reads the real URLconf rather than a maintained list, so an endpoint
    someone forgets to register a contract test for still gets checked.

    Returns:
        Endpoints sorted by path then method, for stable test IDs.
    """
    found: list[Endpoint] = []
    for path, method, view in EndpointEnumerator().get_api_endpoints():
        # `as_view()` returns a closure with no DRF attributes of its own; the
        # class it wraps is on `.cls`. Cast rather than getattr-default because
        # a view missing `.cls` should be a loud failure here, not a silently
        # uncontracted endpoint that passes every rule by having no attributes.
        view_class = getattr(view, "cls", None)
        if view_class is None or not issubclass(view_class, APIView):
            raise TypeError(
                f"{method} {path} resolved to {view!r}, which is not a DRF APIView; "
                "the contract suite cannot read its permissions"
            )
        found.append(Endpoint(path=path, method=method, view=view_class))
    return sorted(found, key=lambda e: (e.path, e.method))


#: Set by :func:`ignoring_exemptions`. Empty means "consult EXEMPTIONS".
#: Indirection rather than a direct read so the override is explicit at every
#: call site instead of relying on who reassigned what.
_ACTIVE_EXEMPTIONS: tuple[Exemption, ...] | None = None


@contextlib.contextmanager
def ignoring_exemptions() -> Iterator[None]:
    """Evaluate rules as though no endpoint were exempt.

    Two tests need this and neither can get the answer any other way: one proves
    each rule can fail, the other proves each exemption is necessary. Both must
    see the rule's own verdict rather than the exemption that would otherwise
    short-circuit it.

    Yields:
        None, with the exemption table suppressed for the duration.
    """
    global _ACTIVE_EXEMPTIONS
    previous = _ACTIVE_EXEMPTIONS
    _ACTIVE_EXEMPTIONS = ()
    try:
        yield
    finally:
        _ACTIVE_EXEMPTIONS = previous


def active_exemptions() -> tuple[Exemption, ...]:
    """The exemption table currently in force.

    Returns:
        The table :func:`ignoring_exemptions` suppressed, or :data:`EXEMPTIONS`.
    """
    return EXEMPTIONS if _ACTIVE_EXEMPTIONS is None else _ACTIVE_EXEMPTIONS


def _waived(endpoint: Endpoint, rule: str) -> bool:
    return any(e.view_key == endpoint.key and rule in e.waives for e in active_exemptions())


def private_by_default(endpoint: Endpoint) -> str | None:
    """No endpoint is public unless it says so through a declared exemption.

    The global default is ``IsAuthenticated``, so the failure this catches is a
    view that overrode it. ``AllowAny`` on a business endpoint is a data leak
    that no other test in the suite would notice, because the endpoint returns
    exactly what it is supposed to return.

    Args:
        endpoint: The endpoint under test.

    Returns:
        A description of the violation, or None when compliant or exempted.
    """
    if _waived(endpoint, "private_by_default"):
        return None
    permissions = list(getattr(endpoint.view, "permission_classes", []) or [])
    if not permissions:
        return (
            "declares no permission class; the global default is only consulted "
            "when the attribute is absent, so this endpoint is unreachable or "
            "unrestricted depending on the DRF version"
        )
    if any(issubclass(perm, AllowAny) for perm in permissions):
        names = ", ".join(p.__name__ for p in permissions)
        return f"is public ({names}); a business endpoint must declare IsAuthenticated or tighter"
    return None


def session_auth_only(endpoint: Endpoint) -> str | None:
    """Every endpoint authenticates with the project's session class.

    A second scheme would mean a second answer to "who is this", and the 401
    that the frontend relies on to trigger a re-login would only apply to one
    of them.

    Args:
        endpoint: The endpoint under test.

    Returns:
        A description of the violation, or None when compliant or exempted.
    """
    if _waived(endpoint, "session_auth_only"):
        return None
    authentication = list(getattr(endpoint.view, "authentication_classes", []) or [])
    if not authentication:
        return "declares no authentication class, so no credential is ever checked"
    unexpected = [
        a.__name__ for a in authentication if not issubclass(a, BarkotSessionAuthentication)
    ]
    if unexpected:
        allowed = ", ".join(a.__name__ for a in authentication)
        return (
            f"authenticates with {allowed}; only {BarkotSessionAuthentication.__name__} may be used"
        )
    return None


def no_browsable_api(endpoint: Endpoint) -> str | None:
    """No endpoint serves DRF's HTML browsable interface.

    It renders every field of every object to anyone who loads the URL, which
    is a disclosure risk and an accident waiting to happen during debugging.

    Args:
        endpoint: The endpoint under test.

    Returns:
        A description of the violation, or None when compliant or exempted.
    """
    renderers = list(getattr(endpoint.view, "renderer_classes", []) or [])
    if any(issubclass(r, BrowsableAPIRenderer) for r in renderers):
        names = ", ".join(r.__name__ for r in renderers)
        return f"renders with {names}, which exposes the browsable HTML interface"
    return None


def project_paginator(endpoint: Endpoint) -> str | None:
    """A paginator, if declared, is the project's one.

    DRF's ``PageNumberPagination`` is close enough to look correct and differs
    exactly where the contract matters: it omits the resolved ``page_size`` and
    rejects out-of-range pages inconsistently.

    Args:
        endpoint: The endpoint under test.

    Returns:
        A description of the violation, or None when compliant or exempted.
    """
    if _waived(endpoint, "project_paginator"):
        return None
    paginator = getattr(endpoint.view, "paginator", None)
    if paginator is None:
        return None
    # Handle both class (pagination_class) and instance (paginator) patterns
    paginator_class = paginator if isinstance(paginator, type) else type(paginator)
    if not issubclass(paginator_class, BarkotPagination):
        return (
            f"paginates with {paginator_class.__name__}; use {BarkotPagination.__name__} so the "
            "response envelope matches every other list endpoint"
        )
    return None


def versioned_path(endpoint: Endpoint) -> str | None:
    """Business endpoints live under the version prefix.

    An unversioned business endpoint is reachable forever, which is the thing
    versioning exists to prevent.

    Args:
        endpoint: The endpoint under test.

    Returns:
        A description of the violation, or None when compliant or exempted.
    """
    if _waived(endpoint, "versioned_path"):
        return None
    if not endpoint.path.startswith(VERSION_PREFIX):
        return f"is mounted at {endpoint.path}, outside the version prefix {VERSION_PREFIX}"
    return None


#: Rule name to rule. Order is the order failures are reported in: cheapest and
#: most alarming first.
Rule = Callable[[Endpoint], "str | None"]
RULES: dict[str, Rule] = {
    "private_by_default": private_by_default,
    "session_auth_only": session_auth_only,
    "no_browsable_api": no_browsable_api,
    "project_paginator": project_paginator,
    "versioned_path": versioned_path,
}


def check(endpoint: Endpoint, rule: Rule) -> str | None:
    """Run one rule against one endpoint, isolating rule bugs.

    A rule that raises would otherwise abort the whole parameterised suite and
    hide every other endpoint's result, so failures are converted into a
    violation string that names the rule.

    Args:
        endpoint: The endpoint under test.
        rule: The rule to apply.

    Returns:
        The violation description, or None when the endpoint passes.
    """
    try:
        return rule(endpoint)
    except Exception as exc:  # pragma: no cover - guards against rule bugs
        return f"the rule itself failed: {type(exc).__name__}: {exc}"


def violations_for(endpoints: Iterable[Endpoint]) -> dict[str, dict[str, str]]:
    """Run every rule against every endpoint and collect the failures.

    Args:
        endpoints: Endpoints to check.

    Returns:
        Rule name to endpoint label to violation. Empty when all pass.
    """
    found: dict[str, dict[str, str]] = {}
    for name, rule in RULES.items():
        for endpoint in endpoints:
            problem = check(endpoint, rule)
            if problem is not None:
                found.setdefault(name, {})[endpoint.label] = problem
    return found


def describe(found: dict[str, dict[str, str]]) -> str:
    """Render a violation mapping for a pytest assertion message.

    Args:
        found: The output of :func:`violations_for`.

    Returns:
        A multi-line human-readable report.
    """
    if not found:
        return "no violations"
    lines = []
    for name in RULES:
        for label, problem in found.get(name, {}).items():
            lines.append(f"[{name}] {label} {problem}")
    return "\n".join(lines)


def rule_names() -> Sequence[str]:
    """The rule names, for tests that must stay in step with :data:`RULES`."""
    return tuple(RULES)
