// @homepilot/api-client — base HTTP client for the HomePilot backend and
// OllaBridge Cloud.
//
// Platform-pure: the auth token and the fetch implementation are *injected*
// (ports), so the same client runs unchanged on web (browser fetch +
// localStorage), desktop (Electron), and mobile (RN fetch + SecureStore). This
// is the ports-&-adapters boundary that keeps the shared packages free of any
// platform API.

export type FetchImpl = typeof fetch;

export interface TokenProvider {
  getToken(): string | null | Promise<string | null>;
}

export interface ClientOptions {
  baseUrl: string;
  tokenProvider?: TokenProvider;
  fetchImpl?: FetchImpl;
  /**
   * Maps a token to the auth header(s) to send. Defaults to
   * `Authorization: Bearer <token>`. HomePilot's backend uses
   * `{ "X-API-Key": token }`; OllaBridge Cloud uses the Bearer default.
   */
  authHeader?: (token: string) => Record<string, string>;
}

export interface ApiClient {
  readonly baseUrl: string;
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  put<T>(path: string, body?: unknown): Promise<T>;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function createClient(opts: ClientOptions): ApiClient {
  const doFetch: FetchImpl = opts.fetchImpl ?? fetch;
  const baseUrl = opts.baseUrl.replace(/\/+$/, "");

  async function headers(): Promise<Record<string, string>> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    const token = await opts.tokenProvider?.getToken();
    if (token) {
      const auth = opts.authHeader
        ? opts.authHeader(token)
        : { Authorization: `Bearer ${token}` };
      Object.assign(h, auth);
    }
    return h;
  }

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await doFetch(`${baseUrl}${path}`, {
      method,
      headers: await headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new ApiError(res.status, await safeText(res));
    return (await res.json()) as T;
  }

  return {
    baseUrl,
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body),
    put: (path, body) => request("PUT", path, body),
  };
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return res.statusText;
  }
}
