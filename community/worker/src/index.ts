/**
 * HomePilot Community Persona Gallery — Cloudflare Worker
 *
 * Serves persona registry, previews, cards, and packages from R2
 * with proper caching, CORS, and stable versioned endpoints.
 *
 * Routes:
 *   GET /registry.json         → persona catalog (short cache)
 *   GET /v/<id>/<version>      → preview image (immutable cache)
 *   GET /c/<id>/<version>      → card JSON (immutable cache)
 *   GET /p/<id>/<version>      → .hpersona package (immutable cache)
 *   GET /health                → service health check
 */

interface Env {
  PERSONA_BUCKET: R2Bucket;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders() });
    }

    // Only allow GET
    if (request.method !== "GET") {
      return json({ error: "method not allowed" }, 405);
    }

    // Health check
    if (path === "/health") {
      return json({ status: "ok", service: "homepilot-persona-gallery" });
    }

    // 1) Registry — the single source of truth
    if (path === "/registry.json") {
      const obj = await env.PERSONA_BUCKET.get("registry/registry.json");
      if (!obj) return json({ error: "registry not found" }, 404);

      return new Response(obj.body, {
        headers: {
          ...corsHeaders(),
          "content-type": "application/json; charset=utf-8",
          // Short cache: registry changes when personas are added/updated
          "cache-control":
            "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
        },
      });
    }

    // 2) Preview image: /v/<persona_id>/<version>
    const vMatch = path.match(/^\/v\/([a-z0-9_-]+)\/([a-z0-9._-]+)$/i);
    if (vMatch) {
      const [, personaId, version] = vMatch;
      const key = `previews/${personaId}/${version}/preview.webp`;
      return r2File(env, key, "image/webp", 3600);
    }

    // 3) Card JSON: /c/<persona_id>/<version>
    const cMatch = path.match(/^\/c\/([a-z0-9_-]+)\/([a-z0-9._-]+)$/i);
    if (cMatch) {
      const [, personaId, version] = cMatch;
      const key = `previews/${personaId}/${version}/card.json`;
      return r2File(env, key, "application/json; charset=utf-8", 3600);
    }

    // 4) Package download: /p/<persona_id>/<version>
    const pMatch = path.match(/^\/p\/([a-z0-9_-]+)\/([a-z0-9._-]+)$/i);
    if (pMatch) {
      const [, personaId, version] = pMatch;
      const key = `packages/${personaId}/${version}/persona.hpersona`;
      return r2File(env, key, "application/octet-stream", 86400);
    }

    return json({ error: "not found" }, 404);
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function corsHeaders(): Record<string, string> {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type",
  };
}

async function r2File(
  env: Env,
  key: string,
  contentType: string,
  maxAge: number,
): Promise<Response> {
  const obj = await env.PERSONA_BUCKET.get(key);
  if (!obj) return json({ error: "not found", key }, 404);

  return new Response(obj.body, {
    headers: {
      ...corsHeaders(),
      "content-type": contentType,
      // Versioned paths are immutable — cache aggressively
      "cache-control": `public, max-age=${maxAge}, s-maxage=${maxAge * 7}, immutable`,
    },
  });
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      ...corsHeaders(),
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
