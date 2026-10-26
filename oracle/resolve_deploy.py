#!/usr/bin/env python3
"""Decide which app image an Oracle production deploy should wrap.

The Hugging Face Space and the GHCR app image both rebuild from master.
Production (homepilot.ruslanmv.com) is a thin wrapper around that GHCR image.
It used to run only when oracle/ or notifications/ changed, so the VM kept
serving a build from months earlier while the Space moved on.

This script is the gate for .github/workflows/oracle.yml:

- A successful GHCR publish deploys that commit's image.
- A push that only changes the wrapper deploys immediately, wrapping the
  newest published app image.
- A push that also changes the app image waits. The container workflow
  publishes it, and the workflow_run that follows deploys that exact tag.
- A failed or cancelled publish does not deploy, and a late run for an
  older commit does not roll production back once a newer image exists.

The app image is tagged with the 7-character commit id (container.yml,
docker/metadata-action type=sha), not the full 40-character sha.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

# Keep in sync with the `paths:` filters in .github/workflows/container.yml.
# A push that touches any of these publishes a new app image; the Oracle
# push must not deploy before that image exists.
APP_IMAGE_PREFIXES = (
    "container/",
    "backend/",
    "frontend/",
    "packages/",
    "expert/",
    "community/",
)
APP_IMAGE_FILES = frozenset({
    "tsconfig.base.json",
    ".dockerignore",
    ".github/workflows/container.yml",
    "scripts/download.py",
})

DEPLOY_BRANCHES = frozenset({"master", "main"})


@dataclass(frozen=True)
class Decision:
    skip: bool
    reason: str
    sha: str = ""
    base_image: str = ""


def touches_app_image(paths: list[str]) -> bool:
    for path in paths:
        if path in APP_IMAGE_FILES or path.startswith(APP_IMAGE_PREFIXES):
            return True
    return False


def needs_image_wait(event: str, changed: list[str] | None, tag_exists: bool) -> bool:
    """A master push that changes the app image starts in parallel with the
    GHCR build. Deploy only after that build's tag exists."""
    return event == "push" and bool(changed) and touches_app_image(changed) and not tag_exists


def decide(
    *,
    event: str,
    conclusion: str,
    branch: str,
    head_sha: str,
    changed: list[str] | None,
    image_tag_exists,
    latest_sha: str,
    master_sha: str,
    is_ancestor,
    owner: str,
    upstream_event: str = "",
) -> Decision:
    """Pure decision. Callers supply registry and git facts."""
    if event == "workflow_run":
        if branch not in DEPLOY_BRANCHES:
            return Decision(True, f"container publish ran on {branch or 'an unknown branch'}; production tracks master")
        if conclusion != "success":
            return Decision(True, f"container publish {conclusion or 'did not succeed'}; leaving production on the current image")
        # A push to master already has an Oracle run waiting on this image.
        # workflow_run is for a container publish that had no such push:
        # a manual Run workflow, or a GitHub release.
        if upstream_event == "push":
            return Decision(True, "the master push deploys this commit once its app image is published")

    sha = head_sha.strip()
    if not sha:
        raise SystemExit("no commit sha to deploy")
    short = sha[:7]
    app_image = f"ghcr.io/{owner}/homepilot"
    if image_tag_exists(short):
        chosen_sha = sha
        base = f"{app_image}:{short}"
        reason = f"wrapping app image {base}"
    elif event == "workflow_run":
        raise SystemExit(
            f"container publish succeeded but ghcr.io/{owner}/homepilot:{short} is not in the registry"
        )
    else:
        if not latest_sha:
            raise SystemExit(
                f"ghcr.io/{owner}/homepilot:{short} does not exist and :latest could not be resolved"
            )
        chosen_sha = latest_sha
        base = f"{app_image}:latest"
        reason = f"no app image for {short}; wrapping :latest ({latest_sha[:7]})"

    if (
        master_sha
        and chosen_sha != master_sha
        and is_ancestor(chosen_sha, master_sha)
        and image_tag_exists(master_sha[:7])
    ):
        return Decision(
            True,
            f"not deploying {chosen_sha[:7]}; origin/master ({master_sha[:7]}) already has an app image",
        )
    return Decision(False, reason, chosen_sha, base)


def _request(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def image_tag_exists(owner: str, tag: str, token: str) -> bool:
    """True when ghcr.io/<owner>/homepilot:<tag> has a manifest."""
    registry_token = _registry_token(owner, token)
    headers = {"Accept": "application/vnd.oci.image.index.v1+json"}
    if registry_token:
        headers["Authorization"] = f"Bearer {registry_token}"
    code, _ = _request(f"https://ghcr.io/v2/{owner}/homepilot/manifests/{tag}", headers)
    return code == 200


def _registry_token(owner: str, token: str) -> str:
    # Anonymous pull works for the public package. A private package needs the
    # Actions token as the password on the token exchange.
    url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{owner}/homepilot:pull"
    status, body = _request(url, {})
    if status != 200 and token:
        user = os.environ.get("GITHUB_ACTOR") or "git"
        import base64
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        status, body = _request(url, {"Authorization": f"Basic {creds}"})
    if status != 200:
        return ""
    try:
        return json.loads(body.decode() or "{}").get("token") or ""
    except ValueError:
        return ""


def latest_image_sha(owner: str, token: str) -> str:
    """Full commit baked into ghcr.io/<owner>/homepilot:latest.

    The image config carries org.opencontainers.image.revision (set by
    container.yml). That label is the source of truth: the short tag sitting
    beside :latest is only a nickname for the same digest.
    """
    revision = _image_revision(owner, "latest", token)
    if revision:
        return revision
    # Images published before that label existed: the package version that
    # wears :latest also wears the 7-character commit tag.
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "homepilot-oracle-deploy",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, body = _request(
        f"https://api.github.com/users/{owner}/packages/container/homepilot/versions?per_page=20",
        headers,
    )
    if status != 200:
        raise SystemExit(
            f"ghcr.io/{owner}/homepilot:latest has no revision label and the tag list "
            f"returned HTTP {status}"
        )
    try:
        versions = json.loads(body.decode() or "[]")
    except ValueError as exc:
        raise SystemExit(f"GHCR tag list was not JSON: {exc}") from exc
    short = ""
    for version in versions if isinstance(versions, list) else []:
        tags = ((version.get("metadata") or {}).get("container") or {}).get("tags") or []
        if "latest" in tags:
            others = [tag for tag in tags if tag != "latest"]
            short = others[0] if others else ""
            break
    if not short:
        raise SystemExit("ghcr.io image :latest has no commit tag beside it")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{short}^{{commit}}"],
        capture_output=True, text=True,
    )
    if resolved.returncode != 0:
        raise SystemExit(f"could not resolve app image tag {short} to a commit: {resolved.stderr.strip()}")
    return resolved.stdout.strip()


def first_image_digest(index: dict) -> str:
    """The first real image in an OCI index. Buildx also lists attestation
    manifests (platform unknown/unknown); their config has no labels."""
    for entry in index.get("manifests") or []:
        platform = entry.get("platform") or {}
        annotations = entry.get("annotations") or {}
        if platform.get("os") == "unknown" or "vnd.docker.reference.type" in annotations:
            continue
        digest = str(entry.get("digest") or "")
        if digest:
            return digest
    return ""


def _image_revision(owner: str, tag: str, token: str) -> str:
    registry_token = _registry_token(owner, token)
    headers = {"Authorization": f"Bearer {registry_token}"} if registry_token else {}
    status, body = _request(
        f"https://ghcr.io/v2/{owner}/homepilot/manifests/{tag}",
        {**headers, "Accept": "application/vnd.oci.image.index.v1+json"},
    )
    if status != 200:
        return ""
    try:
        index = json.loads(body.decode() or "{}")
    except ValueError:
        return ""
    digest = first_image_digest(index)
    if not digest and index.get("config"):
        # A single-platform manifest, not an index: its config is right here.
        config_digest = str((index.get("config") or {}).get("digest") or "")
        return _revision_from_config(owner, config_digest, headers)
    if not digest:
        return ""
    status, body = _request(
        f"https://ghcr.io/v2/{owner}/homepilot/manifests/{digest}",
        {**headers, "Accept": "application/vnd.oci.image.manifest.v1+json"},
    )
    if status != 200:
        return ""
    try:
        manifest = json.loads(body.decode() or "{}")
    except ValueError:
        return ""
    config_digest = str((manifest.get("config") or {}).get("digest") or "")
    return _revision_from_config(owner, config_digest, headers)


def _revision_from_config(owner: str, digest: str, headers: dict[str, str]) -> str:
    if not digest:
        return ""
    status, body = _request(
        f"https://ghcr.io/v2/{owner}/homepilot/blobs/{digest}",
        {**headers, "Accept": "application/vnd.oci.image.config.v1+json"},
    )
    if status != 200:
        return ""
    try:
        config = json.loads(body.decode() or "{}")
    except ValueError:
        return ""
    labels = ((config.get("config") or {}).get("Labels") or {})
    revision = str(labels.get("org.opencontainers.image.revision") or "").strip()
    return revision if len(revision) >= 7 else ""


def changed_files(sha: str) -> list[str] | None:
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^"],
        capture_output=True, text=True,
    )
    if parent.returncode != 0:
        return None
    diff = subprocess.run(
        ["git", "diff", "--name-only", parent.stdout.strip(), sha],
        capture_output=True, text=True, check=True,
    )
    return [line for line in diff.stdout.splitlines() if line.strip()]


def master_head() -> str:
    subprocess.run(["git", "fetch", "--depth=300", "origin", "master"], check=False)
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/master"],
        capture_output=True, text=True,
    )
    return resolved.stdout.strip() if resolved.returncode == 0 else ""


def git_is_ancestor(older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
    )
    return result.returncode == 0


def wait_for_app_image(owner: str, sha: str, token: str, repo: str) -> None:
    """Block until ghcr.io/<owner>/homepilot:<short> exists, or the publish fails."""
    import time
    short = sha[:7]
    deadline = time.time() + int(os.environ.get("IMAGE_WAIT_SECONDS", "5400"))
    last = ""
    while time.time() < deadline:
        if image_tag_exists(owner, short, token):
            print(f"app image ghcr.io/{owner}/homepilot:{short} is published", flush=True)
            return
        state = _container_run_state(repo, sha, token) if repo else ""
        if state in {"failure", "cancelled", "timed_out", "startup_failure"}:
            raise SystemExit(f"container publish {state}; production stays on the current image")
        note = f"waiting for ghcr.io/{owner}/homepilot:{short} (container publish: {state or 'pending'})"
        if note != last:
            print(note, flush=True)
            last = note
        time.sleep(int(os.environ.get("IMAGE_WAIT_INTERVAL", "20")))
    raise SystemExit(f"timed out waiting for ghcr.io/{owner}/homepilot:{short}")


def _container_run_state(repo: str, sha: str, token: str) -> str:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "homepilot-oracle-deploy"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, body = _request(
        f"https://api.github.com/repos/{repo}/actions/workflows/container.yml/runs?head_sha={sha}&per_page=5",
        headers,
    )
    if status != 200:
        return ""
    try:
        runs = json.loads(body.decode() or "{}").get("workflow_runs") or []
    except ValueError:
        return ""
    if not runs:
        return ""
    run = runs[0]
    if run.get("status") != "completed":
        return str(run.get("status") or "")
    return str(run.get("conclusion") or "")


def emit(key: str, value: str) -> None:
    line = f"{key}={value}\n"
    path = os.environ.get("GITHUB_OUTPUT", "")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    print(line, end="")


def main() -> None:
    event = os.environ.get("EVENT_NAME", "").strip()
    conclusion = os.environ.get("WORKFLOW_CONCLUSION", "").strip()
    branch = os.environ.get("HEAD_BRANCH", "").strip()
    sha = os.environ.get("HEAD_SHA", "").strip()
    owner = os.environ.get("REPO_OWNER", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    upstream = os.environ.get("UPSTREAM_EVENT", "").strip()
    if not owner:
        raise SystemExit("REPO_OWNER is required")

    changed = changed_files(sha) if event == "push" and sha else None
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if sha and needs_image_wait(event, changed, image_tag_exists(owner, sha[:7], token)):
        wait_for_app_image(owner, sha, token, repo)
    # Skip paths do not need the registry. Looking :latest up only when this
    # commit has no tag of its own avoids a packages API call on every publish.
    preliminary = decide(
        event=event,
        conclusion=conclusion,
        branch=branch,
        head_sha=sha or "0" * 40,
        changed=changed,
        image_tag_exists=lambda _tag: True,
        latest_sha=sha or "0" * 40,
        master_sha="",
        is_ancestor=lambda _older, _newer: False,
        owner=owner,
        upstream_event=upstream,
    )
    if preliminary.skip or not sha:
        decision = preliminary if sha else Decision(True, "no commit sha to deploy")
        if not sha and event != "workflow_run":
            raise SystemExit("no commit sha to deploy")
    else:
        latest = ""
        if event != "workflow_run" and not image_tag_exists(owner, sha[:7], token):
            latest = latest_image_sha(owner, token)
        decision = decide(
            event=event,
            conclusion=conclusion,
            branch=branch,
            head_sha=sha,
            changed=changed,
            image_tag_exists=lambda tag: image_tag_exists(owner, tag, token),
            latest_sha=latest,
            master_sha=master_head(),
            is_ancestor=git_is_ancestor,
            owner=owner,
            upstream_event=upstream,
        )
    print(decision.reason, flush=True)
    if decision.skip:
        print(f"::notice::{decision.reason}")
    emit("skip", "true" if decision.skip else "false")
    emit("sha", decision.sha)
    emit("base_image", decision.base_image)
    emit("reason", decision.reason)


if __name__ == "__main__":
    main()
