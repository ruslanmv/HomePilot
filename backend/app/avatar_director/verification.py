"""Adult-tier verification (spec v1.1 §16.2, batch B28).

The whole of this module exists to make one sentence true: **the server is the only thing
that can say a session is verified.** Everything else here is in service of that.

## Why a client dialog is not merely weak but forbidden

"Are you over 18? [Yes]" is not a check. It is a form field that records an assertion by the
person it is supposed to be checking, and every implementation of it in this industry has
been a fig leaf. §16.2 does not say a dialog is insufficient and should be supplemented — it
says it *must not be implemented*, because shipping one creates the appearance of a gate and
a code path that later gets trusted.

So there is no client path at all. `adultVerified` becomes true on the client exactly when
an ``adult_ack`` frame arrives, and this module is the only thing that can produce one. The
client tests assert the absence of any other writer; this file is the other half.

## Owner attestation, and why it refuses to load on a multi-user instance

The self-host default is the honest one: the person who owns the machine flips
``avatar.adult.enabled``, and the server attests on their behalf. That is a real statement —
the owner is asserting their own age about their own instance — and it is *only* real while
there is exactly one user. On an instance with accounts, the owner attesting for everybody is
attesting for people they have never met, which is worse than no gate because it looks like
one.

Hence :func:`OwnerAttestProvider.load` **raises** on a multi-user instance rather than
degrading. A distribution build must configure a real provider via ``avatar.adult.provider``;
the interface is one method, ``verify(user) -> Attestation``, and it is where a deployment
meets its local obligations. Compliance requirements vary by jurisdiction and this file does
not pretend to know them.

## Session-scoped, expiring, re-checked on reconnect

An attestation is a *fact about a session*, not a property of an account. It has an
expiry, it is never written to storage, and a reconnect re-asks — so revoking is closing the
tab, and a stolen frame is worth at most ``DEFAULT_TTL_SECONDS``.

Pure module: no FastAPI, no I/O of its own beyond the user count it is told to consult.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("avatar_director.verification")

#: How long one attestation stands. Short on purpose: it is re-asked on every reconnect, so
#: a long life buys nothing and costs the whole window in which a leaked frame is useful.
DEFAULT_TTL_SECONDS = 3600

#: The providers this build knows. A name outside it is a configuration error, not a fallback
#: — silently defaulting to owner-attest when somebody typos their real provider is exactly
#: how an instance ends up with no gate and no warning.
PROVIDERS = ("owner-attest",)


class VerificationError(Exception):
    """A refusal with a code, in the shape :mod:`panels` established."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Attestation:
    """What a provider returns. Frozen, and it carries no identity.

    Deliberately *not* "who this person is" — the tier needs to know that a session may
    proceed, and nothing else. A provider that learns a date of birth must not put it here,
    because everything here reaches the client.
    """

    verified: bool
    exp: float
    provider: str
    reason: str = ""

    def live(self, now: Optional[float] = None) -> bool:
        at = time.time() if now is None else now
        return bool(self.verified) and at < self.exp

    def as_ack(self, now: Optional[float] = None) -> Dict[str, Any]:
        """The ``adult_ack`` payload. The only shape in which verification crosses the wire."""
        return {
            "verified": self.live(now),
            "exp": self.exp,
            "provider": self.provider,
        }


class Provider:
    """The pluggable interface, in full. One method, and a refusal to be constructed wrong."""

    name = "abstract"

    def load(self) -> "Provider":
        """Called once, at registration. Raise to refuse to run on this instance."""
        return self

    def verify(self, user: Optional[str] = None, *, now: Optional[float] = None) -> Attestation:
        raise NotImplementedError


class OwnerAttestProvider(Provider):
    """The self-host default. Honest on one machine, dishonest on many — so it refuses."""

    name = "owner-attest"

    def __init__(self, *, ttl: int = DEFAULT_TTL_SECONDS, count_users: Optional[Callable[[], int]] = None) -> None:
        self.ttl = ttl
        self._count_users = count_users

    def user_count(self) -> int:
        if self._count_users is not None:
            return int(self._count_users())
        from app import users  # noqa: PLC0415 — lazy so this module imports without sqlite work

        return int(users.count_users())

    def load(self) -> "OwnerAttestProvider":
        """Refuse a multi-user instance. See the module header — this is the load-bearing line.

        A count of zero is a fresh install with the default user not yet created, which is
        still one person. Two or more means the owner would be attesting for strangers.
        """
        try:
            count = self.user_count()
        except Exception as error:  # noqa: BLE001 — a store that will not answer is not a yes
            raise VerificationError(
                "provider_unavailable",
                f"owner-attest cannot count the users on this instance: {error}",
            ) from error
        if count > 1:
            raise VerificationError(
                "provider_refuses_multi_user",
                f"owner-attest is a single-user provider and this instance has {count} accounts; "
                "configure a real verification provider via avatar.adult.provider",
            )
        return self

    def verify(self, user: Optional[str] = None, *, now: Optional[float] = None) -> Attestation:
        at = time.time() if now is None else now
        return Attestation(verified=True, exp=at + self.ttl, provider=self.name, reason="owner attestation")


class DisabledProvider(Provider):
    """What an instance with the tier off has. Answers no, always, and says why.

    Not `None`: a null provider means every caller writes its own "if configured" branch,
    and one of them eventually gets it wrong. A provider that refuses is a provider.
    """

    name = "disabled"

    def __init__(self, reason: str = "the adult tier is not enabled on this server") -> None:
        self.reason = reason

    def verify(self, user: Optional[str] = None, *, now: Optional[float] = None) -> Attestation:
        at = time.time() if now is None else now
        return Attestation(verified=False, exp=at, provider=self.name, reason=self.reason)


def build_provider(config, *, count_users: Optional[Callable[[], int]] = None) -> Provider:
    """The one factory. Returns a provider that always answers — never ``None``.

    With the tier disabled it returns :class:`DisabledProvider` **without consulting the
    named provider at all**, so an instance with ``adult.enabled = false`` cannot be made to
    load owner-attest by any request. That is §16.7's fourth invariant, at its source.
    """
    adult = getattr(config, "adult", None)
    if not adult or not getattr(adult, "enabled", False):
        return DisabledProvider()

    name = (getattr(adult, "provider", "") or "").strip()
    if name not in PROVIDERS:
        # Not a fallback. Silently defaulting when somebody typos their real provider is how
        # an instance ends up with no gate and no warning.
        log.error("avatar.adult.provider %r is not a provider this build knows", name)
        return DisabledProvider(f"{name!r} is not a verification provider this build knows")

    provider: Provider = OwnerAttestProvider(count_users=count_users)
    try:
        return provider.load()
    except VerificationError as error:
        log.error("adult verification provider refused to load — %s", error)
        return DisabledProvider(error.detail)


class Session:
    """One connected client's attestation, and the rules about it.

    Holds no identity and writes nothing. ``grant`` is replaced wholesale rather than
    mutated, so there is no half-verified state for a race to find.
    """

    def __init__(self, provider: Provider, *, now: Callable[[], float] = time.time) -> None:
        self.provider = provider
        self._now = now
        self.grant: Optional[Attestation] = None
        self.requests = 0
        self.grants = 0
        self.refusals = 0

    @property
    def verified(self) -> bool:
        """Live *now*. Never a stored boolean — an expiry that is only checked when it is
        set is an expiry that never fires."""
        return bool(self.grant and self.grant.live(self._now()))

    def request(self, user: Optional[str] = None) -> Attestation:
        """Ask the provider. The only way a grant comes into existence."""
        self.requests += 1
        attestation = self.provider.verify(user, now=self._now())
        if attestation.verified:
            self.grant = attestation
            self.grants += 1
        else:
            self.grant = None
            self.refusals += 1
        return attestation

    def revoke(self, why: str = "user") -> bool:
        """Drop it. Cheap, because there is nothing to unwind — see the header."""
        if self.grant is None:
            return False
        log.info("adult attestation revoked (%s)", why)
        self.grant = None
        return True

    def reconnect(self) -> None:
        """A new socket is a new session. §16.2: re-checked on every reconnect."""
        self.grant = None

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "provider": self.provider.name,
            "verified": self.verified,
            "requests": self.requests,
            "grants": self.grants,
            "refusals": self.refusals,
            "expiresIn": max(0, int(self.grant.exp - self._now())) if self.grant else None,
        }


__all__ = [
    "Attestation",
    "DEFAULT_TTL_SECONDS",
    "DisabledProvider",
    "OwnerAttestProvider",
    "PROVIDERS",
    "Provider",
    "Session",
    "VerificationError",
    "build_provider",
]
