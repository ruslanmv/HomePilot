// MB3a — push-to-talk capture. Records a short clip with expo-av and returns it
// base64-encoded for the voice WS (the server transcribes it). HIGH_QUALITY
// yields .m4a (AAC), which OpenAI-compatible STT endpoints accept.
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system';

export interface AudioClip {
  b64: string;
  format: string;
}

export async function ensureMicPermission(): Promise<boolean> {
  const { granted } = await Audio.requestPermissionsAsync();
  return granted;
}

export async function startRecording(): Promise<Audio.Recording> {
  await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
  const { recording } = await Audio.Recording.createAsync(
    Audio.RecordingOptionsPresets.HIGH_QUALITY,
  );
  return recording;
}

export async function stopRecording(recording: Audio.Recording): Promise<AudioClip | null> {
  await recording.stopAndUnloadAsync();
  await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
  const uri = recording.getURI();
  if (!uri) return null;
  const b64 = await FileSystem.readAsStringAsync(uri, {
    encoding: FileSystem.EncodingType.Base64,
  });
  return { b64, format: uri.split('.').pop() || 'm4a' };
}
