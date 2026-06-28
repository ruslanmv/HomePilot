import * as SecureStore from 'expo-secure-store';

import type { TokenStorage } from '@homepilot/auth';

// Mobile adapter for the @homepilot/auth TokenStorage port: the API key lives in
// the OS keychain/keystore (not AsyncStorage), per platform best practice.
const API_KEY = 'homepilot_api_key';
const BASE_URL = 'homepilot_base_url';

export const secureTokenStorage: TokenStorage = {
  get: () => SecureStore.getItemAsync(API_KEY),
  set: async (token) => {
    if (token) await SecureStore.setItemAsync(API_KEY, token);
    else await SecureStore.deleteItemAsync(API_KEY);
  },
  clear: () => SecureStore.deleteItemAsync(API_KEY),
};

export async function getStoredBaseUrl(): Promise<string | null> {
  return SecureStore.getItemAsync(BASE_URL);
}

export async function setStoredBaseUrl(url: string): Promise<void> {
  await SecureStore.setItemAsync(BASE_URL, url);
}
