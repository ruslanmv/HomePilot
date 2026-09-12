export type MediaPreferences = {
  cameraDeviceId: string;
  microphoneDeviceId: string;
  speakerDeviceId: string;
  echoCancellation: boolean;
  noiseSuppression: boolean;
  autoGainControl: boolean;
  mirrorCameraPreview: boolean;
};

export const MEDIA_PREFERENCES_STORAGE_KEY = 'homepilot_media_preferences_v1';
export const MEDIA_PREFERENCES_EVENT = 'homepilot:media-preferences-changed';

export const DEFAULT_MEDIA_PREFERENCES: MediaPreferences = {
  cameraDeviceId: '',
  microphoneDeviceId: '',
  speakerDeviceId: '',
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  mirrorCameraPreview: true,
};

function safeStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function sanitize(raw: unknown): MediaPreferences {
  const value = raw && typeof raw === 'object' ? raw as Partial<MediaPreferences> : {};
  return {
    cameraDeviceId: typeof value.cameraDeviceId === 'string' ? value.cameraDeviceId : '',
    microphoneDeviceId: typeof value.microphoneDeviceId === 'string' ? value.microphoneDeviceId : '',
    speakerDeviceId: typeof value.speakerDeviceId === 'string' ? value.speakerDeviceId : '',
    echoCancellation: typeof value.echoCancellation === 'boolean' ? value.echoCancellation : true,
    noiseSuppression: typeof value.noiseSuppression === 'boolean' ? value.noiseSuppression : true,
    autoGainControl: typeof value.autoGainControl === 'boolean' ? value.autoGainControl : true,
    mirrorCameraPreview: typeof value.mirrorCameraPreview === 'boolean' ? value.mirrorCameraPreview : true,
  };
}

export function getMediaPreferences(): MediaPreferences {
  const storage = safeStorage();
  if (!storage) return { ...DEFAULT_MEDIA_PREFERENCES };

  try {
    const saved = storage.getItem(MEDIA_PREFERENCES_STORAGE_KEY);
    return saved ? sanitize(JSON.parse(saved)) : { ...DEFAULT_MEDIA_PREFERENCES };
  } catch {
    return { ...DEFAULT_MEDIA_PREFERENCES };
  }
}

export function setMediaPreferences(next: MediaPreferences): MediaPreferences {
  const sanitized = sanitize(next);
  const storage = safeStorage();

  try {
    storage?.setItem(MEDIA_PREFERENCES_STORAGE_KEY, JSON.stringify(sanitized));
  } catch {
    // Storage can be unavailable in private/locked-down contexts. The caller
    // still receives the sanitized value so the current session can continue.
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(MEDIA_PREFERENCES_EVENT, { detail: sanitized }));
  }
  return sanitized;
}

export function subscribeMediaPreferences(listener: (preferences: MediaPreferences) => void): () => void {
  if (typeof window === 'undefined') return () => {};

  const onCustom = (event: Event) => {
    const detail = (event as CustomEvent<MediaPreferences>).detail;
    listener(detail ? sanitize(detail) : getMediaPreferences());
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === MEDIA_PREFERENCES_STORAGE_KEY) listener(getMediaPreferences());
  };

  window.addEventListener(MEDIA_PREFERENCES_EVENT, onCustom);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(MEDIA_PREFERENCES_EVENT, onCustom);
    window.removeEventListener('storage', onStorage);
  };
}

function supportedAudioConstraints(): MediaTrackSupportedConstraints {
  try {
    return navigator.mediaDevices?.getSupportedConstraints?.() ?? {};
  } catch {
    return {};
  }
}

export function buildAudioConstraints(
  preferences: MediaPreferences = getMediaPreferences(),
  options: { ignoreDeviceId?: boolean } = {},
): MediaTrackConstraints {
  const supported = supportedAudioConstraints();
  const constraints: MediaTrackConstraints = {};

  if (!options.ignoreDeviceId && preferences.microphoneDeviceId) {
    constraints.deviceId = { exact: preferences.microphoneDeviceId };
  }
  if (supported.echoCancellation !== false) {
    constraints.echoCancellation = preferences.echoCancellation;
  }
  if (supported.noiseSuppression !== false) {
    constraints.noiseSuppression = preferences.noiseSuppression;
  }
  if (supported.autoGainControl !== false) {
    constraints.autoGainControl = preferences.autoGainControl;
  }

  return constraints;
}

export function buildVideoConstraints(
  preferences: MediaPreferences = getMediaPreferences(),
  options: { ignoreDeviceId?: boolean } = {},
): MediaTrackConstraints {
  const constraints: MediaTrackConstraints = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 30, max: 30 },
  };

  if (!options.ignoreDeviceId && preferences.cameraDeviceId) {
    constraints.deviceId = { exact: preferences.cameraDeviceId };
  }
  return constraints;
}

export function isDeviceSelectionError(error: unknown): boolean {
  const name = error instanceof DOMException ? error.name : (error as { name?: string } | null)?.name;
  return name === 'OverconstrainedError' || name === 'NotFoundError' || name === 'DevicesNotFoundError';
}
