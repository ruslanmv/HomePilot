# Account Isolation — Imagine gallery fix

## What this branch fixes

After logging into a second account, the Imagine gallery showed empty
"ghost" thumbnail cards that referenced image assets belonging to the
*previous* user. Server-side ownership checks already rejected the
`/files/f_*` fetches (403/404) and the `DELETE /media/image` calls
(`forbidden_image_delete`), but the client kept rendering bordered
cards around the broken `<img>` tags because the gallery state was
cached in an un-scoped `localStorage` key.

### Root cause

`frontend/src/ui/Imagine.tsx` read and wrote `homepilot_imagine_items`
directly. The key was global (not namespaced per user) and was never
cleared on logout. When user B signed in, `ImagineView` hydrated with
user A's gallery, fetched assets with user B's token, got
403/404, and left the card container rendered with broken images.

## Fix overview

Two changes, both additive and feature-local:

1. **`frontend/src/ui/lib/userScopedStorage.ts` (new)** — a small
   registry-based module that gives every feature a way to namespace
   its localStorage keys per authenticated user. Modeled on the
   per-workspace state pattern used by ChatGPT and Claude Enterprise:

   - Feature modules call `registerUserScopedKey('my_feature_key')`
     once at module load.
   - `AuthGate` (or any login/logout orchestrator) calls
     `persistActiveStateForUser(prev.id)` before switching, then
     `restoreActiveStateForUser(next.id)`, and `clearActiveUiState()`
     on logout.
   - Feature code keeps reading/writing the un-suffixed base key; the
     scoping happens at identity boundaries, not at every call site.

2. **`frontend/src/ui/Imagine.tsx` (patched via
   `frontend/src/ui/Imagine.tsx.patch`)** — the gallery now:

   - Registers `homepilot_imagine_items` with the scoping registry.
   - Reads/writes via `imagineItemsKey()` which resolves to
     `homepilot_imagine_items:user:<uid>` for the active user, or
     an `:user:anon` bucket when no one is signed in.
   - Performs a one-time migration from the legacy global slot to
     the scoped slot so existing galleries are not lost on first
     deploy of this fix.
   - Fails closed on image load errors: when a gallery `<img>` fires
     `onError` (which is what happens when user B's token is rejected
     for user A's asset) the item is removed from the current view
     and persisted as removed, so the empty thumbnail card
     disappears immediately and never comes back.

## How to apply locally

From the repository root, on your working branch:

```bash
git apply frontend/src/ui/Imagine.tsx.patch
```

Then verify:

```bash
grep -n imagineItemsKey frontend/src/ui/Imagine.tsx
grep -n markImageBroken frontend/src/ui/Imagine.tsx
```

You should see six `imagineItemsKey()` call sites and one
`markImageBroken` wired into the gallery `<img onError>`.

## Recommended AuthGate integration

If you have local, unpushed edits in `AuthGate.tsx` that already
namespace some keys, replace those inline helpers with imports from
`./lib/userScopedStorage` so every registered key is handled in one
place:

```ts
import {
  persistActiveStateForUser,
  restoreActiveStateForUser,
  clearActiveUiState,
} from './lib/userScopedStorage'
```

- On login (`handleAuthenticated`): if switching from a previous user,
  call `persistActiveStateForUser(prev.id)` then
  `restoreActiveStateForUser(next.id)`.
- On logout: call `persistActiveStateForUser(user.id)` followed by
  `clearActiveUiState()` before removing the auth blob.
- Wrap `children` in `<React.Fragment key={user?.id ?? 'anon'}>` so
  the app subtree remounts on account change and drops in-memory
  state from the outgoing user.

## Industry alignment

This pattern matches the way production multi-tenant SaaS clients
handle account switching:

- **Authenticate every request** — server enforces ownership on
  `/files/f_*` and `DELETE /media/image`.
- **Authorize every sensitive action** — cross-account delete returns
  403 `forbidden_image_delete`.
- **Scope client state per identity** — localStorage keys namespaced
  via `userScopedStorage`.
- **Drop stale session data** — `clearActiveUiState()` on logout,
  `<Fragment key={user.id}>` remount on switch, fail-closed rendering
  on broken asset URLs.
- **Continuously test isolation** — backend already covers
  `test_media_image_delete_authz`; extend with a frontend unit test
  that asserts user B's `Imagine` mount does not surface user A's
  gallery items.
