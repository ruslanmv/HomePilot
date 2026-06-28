// MB7 — single sign-in. Authenticates against OllaBridge Cloud's JSON login
// (POST /v1/auth/login → JWT) and stores the token via the shared link helper,
// so the same credential drives compute, devices, and voice. Replaces pasting a
// raw token; registration stays on the web for now.
import { DEFAULT_CLOUD_URL } from './client';
import { linkWithToken } from './pairing';
import { registerForPush } from './push';

interface LoginResponse {
  token: string;
  user_id: string;
  email: string;
}

export async function signIn(
  email: string,
  password: string,
  cloudUrl: string = DEFAULT_CLOUD_URL,
): Promise<{ email: string }> {
  const base = cloudUrl.trim().replace(/\/+$/, '');
  const res = await fetch(`${base}/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email.trim(), password }),
  });
  if (!res.ok) {
    throw new Error(res.status === 401 ? 'Invalid email or password' : `Sign-in failed (${res.status})`);
  }
  const data = (await res.json()) as LoginResponse;
  await linkWithToken(data.token, base);
  // Register for push now that we're authenticated (fire-and-forget).
  void registerForPush();
  return { email: data.email };
}
