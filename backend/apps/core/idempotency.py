"""Idempotency for financial and stock-creating writes (spec §10.2, P11).

§10.2 asks that "financial and stock-creating endpoints accept an Idempotency-Key or
enforce an equivalent client-generated unique reference", because a weak network or an
accidental double-click must not create duplicate sales or duplicate stock receipts.
The risk table rates that "High".

**The mechanism is a claim row, not a lock.** A request presents a key; the service
tries to insert a row claiming ``(scope, key)`` and refuses if one already exists. The
unique constraint is what makes it correct, so two workers racing the same key produce
exactly one winner regardless of process, and the loser is a unique-violation rather
than a second sale. A ``SELECT``-then-``INSERT`` check would leave exactly the window
this exists to close.

**Stored, not cached.** A duplicate sale is unrecoverable in the way a duplicate cache
entry is not, so the claim lives in the database next to the records it protects. The
cache is used for throttling (:mod:`apps.core.throttling`) precisely because a lost
counter costs one login attempt; losing an idempotency claim would cost a sale.

**A key is a claim about content, not just a de-duplication token.** Replaying a key
whose body differs is refused with :class:`~apps.core.exceptions.IdempotencyKeyReuse`
rather than served the first result, because the caller would believe a different
request had been applied. A concurrent request with an identical body is a different
situation and gets :class:`~apps.core.exceptions.IdempotencyInFlight`, which asks it
to retry the same key.

**The fingerprint is over the normalised body.** Callers reorder JSON keys or send
``1`` where they sent ``1.0`` on the retry; those are the same request and must hash
the same. :func:`fingerprint` normalises before hashing, so a faithful retry replays
and only a genuinely different body is refused.

**Not an HTTP concern.** This is deliberately a service-level facility: the key is
carried as a keyword argument rather than read from a header, so the same guarantee
applies to a management command, a scheduled job or a test that never touches HTTP. The
endpoint that eventually reads ``Idempotency-Key`` is a thin adapter over this, and no
business endpoint exists yet (roadmap A10 is Phase A's last task, before any route).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, models, transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.core.exceptions import IdempotencyInFlight, IdempotencyKeyReuse
from apps.core.models import TimeStampedModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.db.models import Model

#: Header name an endpoint adapter will read, and the keyword an in-process caller
#: passes. Named once so the two cannot drift apart.
IDEMPOTENCY_HEADER = "Idempotency-Key"

#: Longest key accepted. Generous enough for a UUID, a ULID or a client-chosen
#: token, short enough that the column is not a place to store a payload.
MAX_KEY_LENGTH = 255

#: Scope for :func:`apps.sales.services.complete_sale`. Scoped rather than global so
#: the same key value on two different operations cannot collide.
SALE_SCOPE = "sales.complete_sale"


def canonical(value: Any) -> Any:
    """Return a stable, JSON-serialisable form of a request body.

    Two retries of one request must hash identically even when the client serialised
    them differently. The differences that matter are key order, ``1`` versus ``1.0``,
    and a set that arrived in a different iteration order; each is normalised here
    rather than left to the client to be careful about.

    ``Decimal`` and ``date``/``datetime`` become tagged strings rather than floats.
    Converting money to a float before hashing would be the exact class of bug §10.3
    exists to prevent, and two amounts differing below float precision would then
    compare equal.

    Args:
        value: Any part of a request body.

    Returns:
        A value ``json.dumps`` can render deterministically.

    Raises:
        TypeError: If the body contains something with no defined canonical form,
            such as a database connection. Failing here is better than hashing
            ``repr()`` and treating two different objects as one request.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float, Decimal)):
        # One tag for all three, so a client that sent ``1`` the first time and
        # ``1.0`` the second is recognised as retrying rather than reusing the key
        # for a different request. The text is then read back as a ``Decimal``, so
        # the value enters the digest exactly and no binary float is ever involved
        # (§10.3). ``bool`` is checked above because it is an ``int`` subclass, and
        # ``True`` must not hash as ``1``.
        #
        # ``str`` rather than ``repr`` for an int or a Decimal, because a Decimal's
        # repr is ``Decimal('2')`` and not a number any parser will read. For a float
        # it is ``repr``, which is the shortest text that round-trips to the same
        # float - so a binary artefact such as ``0.1 + 0.2`` stays visible instead of
        # being quietly normalised onto the value a human probably meant.
        text = repr(value) if isinstance(value, float) else str(value)
        return {"__number__": str(Decimal(text).normalize())}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted(repr(canonical(v)) for v in value)}
    raise TypeError(f"Cannot build a canonical form of {type(value).__name__}.")


def fingerprint(body: Any) -> str:
    """Return a stable digest of a request body.

    Args:
        body: The request payload.

    Returns:
        A hex SHA-256 digest, used to decide whether a repeated key describes the
        same request.
    """
    encoded = json.dumps(canonical(body), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class IdempotencyRecord(TimeStampedModel):
    """One claim that a ``(scope, key)`` pair has been handled.

    Rows are never updated after the claim is made and never deleted: the record is
    the evidence that a retry was answered from the first attempt rather than
    re-executed. ``object_type``/``object_id`` name what the first attempt produced, so
    a replay can hand back the same identifier without running anything.
    """

    scope = models.CharField(
        _("scope"),
        max_length=100,
        help_text=_("The operation the key applies to, e.g. 'sales.complete_sale'."),
    )
    key = models.CharField(_("key"), max_length=MAX_KEY_LENGTH)
    request_fingerprint = models.CharField(_("request fingerprint"), max_length=64)
    object_type = models.CharField(
        _("object type"),
        max_length=100,
        blank=True,
        help_text=_(
            "Module path and class name of what the first attempt created, e.g. "
            "'apps.sales.models.Sale'. This is the model's Python path rather than "
            "Django's app_label.ModelName form, because a caller knows which class it "
            "was guarding and :func:`replayed_object` checks the two agree."
        ),
    )
    object_id = models.CharField(_("object id"), max_length=64, blank=True)

    class Meta:
        verbose_name = _("idempotency record")
        verbose_name_plural = _("idempotency records")
        ordering = ["-created_at", "-id"]
        default_permissions = ("add", "view")
        constraints = [
            # The whole mechanism. Without it two workers can both believe they own
            # the key, which is the duplicate sale this table exists to prevent.
            models.UniqueConstraint(fields=["scope", "key"], name="uniq_idempotency_scope_key"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}"


def validate_key(key: str) -> str:
    """Return the key stripped, or refuse it.

    A blank key is refused rather than treated as absent: a client that sends an empty
    ``Idempotency-Key`` believes it is protected, and silently proceeding without a
    claim is the one outcome worse than an error.

    Args:
        key: The client-supplied key.

    Returns:
        The trimmed key.

    Raises:
        ValueError: If the key is empty or longer than :data:`MAX_KEY_LENGTH`.
    """
    stripped = key.strip()
    if not stripped:
        raise ValueError("An idempotency key cannot be blank.")
    if len(stripped) > MAX_KEY_LENGTH:
        raise ValueError(
            ngettext(
                "An idempotency key may be at most %(limit)d character.",
                "An idempotency key may be at most %(limit)d characters.",
                MAX_KEY_LENGTH,
            )
            % {"limit": MAX_KEY_LENGTH}
        )
    return stripped


@dataclass(frozen=True, slots=True)
class Claim:
    """The outcome of asking for a ``(scope, key)`` pair.

    Attributes:
        replayed: Whether the work had already been done. When True, ``record`` is
            the claim written by the first attempt and nothing was executed.
        record: The stored claim. Always present, whether new or replayed.
        guarded: Whether a claim row was actually written. False when the caller
            supplied no key, in which case :meth:`produced` is a no-op.
    """

    replayed: bool
    record: IdempotencyRecord
    guarded: bool = True

    def produced(self, obj: Model) -> None:
        """Point this claim at the object the guarded operation created.

        Called inside the same transaction as the work, so a claim and the rows it
        describes commit together. A crash between the two would otherwise leave a
        key claiming to be handled with nothing to show for it, and every later retry
        would be refused forever.

        Args:
            obj: The object the guarded operation created.
        """
        if not self.guarded:
            return
        self.record.object_type = f"{type(obj).__module__}.{type(obj).__qualname__}"
        self.record.object_id = str(obj.pk)
        self.record.save(update_fields=["object_type", "object_id", "updated_at"])


def claim_key(*, scope: str, key: str | None, body: Any) -> Claim:
    """Claim ``(scope, key)``, or report that the work was already done.

    Must be called inside the transaction that performs the work, so that the claim
    and its result commit or roll back together.

    The insert is the lock. A duplicate-key violation means another request got there
    first, and the stored fingerprint then decides whether this is a faithful retry
    (replay the stored result) or a key reused for a different body (refuse).

    Args:
        scope: The operation the key belongs to. Two operations may use the same key
            value without colliding.
        key: The client-supplied key, or None to run unguarded.
        body: The request payload, fingerprinted to detect key reuse.

    Returns:
        A :class:`Claim`. ``replayed`` is False when this call now owns the work.

    Raises:
        IdempotencyKeyReuse: If the key exists with a different request body.
        IdempotencyInFlight: If a concurrent request holds the key and has not
            finished, so there is no result to replay yet.
    """
    if key is None:
        # No key means no promise to keep, so there is nothing to claim. The record
        # is unsaved and produced() is a no-op, which keeps the caller's code free of
        # a branch on whether this request was guarded.
        return Claim(
            replayed=False,
            record=IdempotencyRecord(scope=scope, key="", request_fingerprint=fingerprint(body)),
            guarded=False,
        )

    cleaned = validate_key(key)
    digest = fingerprint(body)

    try:
        # A savepoint, so the unique violation does not poison the caller's
        # transaction: the work it wraps is still owed an attempt if the key turns
        # out to be a reuse.
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                scope=scope,
                key=cleaned,
                request_fingerprint=digest,
            )
        return Claim(replayed=False, record=record)
    except IntegrityError:
        pass

    existing = IdempotencyRecord.objects.filter(scope=scope, key=cleaned).first()
    if existing is None:
        # The row was created and then rolled back by the winner between our insert
        # and this read. Treat it as in flight: the winner is still deciding.
        raise IdempotencyInFlight

    if existing.request_fingerprint != digest:
        raise IdempotencyKeyReuse(
            f"Idempotency key {cleaned!r} was already used for a different {scope} request."
        )

    if not existing.object_type or not existing.object_id:
        # The first attempt claimed the key but has not recorded its result, so it is
        # still running. Retrying the same key is correct; minting a new one is not.
        raise IdempotencyInFlight

    return Claim(replayed=True, record=existing)


def replayed_object[M: "Model"](claim: Claim, model: type[M]) -> M | None:
    """Return the object a replayed claim refers to, if it still exists.

    The expected model is passed in rather than trusted from the stored label, for two
    reasons. A caller knows what it was guarding, so it gets a typed result back
    instead of a bare ``Model``; and a label in the database cannot redirect the lookup
    to some other table. The label is still checked against the model, because a claim
    recorded by a different scope is a bug worth refusing rather than casting away.

    Args:
        claim: A claim, normally one with ``replayed`` True.
        model: The model the guarded operation is expected to have created.

    Returns:
        The stored object, or None if the claim is not a replay, points at a different
        model, or the object has since been deleted. None is a real answer rather than
        an error: the caller asked whether the work was already done, and it was,
        whatever became of the result.

    Raises:
        AssertionError: If the claim names a different model than expected. That
            means one scope's claim was consulted for another's operation, which is a
            wiring bug; silently returning None would hide it.
    """
    if not claim.replayed or not claim.record.object_type:
        return None

    expected = f"{model.__module__}.{model.__qualname__}"
    assert claim.record.object_type == expected, (
        f"Idempotency claim points at {claim.record.object_type!r} but {expected!r} "
        f"was expected; the claim is being consulted for the wrong operation."
    )

    return model._default_manager.filter(pk=claim.record.object_id).first()


__all__ = [
    "IDEMPOTENCY_HEADER",
    "MAX_KEY_LENGTH",
    "SALE_SCOPE",
    "Claim",
    "IdempotencyRecord",
    "canonical",
    "claim_key",
    "fingerprint",
    "replayed_object",
    "validate_key",
]
