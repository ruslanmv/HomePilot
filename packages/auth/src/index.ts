// @homepilot/auth — token/session handling + device pairing.
//
// Token persistence is a PORT (TokenStorage) implemented per app: web
// localStorage, desktop Electron safeStorage, mobile expo-secure-store
// (Keychain/Keystore). The package itself never touches a platform API.

import type { ApiClient } from "@homepilot/api-client";
import { ENDPOINTS } from "@homepilot/config";

export interface TokenStorage {
  get(): string | null | Promise<string | null>;
  set(token: string | null): void | Promise<void>;
  clear(): void | Promise<void>;
}

/** Adapts a TokenStorage into the TokenProvider shape api-client expects. */
export function tokenProviderFromStorage(storage: TokenStorage) {
  return { getToken: async () => await storage.get() };
}

export interface PairingStart {
  userCode: string;
  deviceCode: string;
  verificationUrl: string;
  expiresIn: number;
}

export interface Auth {
  getToken(): Promise<string | null>;
  setToken(token: string | null): Promise<void>;
  signOut(): Promise<void>;
  startPairing(): Promise<PairingStart>;
  pollPairing(deviceCode: string): Promise<{ status: string }>;
}

export function createAuth(api: ApiClient, storage: TokenStorage): Auth {
  return {
    getToken: async () => await storage.get(),
    setToken: async (token) => {
      await storage.set(token);
    },
    signOut: async () => {
      await storage.clear();
    },
    startPairing: () => api.post<PairingStart>(ENDPOINTS.pairStart),
    pollPairing: (deviceCode) =>
      api.post<{ status: string }>(ENDPOINTS.pairPoll, { device_code: deviceCode }),
  };
}
