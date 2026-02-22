# Multi-User Sessions

HomePilot supports multiple user accounts on a single self-hosted instance. Each user gets their own isolated workspace.

## What's Scoped Per User

| Data | Scope |
| :--- | :--- |
| Conversations | Per user — users only see their own chat history |
| Profile | Per user — display name, avatar, email, preferences |
| Memory | Per user — long-term memory items are private |
| Secrets vault | Per user — API keys and credentials are isolated |
| Personas | Shared — all users can access installed personas |
| Settings | Per browser — stored in localStorage |

## Authentication Flow

1. **First boot** — no users exist, the app shows the **Create Account** screen
2. **Register** — pick a username and optional password (passwordless supported)
3. **Onboarding** — set your display name and preferences
4. **Login** — Bearer token stored in the browser; sessions persist until logout

Tokens are issued by the backend (`POST /v1/auth/login`) and validated on every request (`GET /v1/auth/me`). Logout invalidates the token server-side.

## Switching Accounts

Clicking **Log out** from the account menu smoothly transitions to the login screen (no page reload). The login screen shows:

- **Recent Accounts** — previously logged-in users for one-click re-login
- **Sign In** — log in with a different existing account
- **Create Account** — register a new user on the same instance

## API Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/v1/auth/register` | Create a new user |
| `POST` | `/v1/auth/login` | Authenticate and receive a token |
| `GET` | `/v1/auth/me` | Check current session status |
| `POST` | `/v1/auth/logout` | Invalidate the current token |
| `GET` | `/v1/user/profile` | Get per-user profile (Bearer) |
| `POST` | `/v1/user/profile` | Save per-user profile (Bearer) |

## Single-User Mode

If the backend has no auth routes (older versions) or only one passwordless user exists, HomePilot auto-logs in with zero friction — no login screen shown.
