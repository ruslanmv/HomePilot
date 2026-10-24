"""Sign in with Hugging Face. The browser never receives the access token."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import hf_inference as hf

router = APIRouter(tags=["huggingface"])


def _cookie_flags(request: Request) -> dict:
    secure = bool(request.url.scheme == "https" or hf.on_huggingface())
    return {"httponly": True, "secure": secure, "samesite": "lax", "path": "/", "max_age": hf.SESSION_TTL_S}


@router.get("/v1/hf/session")
def hf_session(hp_hf_session: Optional[str] = Cookie(default=None)) -> JSONResponse:
    return JSONResponse(hf.session_public(hp_hf_session))


@router.get("/v1/hf/login")
def hf_login(request: Request) -> Response:
    if not hf.oauth_configured():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "message": "Hugging Face sign-in is not enabled on this Space yet. Chat keeps using the local model.",
            },
        )
    target = hf.authorization_url(hf.redirect_uri(str(request.base_url)))
    return RedirectResponse(target, status_code=302)


@router.get("/login/callback")
async def hf_callback(
    request: Request,
    code: str = "",
    state: str = "",
) -> HTMLResponse:
    if not hf.state_ok(state) or not code:
        return HTMLResponse("Sign-in could not be verified. Close this tab and try again.", status_code=400)
    try:
        session = await hf.exchange_code(code, hf.redirect_uri(str(request.base_url)))
    except Exception as exc:  # noqa: BLE001 — the page must not leak the token response
        return HTMLResponse(f"Sign-in failed. {exc}", status_code=502)
    response = HTMLResponse(hf.callback_page(session.get("username") or ""))
    response.set_cookie(hf.SESSION_COOKIE, session["sid"], **_cookie_flags(request))
    return response


@router.post("/v1/hf/logout")
def hf_logout(hp_hf_session: Optional[str] = Cookie(default=None)) -> JSONResponse:
    hf.drop_session(hp_hf_session)
    response = JSONResponse({"ok": True, "signed_in": False})
    response.delete_cookie(hf.SESSION_COOKIE, path="/")
    return response
