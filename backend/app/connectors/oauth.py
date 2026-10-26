"""Sign in with Hugging Face — the one-click way to link the Hugging Face connector.

The standard OAuth 2.0 authorization-code flow with PKCE, the way "Sign in with …" buttons work
elsewhere:

  1. Settings → Connectors → "Continue with Hugging Face" asks ``POST …/oauth/start`` for a
     sign-in URL and opens it in a new window. The request is tied to the signed-in HomePilot
     user by a random, single-use ``state`` that expires after ten minutes.
  2. Hugging Face shows its own consent page: who is asking and what for (the scopes). The user
     clicks Accept — HomePilot never sees their password.
  3. Hugging Face sends the window back to ``GET …/oauth/callback`` with a code. The server
     swaps it (with the PKCE verifier and the app secret) for an access token, stores it like a
     pasted token (``store.py``, never returned to the browser), and the window tells the
     settings page it is done and closes itself.

Configuration:
  * On a Hugging Face Space, ``hf_oauth: true`` in the Space README creates the OAuth app and
    injects ``OAUTH_CLIENT_ID``, ``OAUTH_CLIENT_SECRET``, ``OAUTH_SCOPES`` and
    ``OPENID_PROVIDER_URL``; ``hf_oauth_scopes: [inference-api]`` lets the token call Inference
    Providers on the user's account.
  * Anywhere else, register an OAuth app at https://huggingface.co/settings/applications/new
    and set ``HOMEPILOT_HF_OAUTH_CLIENT_ID`` / ``HOMEPILOT_HF_OAUTH_CLIENT_SECRET`` (redirect URL:
    ``<your HomePilot URL>/v1/connectors/huggingface/oauth/callback``).
  * Without either, the connector offers only the access-token form, as before.

Tokens from this flow expire (``hf_oauth_expiration_minutes``, up to 30 days); the expiry is
kept with the connector and an expired one shows as "Reconnect" instead of failing calls.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

CALLBACK_PATH = "/v1/connectors/huggingface/oauth/callback"
STATE_TTL_S = 600
#: Scopes asked for outside a Space: who you are, and calls to Inference Providers.
DEFAULT_SCOPES = "openid profile inference-api"
#: Where people review or revoke what they granted, on Hugging Face.
MANAGE_URL = "https://huggingface.co/settings/connected-applications"


def client_id() -> str:
    return (os.getenv("HOMEPILOT_HF_OAUTH_CLIENT_ID") or os.getenv("OAUTH_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.getenv("HOMEPILOT_HF_OAUTH_CLIENT_SECRET") or os.getenv("OAUTH_CLIENT_SECRET") or "").strip()


def provider_url() -> str:
    return (os.getenv("OPENID_PROVIDER_URL") or "https://huggingface.co").strip().rstrip("/")


def scopes() -> str:
    # A Space's app may only ask for the scopes declared in its README.
    return (os.getenv("OAUTH_SCOPES") or os.getenv("HOMEPILOT_HF_OAUTH_SCOPES") or DEFAULT_SCOPES).strip()


def enabled() -> bool:
    return bool(client_id() and client_secret())


def can_call_models() -> bool:
    """Whether a token from this flow may call Inference Providers (the ``inference-api`` scope)."""
    return "inference-api" in scopes().split()


def redirect_uri(request_base: str) -> str:
    """The callback on this server. A Space is served at ``https://$SPACE_HOST``; elsewhere
    ``HOMEPILOT_PUBLIC_URL`` wins over the URL the request came in on (a proxy may hide it)."""
    public = (os.getenv("HOMEPILOT_PUBLIC_URL") or "").strip().rstrip("/")
    host = (os.getenv("SPACE_HOST") or "").strip()
    if public:
        base = public
    elif host:
        base = f"https://{host}"
    else:
        base = request_base.rstrip("/")
    return base + CALLBACK_PATH


# ── pending sign-ins (single use, short-lived; SQLite so any worker can finish one) ─────────

def _db() -> sqlite3.Connection:
    from ..storage import _get_db_path

    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_oauth_states(
            state TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            verifier TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            origin TEXT DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    return con


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def start(user_id: str, request_base: str, origin: str = "") -> str:
    """A Hugging Face sign-in URL for this user, valid for one use within STATE_TTL_S."""
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    uri = redirect_uri(request_base)
    con = _db()
    con.execute("DELETE FROM connector_oauth_states WHERE created_at < ?", (time.time() - STATE_TTL_S,))
    con.execute(
        "INSERT INTO connector_oauth_states(state, user_id, verifier, redirect_uri, origin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (state, user_id, verifier, uri, origin, time.time()),
    )
    con.commit()
    con.close()
    return f"{provider_url()}/oauth/authorize?" + urlencode({
        "client_id": client_id(),
        "redirect_uri": uri,
        "response_type": "code",
        "scope": scopes(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def take(state: str) -> Optional[Dict[str, Any]]:
    """The pending sign-in for ``state``, removed so it cannot be replayed; None if unknown or old."""
    if not state:
        return None
    con = _db()
    row = con.execute("SELECT * FROM connector_oauth_states WHERE state = ?", (state,)).fetchone()
    con.execute("DELETE FROM connector_oauth_states WHERE state = ?", (state,))
    con.commit()
    con.close()
    if not row or time.time() - row["created_at"] > STATE_TTL_S:
        return None
    return dict(row)


async def exchange(code: str, pending: Dict[str, Any]) -> Dict[str, Any]:
    """Swap the code for a token, then read who signed in. Raises ValueError with a plain reason."""
    import httpx

    basic = base64.b64encode(f"{client_id()}:{client_secret()}".encode()).decode()
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(
            f"{provider_url()}/oauth/token",
            headers={"Authorization": f"Basic {basic}"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": pending["redirect_uri"],
                "client_id": client_id(),
                "code_verifier": pending["verifier"],
            },
        )
        if res.status_code != 200:
            raise ValueError("Hugging Face did not accept the sign-in. Please try again.")
        tok = res.json()
        access = str(tok.get("access_token") or "")
        if not access:
            raise ValueError("Hugging Face did not return an access token.")
        info: Dict[str, Any] = {}
        who = await client.get(f"{provider_url()}/oauth/userinfo", headers={"Authorization": f"Bearer {access}"})
        if who.status_code == 200:
            info = who.json()
    expires_in = tok.get("expires_in")
    return {
        "token": access,
        "account": str(info.get("preferred_username") or info.get("name") or ""),
        "meta": {
            "via": "oauth",
            "name": str(info.get("name") or ""),
            "avatar": str(info.get("picture") or ""),
            "scopes": str(tok.get("scope") or scopes()),
            "expires_at": time.time() + float(expires_in) if expires_in else None,
        },
    }


def finish_page(ok: bool, *, account: str = "", error: str = "", origin: str = "") -> str:
    """The page the sign-in window lands on: tell the settings page, then close.

    Three channels, because a provider's opener policy can cut ``window.opener``: postMessage to
    the opener, a BroadcastChannel (same origin), and — always — the settings page polling the
    connector list. Only the outcome is sent, never the token."""
    payload = json.dumps({"type": "homepilot:connector", "id": "huggingface", "ok": ok,
                          "account": account, "error": error})
    target = json.dumps(origin or "*")
    title = "Hugging Face connected" if ok else "Could not connect Hugging Face"
    body = (f"Connected{(' as ' + html.escape(account)) if account else ''}. You can close this window."
            if ok else html.escape(error or "The sign-in did not finish."))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{color-scheme:dark}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0b0f;
color:#f4f4f5;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
.card{{max-width:360px;margin:16px;padding:28px;border-radius:20px;background:#16161c;border:1px solid #ffffff14;text-align:center}}
.mark{{width:48px;height:48px;margin:0 auto 14px;border-radius:14px;display:grid;place-items:center;font-size:26px;
background:{'#FFD21E' if ok else '#3f1d1d'}}}
h1{{font-size:18px;margin:0 0 6px}}p{{margin:0 0 18px;color:#a1a1aa}}
button{{min-height:44px;padding:0 20px;border:0;border-radius:999px;background:#fff;color:#000;font-weight:600;font-size:15px;cursor:pointer}}
</style></head><body><div class="card"><div class="mark" aria-hidden="true">{'🤗' if ok else '!'}</div>
<h1>{title}</h1><p>{body}</p><button type="button" onclick="window.close()">Back to HomePilot</button></div>
<script>
(function(){{var m={payload};
try{{if(window.opener)window.opener.postMessage(m,{target});}}catch(e){{}}
try{{var c=new BroadcastChannel("homepilot-connectors");c.postMessage(m);c.close();}}catch(e){{}}
if(m.ok)setTimeout(function(){{try{{window.close();}}catch(e){{}}}},900);}})();
</script></body></html>"""
