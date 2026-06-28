import EventSource from 'react-native-sse';

import type { EventTransport } from '@homepilot/compute-client';
import type { JobEvent } from '@homepilot/types';

import { secureTokenStorage } from './storage';

// EventTransport adapter for React Native (which has no native EventSource).
// Streams the cloud's /v1/jobs/{id}/events SSE and attaches the same auth as the
// HTTP client — both Authorization: Bearer (Cloud) and X-API-Key (HomePilot) —
// so the stream authenticates against either backend. Fulfils the
// @homepilot/compute-client EventTransport port, so the screens use
// compute.subscribeToJobEvents(...) unchanged.
export const sseEventTransport: EventTransport = {
  subscribe(url: string, onEvent: (event: JobEvent) => void): () => void {
    let es: EventSource | null = null;
    let closed = false;

    // Token read is async; resolve it, then open the stream (unless cancelled).
    void (async () => {
      const key = await secureTokenStorage.get();
      if (closed) return;
      es = new EventSource(
        url,
        key ? { headers: { Authorization: `Bearer ${key}`, 'X-API-Key': key } } : undefined,
      );
      es.addEventListener('message', (event) => {
        const data = (event as { data?: string | null }).data;
        if (!data) return;
        try {
          onEvent(JSON.parse(data) as JobEvent);
        } catch {
          /* ignore a malformed frame */
        }
      });
    })();

    return () => {
      closed = true;
      es?.removeAllEventListeners?.();
      es?.close();
    };
  },
};
