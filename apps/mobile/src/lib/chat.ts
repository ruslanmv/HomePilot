// MB1 — mobile chat. Reuses the shared api-client to call the OpenAI-compatible
// chat endpoint the configured backend exposes (the HomePilot backend directly,
// or the OllaBridge Cloud relay). Non-streaming MVP; a streaming variant
// (react-native-sse over POST) is a drop-in follow-up that keeps this signature.
import { getHttp } from './client';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface ChatCompletion {
  choices?: { message?: { content?: string } }[];
}

export const DEFAULT_MODEL = 'default';

/** Send the running conversation, return the assistant's reply text. */
export async function sendChat(
  messages: ChatMessage[],
  model: string = DEFAULT_MODEL,
): Promise<string> {
  const res = await getHttp().post<ChatCompletion>('/v1/chat/completions', {
    model,
    messages,
    stream: false,
  });
  return (res.choices?.[0]?.message?.content ?? '').trim();
}
