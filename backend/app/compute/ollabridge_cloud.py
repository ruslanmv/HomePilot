"""
OllaBridgeCloudComputeProvider (Wave A — Batch 6 / HP-1).

Routes generation to a paired GPU through OllaBridge Cloud's async job API
(docs/contracts/jobs-protocol.md): create a job, poll until it succeeds, and
return the resulting media-cache URLs. This is the path the proof gate uses:

    HomePilot (cloud mode) → POST /v1/images/generations → tier-1 routed to the
    user's own paired node → result back via the Cloud media cache.

The HTTP transport is injectable so the provider is unit-testable without a
running Cloud (tests pass an ``httpx.MockTransport``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import ComputeProvider, GeneratedMedia


class OllaBridgeCloudComputeProvider(ComputeProvider):
    name = "ollabridge_cloud"

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        image_model: str = "flux-schnell",
        video_model: str = "ltx-video",
        timeout: float = 300.0,
        poll_interval: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.image_model = image_model
        self.video_model = video_model
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._transport = transport

    # ---- HTTP plumbing ----

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, transport=self._transport,
        )

    def _abs_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    async def _create_and_await(self, path: str, body: dict) -> dict:
        async with self._client(self.timeout) as client:
            r = await client.post(path, json=body, headers=self._headers())
            r.raise_for_status()
            job_id = r.json()["id"]
            return await self._await_job(client, job_id)

    async def _await_job(self, client: httpx.AsyncClient, job_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            r = await client.get(f"/v1/jobs/{job_id}", headers=self._headers())
            r.raise_for_status()
            job = r.json()
            status = job.get("status")
            if status == "succeeded":
                return job
            if status in ("failed", "canceled"):
                err = (job.get("error") or {}).get("message", f"cloud job {status}")
                raise RuntimeError(err)
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"OllaBridge Cloud job {job_id} did not finish within {self.timeout}s")

    def _media_from_job(self, job: dict) -> GeneratedMedia:
        artifacts = (job.get("output") or {}).get("artifacts", [])
        images, videos = [], []
        for a in artifacts:
            url = self._abs_url(a.get("url", ""))
            ctype = a.get("content_type", "")
            (videos if ctype.startswith("video/") else images).append(url)
        return GeneratedMedia(
            images=images, videos=videos,
            meta={
                "provider": "ollabridge_cloud",
                "job_id": job.get("id"),
                "device": job.get("selected_device_id"),
                "gpu_seconds": job.get("gpu_seconds"),
            },
        )

    # ---- ComputeProvider interface ----

    async def generate_image(
        self, *, prompt, model=None, negative_prompt="",
        width=None, height=None, steps=None, seed=None, **extra,
    ) -> GeneratedMedia:
        body: dict[str, Any] = {"model": model or self.image_model, "prompt": prompt}
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        for k, v in (("width", width), ("height", height), ("steps", steps), ("seed", seed)):
            if v is not None:
                body[k] = v
        job = await self._create_and_await("/v1/images/generations", body)
        return self._media_from_job(job)

    async def edit_image(self, *, prompt, image, model=None, **extra) -> GeneratedMedia:
        body = {"model": model or self.image_model, "prompt": prompt, "image": image}
        job = await self._create_and_await("/v1/images/edits", body)
        return self._media_from_job(job)

    async def generate_video(self, *, prompt=None, image=None, model=None, **extra) -> GeneratedMedia:
        body: dict[str, Any] = {"model": model or self.video_model}
        if prompt is not None:
            body["prompt"] = prompt
        if image is not None:
            body["image"] = image
        body.update({k: v for k, v in extra.items() if v is not None})
        job = await self._create_and_await("/v1/videos/generations", body)
        return self._media_from_job(job)

    async def chat(self, *, model, messages, **extra) -> dict:
        body = {"model": model, "messages": messages}
        body.update({k: v for k, v in extra.items() if v is not None})
        async with self._client(self.timeout) as client:
            r = await client.post("/v1/chat/completions", json=body, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def available(self) -> bool:
        if not self.base_url:
            return False
        try:
            async with self._client(5.0) as client:
                r = await client.get("/health")
                return r.status_code < 500
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "ollabridge_cloud",
            "cloud_url": self.base_url,
            "configured": bool(self.token),
        }
