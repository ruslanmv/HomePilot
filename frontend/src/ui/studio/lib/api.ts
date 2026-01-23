/**
 * API helper for Creator Studio
 *
 * Provides a consistent way to make API calls using the connection
 * info (backendUrl + apiKey) stored in the studio store.
 */
import { useStudioStore } from "../stores/studioStore";

/**
 * Make a fetch request to the Studio backend with proper auth headers.
 *
 * @param path - The API path (e.g., "/studio/presets")
 * @param init - Optional RequestInit options
 * @returns The parsed JSON response (or text if not JSON)
 */
export async function studioFetch<T = unknown>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const { backendUrl, apiKey } = useStudioStore.getState();

  // Build full URL (use backendUrl if set, otherwise relative path)
  const url = backendUrl ? `${backendUrl}${path}` : path;

  // Build headers
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };

  // Add Content-Type for requests with body
  if (init?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  // Add auth header if API key is set
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }

  const res = await fetch(url, { ...init, headers });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `${res.status} ${res.statusText}${text ? ` - ${text}` : ""}`
    );
  }

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json() as Promise<T>;
  }

  return res.text() as unknown as T;
}

/**
 * Make a GET request to the Studio backend.
 */
export async function studioGet<T = unknown>(path: string): Promise<T> {
  return studioFetch<T>(path, { method: "GET" });
}

/**
 * Make a POST request to the Studio backend with JSON body.
 */
export async function studioPost<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  return studioFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Make a PATCH request to the Studio backend with JSON body.
 */
export async function studioPatch<T = unknown>(
  path: string,
  body?: unknown
): Promise<T> {
  return studioFetch<T>(path, {
    method: "PATCH",
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * Make a DELETE request to the Studio backend.
 */
export async function studioDelete<T = unknown>(path: string): Promise<T> {
  return studioFetch<T>(path, { method: "DELETE" });
}
