"""
HomePilot One — routing policy, per-user preferences and the spending ledger.

HomePilot decides *policy*; OllaBridge decides *execution*. This module is the
HomePilot half of that contract:

* **Preferences** — each user's strategy, privacy mode and spending rules,
  stored per user (never in a shared row) so the hosted, multi-user edition
  cannot leak one user's settings into another's request.
* **Precedence** — operator restrictions > privacy > spending > the user's
  preference > the edition default. A user can always make routing stricter
  than the operator allows, never looser.
* **Policy header** — the signed ``X-HomePilot-Policy`` the gateway trusts
  (docs/HOMEPILOT_ONE_ARCHITECTURE.md). Minted server-side per request; the
  browser never sees it and cannot forge it.
* **Ledger** — what each request cost and who served it, so daily and monthly
  budgets are enforced from HomePilot's own durable record.

Strategies
----------
``hf_first``       Hugging Face → other free APIs → authorised paid → my PC.
``local_first``    My paired PC first, then the hosted tiers.
``private_local``  Only my own machines. Never a hosted provider. Offline is
                   an explicit error, not a silent fallback.
``lowest_cost`` / ``fastest`` / ``quality_first``  Reorder what is permitted.
``pinned``         A model route configured in Settings → Models (unchanged).
``legacy``         Routing as it was before HomePilot One (the default on a
                   local install, so existing setups behave exactly as before).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Optional

from ..storage import _get_db_path

POLICY_HEADER = "X-HomePilot-Policy"
CREDENTIALS_HEADER = "X-HomePilot-Provider-Credentials"
HOP_HEADER = "X-OllaBridge-Hop"
ORIGIN_HEADER = "X-OllaBridge-Origin"
REQUEST_ID_HEADER = "X-Request-Id"
POLICY_TTL_S = 120
MAX_HOPS = 3

STRATEGIES = (
    "hf_first", "local_first", "private_local", "lowest_cost",
    "fastest", "quality_first", "pinned", "legacy",
)
#: Strategies that send the request through the gateway's provider selection.
GATEWAY_STRATEGIES = ("hf_first", "local_first", "private_local", "lowest_cost",
                      "fastest", "quality_first")
CHAT_MODALITIES = ("chat", "multimodal")

_PREFS_TABLE = "user_routing_prefs"
_LEDGER_TABLE = "inference_usage"


# ── environment (operator defaults and restrictions) ────────────────


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    return default if not raw else raw.lower() in ("1", "true", "yes", "on")


def _env_float(name: str) -> Optional[float]:
    raw = _env(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def is_web() -> bool:
    from ..config import HOMEPILOT_EDITION
    return HOMEPILOT_EDITION == "web"


def default_strategy() -> str:
    """``HOMEPILOT_ROUTING_STRATEGY``; else ``hf_first`` on the hosted web
    edition and ``legacy`` on a local install."""
    chosen = _env("HOMEPILOT_ROUTING_STRATEGY").lower()
    if chosen in STRATEGIES:
        return chosen
    return "hf_first" if is_web() else "legacy"


def operator_allows_paid() -> bool:
    """The paid-provider kill switch. Off unless the operator turns it on."""
    return _env_bool("HOMEPILOT_ALLOW_PAID_FALLBACK", False)


def operator_inference_allowed() -> bool:
    """May operator-held provider keys serve users who linked no account of
    their own? Explicit on the web edition (default on, as today's Space token
    behaviour); never on a local install, where there is no operator."""
    return _env_bool("HOMEPILOT_OPERATOR_INFERENCE", is_web())


def hosted_alias(modality: str = "chat") -> str:
    if modality == "multimodal":
        return _env("HOMEPILOT_VISION_ALIAS", "homepilot-vision")
    return _env("HOMEPILOT_HOSTED_ALIAS", "homepilot-auto")


def policy_secret() -> str:
    return _env("HOMEPILOT_POLICY_SECRET")


# ── per-user preferences ─────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingPrefs:
    strategy: str = "legacy"
    allow_paid: bool = False
    #: USD. ``None`` = no limit of that kind.
    max_request_cost_usd: Optional[float] = None
    daily_budget_usd: Optional[float] = None
    monthly_budget_usd: Optional[float] = None
    #: Share my paired computers with my own hosted session.
    use_my_devices: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def ensure_tables() -> None:
    con = _conn()
    try:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {_PREFS_TABLE} ("
            "user_id TEXT PRIMARY KEY, prefs TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {_LEDGER_TABLE} ("
            "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, ts REAL NOT NULL, "
            "modality TEXT, provider TEXT, provider_kind TEXT, model TEXT, tier TEXT, "
            "billing TEXT, credential TEXT, execution TEXT, request_id TEXT, "
            "cost_usd REAL, cost_known INTEGER NOT NULL DEFAULT 0, "
            "prompt_tokens INTEGER, completion_tokens INTEGER, "
            "fell_back INTEGER NOT NULL DEFAULT 0, fallback_reason TEXT)"
        )
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{_LEDGER_TABLE}_user_ts "
            f"ON {_LEDGER_TABLE}(user_id, ts)"
        )
        con.commit()
    finally:
        con.close()


def _defaults() -> RoutingPrefs:
    return RoutingPrefs(
        strategy=default_strategy(),
        allow_paid=operator_allows_paid(),
        max_request_cost_usd=_env_float("HOMEPILOT_MAX_REQUEST_COST_USD"),
        daily_budget_usd=_env_float("HOMEPILOT_DAILY_BUDGET_USD"),
        monthly_budget_usd=_env_float("HOMEPILOT_MONTHLY_BUDGET_USD"),
    )


def _opt_float(value: Any) -> Optional[float]:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def load_prefs(user_id: str) -> RoutingPrefs:
    """This user's saved preferences over the operator defaults.

    Read failures return the defaults: a locked or missing database must never
    take down an inference path (nor loosen it — the defaults are the
    operator's own)."""
    prefs = _defaults()
    if not user_id:
        return prefs
    try:
        ensure_tables()
        con = _conn()
        try:
            row = con.execute(
                f"SELECT prefs FROM {_PREFS_TABLE} WHERE user_id = ?", (user_id,)
            ).fetchone()
        finally:
            con.close()
        saved = json.loads(row["prefs"]) if row else {}
    except Exception:
        saved = {}
    if not isinstance(saved, dict):
        return prefs
    strategy = str(saved.get("strategy") or prefs.strategy).lower()
    return RoutingPrefs(
        strategy=strategy if strategy in STRATEGIES else prefs.strategy,
        allow_paid=bool(saved.get("allow_paid", prefs.allow_paid)),
        max_request_cost_usd=_opt_float(saved["max_request_cost_usd"])
        if "max_request_cost_usd" in saved else prefs.max_request_cost_usd,
        daily_budget_usd=_opt_float(saved["daily_budget_usd"])
        if "daily_budget_usd" in saved else prefs.daily_budget_usd,
        monthly_budget_usd=_opt_float(saved["monthly_budget_usd"])
        if "monthly_budget_usd" in saved else prefs.monthly_budget_usd,
        use_my_devices=bool(saved.get("use_my_devices", True)),
    )


def save_prefs(user_id: str, changes: Mapping[str, Any]) -> RoutingPrefs:
    """Persist a user's own preferences. Unknown keys are ignored."""
    if not user_id:
        raise ValueError("a user is required to save routing preferences")
    allowed = set(RoutingPrefs.__dataclass_fields__)
    current: dict[str, Any] = {}
    ensure_tables()
    con = _conn()
    try:
        row = con.execute(
            f"SELECT prefs FROM {_PREFS_TABLE} WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            try:
                current = json.loads(row["prefs"]) or {}
            except Exception:
                current = {}
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "strategy":
                value = str(value or "").lower()
                if value not in STRATEGIES:
                    raise ValueError(f"unknown strategy '{value}'")
            current[key] = value
        con.execute(
            f"INSERT INTO {_PREFS_TABLE}(user_id, prefs, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET prefs=excluded.prefs, updated_at=excluded.updated_at",
            (user_id, json.dumps(current), time.time()),
        )
        con.commit()
    finally:
        con.close()
    return load_prefs(user_id)


def effective_prefs(user_id: str) -> RoutingPrefs:
    """Preferences after operator restrictions — what routing actually uses."""
    prefs = load_prefs(user_id)
    if not operator_allows_paid():
        prefs = replace(prefs, allow_paid=False)   # the kill switch always wins
    return prefs


# ── spending ledger ──────────────────────────────────────────────────


def _period_start(period: str, now: Optional[float] = None) -> float:
    t = time.gmtime(now if now is not None else time.time())
    if period == "day":
        return float(_timegm((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0)))
    return float(_timegm((t.tm_year, t.tm_mon, 1, 0, 0, 0)))


def _timegm(parts: tuple) -> int:
    import calendar
    return calendar.timegm(parts + (0, 0, 0))


def record_usage(user_id: str, provenance: Mapping[str, Any], *, modality: str = "chat") -> None:
    """Append one served request to the ledger. Never raises into a request."""
    if not user_id or not provenance:
        return
    cost = provenance.get("cost") or {}
    actual = cost.get("actual_usd")
    amount = actual if actual is not None else cost.get("estimated_usd")
    usage = provenance.get("usage") or {}
    try:
        ensure_tables()
        con = _conn()
        try:
            con.execute(
                f"INSERT INTO {_LEDGER_TABLE}(id, user_id, ts, modality, provider, provider_kind, "
                "model, tier, billing, credential, execution, request_id, cost_usd, cost_known, "
                "prompt_tokens, completion_tokens, fell_back, fallback_reason) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex, user_id, time.time(), modality,
                    provenance.get("provider"), provenance.get("provider_kind"),
                    provenance.get("model"), provenance.get("tier"), provenance.get("billing"),
                    provenance.get("credential"), provenance.get("execution"),
                    provenance.get("request_id"),
                    float(amount) if amount is not None else None,
                    1 if amount is not None else 0,
                    usage.get("prompt_tokens"), usage.get("completion_tokens"),
                    1 if provenance.get("fell_back") else 0, provenance.get("fallback_reason"),
                ),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def spent(user_id: str, period: str, *, billing: Optional[str] = "paid",
          now: Optional[float] = None) -> float:
    """USD recorded for this user since the start of the day or month.

    ``billing="paid"`` (the default) counts only money actually spent;
    ``billing=None`` counts everything, including the value of included
    allowances."""
    if not user_id:
        return 0.0
    try:
        ensure_tables()
        con = _conn()
        try:
            sql = (f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {_LEDGER_TABLE} "
                   "WHERE user_id = ? AND ts >= ?")
            args: list[Any] = [user_id, _period_start(period, now)]
            if billing:
                sql += " AND billing = ?"
                args.append(billing)
            return float(con.execute(sql, args).fetchone()["total"] or 0.0)
        finally:
            con.close()
    except Exception:
        return 0.0


def hf_included_spent(user_id: str, credential: str, now: Optional[float] = None) -> float:
    """Estimated value of Hugging Face included allowance used this month.

    A user's own linked account is theirs alone; the operator's token is one
    allowance shared by every user who relies on it, so it is summed across
    users."""
    try:
        ensure_tables()
        con = _conn()
        try:
            sql = (f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {_LEDGER_TABLE} "
                   "WHERE provider_kind = 'huggingface' AND billing = 'included' "
                   "AND ts >= ? AND credential = ?")
            args: list[Any] = [_period_start("month", now), credential]
            if credential == "caller":
                sql += " AND user_id = ?"
                args.append(user_id)
            return float(con.execute(sql, args).fetchone()["total"] or 0.0)
        finally:
            con.close()
    except Exception:
        return 0.0


def usage_summary(user_id: str) -> dict[str, Any]:
    prefs = effective_prefs(user_id)
    day, month = spent(user_id, "day"), spent(user_id, "month")
    rows: list[dict[str, Any]] = []
    try:
        ensure_tables()
        con = _conn()
        try:
            rows = [dict(r) for r in con.execute(
                f"SELECT provider, provider_kind, tier, billing, COUNT(*) AS requests, "
                f"COALESCE(SUM(cost_usd),0) AS cost_usd, "
                f"SUM(CASE WHEN cost_known=0 THEN 1 ELSE 0 END) AS unknown_cost_requests "
                f"FROM {_LEDGER_TABLE} WHERE user_id = ? AND ts >= ? "
                "GROUP BY provider, provider_kind, tier, billing ORDER BY requests DESC",
                (user_id, _period_start("month")),
            )]
        finally:
            con.close()
    except Exception:
        rows = []
    return {
        "paid_spent_today_usd": round(day, 6),
        "paid_spent_month_usd": round(month, 6),
        "daily_budget_usd": prefs.daily_budget_usd,
        "monthly_budget_usd": prefs.monthly_budget_usd,
        "budget_exhausted": remaining_budget(user_id, prefs) == 0.0,
        "this_month": rows,
    }


def remaining_budget(user_id: str, prefs: Optional[RoutingPrefs] = None) -> Optional[float]:
    """The most a single paid request may cost right now, or ``None`` when no
    limit of any kind is set. ``0.0`` means a budget is exhausted."""
    prefs = prefs or effective_prefs(user_id)
    limits: list[float] = []
    if prefs.max_request_cost_usd is not None:
        limits.append(prefs.max_request_cost_usd)
    if prefs.daily_budget_usd is not None:
        limits.append(max(0.0, prefs.daily_budget_usd - spent(user_id, "day")))
    if prefs.monthly_budget_usd is not None:
        limits.append(max(0.0, prefs.monthly_budget_usd - spent(user_id, "month")))
    return min(limits) if limits else None


# ── privacy guard for HomePilot's own executor ───────────────────────

_HOSTED_LLM_PROVIDERS = ("huggingface", "openai", "claude", "watsonx")


def _is_own_network(url: str) -> bool:
    """True for loopback / private-network addresses (this machine, the LAN)."""
    import ipaddress
    from urllib.parse import urlparse
    host = (urlparse(url if "://" in url else f"http://{url}").hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith((".local", ".lan", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host        # a bare service name (docker-compose) is local
    return ip.is_loopback or ip.is_private or ip.is_link_local


class PrivacyRestricted(RuntimeError):
    """``private_local`` is set and the request would leave the user's machines."""

    code = "privacy_restricted"


def assert_private_ok(user_id: str, provider: Optional[str], base_url: Optional[str]) -> None:
    """Refuse a hosted LLM provider under ``private_local``.

    The ``local`` target runs whatever provider the request names — on some
    setups that is a hosted API. In private mode that is an explicit error,
    never a silent leak."""
    if effective_prefs(user_id).strategy != "private_local":
        return
    hosted = (provider or "") in _HOSTED_LLM_PROVIDERS
    if not hosted and base_url:
        hosted = not _is_own_network(base_url)
    if hosted:
        raise PrivacyRestricted(
            "private_local is on: this request would be sent to a hosted provider "
            f"({provider or base_url}). Choose a local model, or change the routing "
            "mode in Settings."
        )


# ── execution context (loop guard, provenance) ───────────────────────

_hop: ContextVar[int] = ContextVar("hp_routing_hop", default=0)
_last_provenance: ContextVar[Optional[dict]] = ContextVar("hp_routing_provenance", default=None)


def set_inbound_hop(value: Any) -> None:
    """Record how many times this request already passed through the gateway
    (from ``X-OllaBridge-Hop`` on the inbound persona API)."""
    try:
        _hop.set(max(0, int(value or 0)))
    except (TypeError, ValueError):
        _hop.set(0)


def current_hop() -> int:
    return _hop.get()


def gateway_allowed() -> bool:
    """False once a request has bounced enough that sending it to the gateway
    again could loop — HomePilot must then answer with its own executor."""
    return _hop.get() + 1 < MAX_HOPS


def note_provenance(provenance: Optional[dict]) -> None:
    _last_provenance.set(provenance)


def take_provenance() -> Optional[dict]:
    value = _last_provenance.get()
    _last_provenance.set(None)
    return value


# ── the signed policy header ─────────────────────────────────────────


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def encode_credentials(credentials: Mapping[str, str]) -> str:
    clean = {k: v for k, v in credentials.items() if k and v}
    return _b64e(json.dumps(clean, sort_keys=True).encode()) if clean else ""


def sign_policy(claims: Mapping[str, Any], *, credentials_header: str = "",
                secret: Optional[str] = None, now: Optional[float] = None) -> str:
    """Byte-compatible with ``ollabridge_cloud.addons.providers.policy``."""
    body = dict(claims)
    issued = int(now if now is not None else time.time())
    body.setdefault("iat", issued)
    body.setdefault("exp", issued + POLICY_TTL_S)
    if credentials_header:
        body["cred"] = hashlib.sha256(credentials_header.encode()).hexdigest()
    payload = _b64e(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    key = policy_secret() if secret is None else secret
    if not key:
        return payload
    return f"{payload}.{hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()}"


@dataclass(frozen=True)
class GatewayCall:
    """Everything one gateway request needs. Built per request, in memory."""

    claims: dict
    headers: dict
    token: str
    #: ``"caller"`` when a user-linked provider key is forwarded, else ``"operator"``.
    hf_credential: str
    request_id: str


def _user_cloud_token(user_id: str) -> str:
    try:
        from ..cloud_tokens import get_cloud_token
        return (get_cloud_token(user_id) or "").strip() if user_id else ""
    except Exception:
        return ""


def _user_hf_token(user_id: str) -> str:
    """The user's *own* linked Hugging Face token — never the Space's."""
    try:
        from ..connectors import store
        return (store.secret(user_id, "huggingface") or "").strip() if user_id else ""
    except Exception:
        return ""


def build_gateway_call(
    user_id: str,
    *,
    modality: str = "chat",
    require: tuple[str, ...] = (),
    prefer_model: Optional[str] = None,
    prefs: Optional[RoutingPrefs] = None,
) -> GatewayCall:
    """Mint the policy and credentials for one request by ``user_id``.

    Identity rules (tenant isolation):

    * The gateway is called with **this user's** OllaBridge token when they
      linked an account; only then may their own paired devices be used.
    * Otherwise, on the hosted edition, the operator's service token is used
      for hosted providers only — ``allow_relay`` is false, so an operator
      token is never an authorisation to reach anyone's devices.
    * On a single-user local install the configured token is the user's own.
    * Only this user's linked Hugging Face token is ever forwarded, and only
      inside this request.
    """
    from ..config import OLLABRIDGE_CLOUD_TOKEN

    prefs = prefs or effective_prefs(user_id)
    own_cloud = _user_cloud_token(user_id)
    operator_cloud = (OLLABRIDGE_CLOUD_TOKEN or "").strip()
    if own_cloud:
        token, allow_relay = own_cloud, prefs.use_my_devices
    elif is_web():
        token, allow_relay = operator_cloud, False
    else:
        token, allow_relay = operator_cloud, prefs.use_my_devices

    hf_token = _user_hf_token(user_id)
    credentials = {"huggingface": hf_token} if hf_token else {}
    hf_credential = "caller" if hf_token else "operator"

    strategy = prefs.strategy if prefs.strategy in GATEWAY_STRATEGIES else "hf_first"
    request_id = uuid.uuid4().hex
    claims: dict[str, Any] = {
        "strategy": strategy,
        "privacy": "private_local" if strategy == "private_local" else "hosted_allowed",
        "allow_paid": bool(prefs.allow_paid),
        "max_cost_usd": remaining_budget(user_id, prefs),
        "allow_operator_credentials": operator_inference_allowed(),
        "allow_relay": bool(allow_relay),
        "sub": user_id,
        "rid": request_id,
    }
    if require:
        claims["require"] = list(require)
    if prefer_model:
        claims["prefer_model"] = prefer_model
    included = _env_float("HOMEPILOT_HF_INCLUDED_USD")
    if included is not None:
        claims["hf_included_remaining_usd"] = max(
            0.0, included - hf_included_spent(user_id, hf_credential))

    cred_header = encode_credentials(credentials) if policy_secret() else ""
    headers = {
        POLICY_HEADER: sign_policy(claims, credentials_header=cred_header),
        ORIGIN_HEADER: "homepilot",
        HOP_HEADER: str(current_hop() + 1),
        REQUEST_ID_HEADER: request_id,
    }
    if cred_header:
        # Forwarded only under a signed policy; without a shared secret the
        # gateway would reject it, so it is simply not sent.
        headers[CREDENTIALS_HEADER] = cred_header
    else:
        hf_credential = "operator"
    return GatewayCall(claims=claims, headers=headers, token=token,
                       hf_credential=hf_credential, request_id=request_id)


def describe(user_id: str) -> dict[str, Any]:
    """The user's routing state for Settings — no secrets."""
    prefs = load_prefs(user_id)
    effective = effective_prefs(user_id)
    return {
        "prefs": prefs.to_dict(),
        "effective": effective.to_dict(),
        "strategies": list(STRATEGIES),
        "default_strategy": default_strategy(),
        "operator": {
            "paid_allowed": operator_allows_paid(),
            "operator_inference": operator_inference_allowed(),
            "policy_signed": bool(policy_secret()),
        },
        "priority": priority_for(effective.strategy, effective.allow_paid),
    }


def priority_for(strategy: str, allow_paid: bool) -> list[str]:
    paid = ["Authorised paid APIs"] if allow_paid else []
    hosted = ["Hugging Face", "Other free APIs", *paid]
    if strategy == "private_local":
        return ["My computers only"]
    if strategy == "local_first":
        return ["My computers", *hosted]
    if strategy == "legacy":
        return ["This installation's configured provider"]
    if strategy == "pinned":
        return ["The model routes set in Models"]
    label = {"lowest_cost": " (cheapest first)", "fastest": " (fastest first)",
             "quality_first": " (strongest first)"}.get(strategy, "")
    return [h + label if i == 0 and label else h for i, h in enumerate(hosted)] + ["My computers"]
