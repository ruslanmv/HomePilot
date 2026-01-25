"""
HomePilot API client module.

Provides async HTTP client for communicating with the HomePilot backend service.
Handles upload and chat endpoints with proper error handling.
"""

from __future__ import annotations

import httpx
from typing import Any, Dict
from fastapi import HTTPException

from .config import settings


class HomePilotClient:
    """
    Async HTTP client for HomePilot backend API.

    Handles:
    - Image upload proxying
    - Chat request forwarding
    - Error handling and response parsing
    """

    def __init__(self):
        """Initialize client with configuration."""
        self.base = settings.HOME_PILOT_BASE_URL.rstrip("/")
        self.hp_key = settings.HOME_PILOT_API_KEY

    def _headers(self) -> Dict[str, str]:
        """
        Build request headers.

        Includes API key if configured.
        """
        headers: Dict[str, str] = {}
        if self.hp_key:
            headers["X-API-Key"] = self.hp_key
        return headers

    async def upload(
        self,
        filename: str,
        content_type: str,
        data: bytes
    ) -> str:
        """
        Upload an image to HomePilot and return the URL.

        Args:
            filename: Original filename
            content_type: MIME type (e.g., image/png)
            data: Raw image bytes

        Returns:
            URL of the uploaded image

        Raises:
            HTTPException: On upload failure or invalid response
        """
        url = f"{self.base}/upload"
        files = {"file": (filename, data, content_type)}

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(
                    url,
                    files=files,
                    headers=self._headers()
                )
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"HomePilot upload error: {e}"
                ) from e

        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"HomePilot upload failed: {resp.status_code} {resp.text}"
            )

        payload: Any = None
        try:
            payload = resp.json()
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="HomePilot upload returned non-JSON response"
            )

        # Be flexible: HomePilot might return various URL field names
        url_fields = ("url", "file_url", "image_url", "download_url")
        for key in url_fields:
            if isinstance(payload, dict) and payload.get(key):
                return str(payload[key])

        # Handle nested response: { "data": { "url": ... } }
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            d = payload["data"]
            for key in url_fields:
                if d.get(key):
                    return str(d[key])

        raise HTTPException(
            status_code=502,
            detail="HomePilot upload JSON did not include a URL"
        )

    async def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Forward a chat request to HomePilot.

        Args:
            payload: Chat request payload (message, mode, etc.)

        Returns:
            HomePilot response as dictionary

        Raises:
            HTTPException: On request failure or invalid response
        """
        url = f"{self.base}/chat"

        # Use longer timeout for image generation (can take minutes)
        async with httpx.AsyncClient(timeout=180) as client:
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=self._headers()
                )
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"HomePilot chat error: {e}"
                ) from e

        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"HomePilot chat failed: {resp.status_code} {resp.text}"
            )

        try:
            return resp.json()
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="HomePilot chat returned non-JSON response"
            )

    async def health_check(self) -> bool:
        """
        Check if HomePilot backend is reachable.

        Returns:
            True if backend responds to health check
        """
        url = f"{self.base}/health"

        async with httpx.AsyncClient(timeout=5) as client:
            try:
                resp = await client.get(url, headers=self._headers())
                return resp.status_code < 400
            except Exception:
                return False
