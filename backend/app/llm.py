import requests
from .config import LLM_BASE_URL, LLM_MODEL, TOOL_TIMEOUT_S

def chat(messages, temperature=0.7, max_tokens=800):
payload = {
"model": LLM_MODEL,
"messages": messages,
"temperature": temperature,
"max_tokens": max_tokens
}
r = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, timeout=TOOL_TIMEOUT_S)
r.raise_for_status()
return r.json()
