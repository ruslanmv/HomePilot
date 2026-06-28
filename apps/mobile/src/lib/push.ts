// MB8 — register this device for push so the Cloud can notify when a generation
// is ready or the PC comes online. Best-effort: silently no-ops without
// permission or an EAS projectId, so it never blocks the app.
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { getHttp } from './client';

export async function registerForPush(): Promise<boolean> {
  try {
    const { status } = await Notifications.requestPermissionsAsync();
    if (status !== 'granted') return false;
    const resp = await Notifications.getExpoPushTokenAsync();
    const token = resp?.data;
    if (!token) return false;
    await getHttp().post('/v1/push/register', { token, platform: Platform.OS });
    return true;
  } catch {
    return false; // push is optional — never throw into the app
  }
}
