# Coding in HomePilot with GitPilot

HomePilot can plan code changes, apply them on a branch and open pull requests
by using [GitPilot](https://github.com/ruslanmv/gitpilot) as its coding
backend. It is a **connector**: nothing changes until a user links it, and it
adds tools to agent chats instead of replacing anything.

Built against GitPilot branch `fix/github-device-poll-500-retry`
(commit `4d24aae`, 15 commits ahead of `master`, 0 behind, as of 2026-11-12).

## For users

1. **Settings → Connectors → GitPilot → Connect.** Enter where your GitPilot
   runs (for example `http://localhost:8000`) and a GitHub token. Leave the
   token empty if your GitPilot already signs in to GitHub.
2. In an agent chat, ask in plain words: *"In octocat/app, add a health
   endpoint with a test."*
3. HomePilot shows GitPilot's **plan** — steps and files. Nothing has changed.
4. To make the change, the assistant asks for approval and gives a code.
   Reply **`approve K7QW2M`** (or `deny K7QW2M`), or press Approve in
   Settings → Connectors. The change is written to a **new branch**.
5. Ask for a pull request. That also needs your approval. You merge on GitHub.

A **Read-only** switch in the connector lets HomePilot plan but never change.

## The design, and why

| Practice | How it is done here |
|---|---|
| Plan, then act | `code.plan` is read-only and comes first. No tool writes from a prompt alone. |
| A person approves every change | `code.apply` and `code.open_pr` never run. They create a pending approval. Only the signed-in user resolves it, and HomePilot's own code handles that reply before any model sees it. |
| What is approved is what runs | The approval points at the exact plan GitPilot returned, stored by HomePilot. Approving executes that plan. |
| Approvals are single-use and short-lived | One atomic claim per code; 30 minutes; scoped to the user who asked. |
| Least privilege, per user | Each user's own GitHub token, kept server-side, used only for that user's requests. |
| Changes are reviewable and reversible | Work lands on a branch; the default branch changes only through a pull request the user merges. |
| No secrets in the browser or in errors | The token is never returned by the API and is redacted from GitPilot error text. |
| Input is validated before it leaves | Repository and branch names are checked; the address goes through the outbound-URL guard. |
| Privacy mode is honoured | Under `private_local`, a GitPilot outside the user's own network is refused. |
| No loops | Requests carry `X-Gitpilot-Origin: homepilot`. |

The reason the model cannot approve: an approval is matched only when the
**user's whole message** is `approve CODE` or `deny CODE`. Text the model
writes, or an instruction hidden in a repository file, is never parsed as a
decision.

## What HomePilot calls

GitPilot's REST API:

| HomePilot | GitPilot |
|---|---|
| link check | `GET /api/health`, `POST /api/auth/validate`, `GET /api/auth/status` |
| `code.repos` | `GET /api/repos` |
| `code.plan` | `POST /api/chat/plan` |
| approved `code.apply` | `POST /api/chat/execute` with the stored plan |
| approved `code.open_pr` | `POST /api/repos/{owner}/{repo}/pulls` |

Linking GitPilot is not enough on its own: inside a project, `code.*` tools run
only when the project owner turns **GitPilot** on in the project's
Permissions (off by default). See [PROJECT_SECURITY.md](PROJECT_SECURITY.md).

GitPilot also publishes an MCP-style tool surface (`/mcp-server/mcp`, enabled
with `GITPILOT_EXPOSE_MCP_SERVER=true`) intended for HomePilot's Coder
persona. This connector does not use it yet, for two reasons found in that
branch: its `gitpilot.execute` tool reports itself as not implemented and
directs callers to the REST route, and its mutation tools require the same
token to equal both `GITPILOT_MCP_SERVER_TOKEN` and
`GITPILOT_MCP_SERVER_MUTATION_TOKEN`. When GitPilot's agentic runtime exposes
execution over MCP, only `connectors/gitpilot.py` needs to change.

## HomePilot API

All under `/v1/connectors/gitpilot`, for the signed-in user:

| Route | Purpose |
|---|---|
| `POST /` | Link (`endpoint`, `token`) |
| `GET /status` | Reachability, version, read-only, pending approvals |
| `PUT /settings` | `read_only` |
| `GET /repos?q=` | Repositories |
| `POST /plan` | Make a plan (read-only) |
| `POST /plans/{plan_id}/apply` | Create the approval request |
| `GET /approvals` | Pending approvals |
| `POST /approvals/{code}/approve` or `/deny` | The user's decision |

Agent tools, present only for a user who linked GitPilot: `code.repos`,
`code.plan`, `code.apply`, `code.open_pr`.

## Configuration

| Variable | Purpose |
|---|---|
| `GITPILOT_URL` | Optional default address offered when linking. |
| `HOMEPILOT_COMPUTE_BLOCK_PRIVATE` | On a hosted HomePilot, blocks private addresses; users then need a GitPilot reachable over the internet. |

## Verification

* `backend/tests/test_connector_gitpilot.py` — 15 tests, including a full agent
  conversation where the model's own "approve" does nothing and the user's does.
* HomePilot's HTTP API and the Settings panel were exercised against a
  **stand-in** that reproduces GitPilot's REST shapes.
* **Not verified against a running GitPilot.** Installing it in the build
  environment was not permitted, and no GitHub token was available. The
  request and response shapes were taken from GitPilot's source.

## Not included yet

* A dedicated coding workspace (file tree, diff view). Plans are shown as text.
* Streaming progress while GitPilot applies a plan.
* GitLab repositories (GitPilot supports them; this connector sends GitHub only).
* GitPilot's skills and sandbox terminal.
