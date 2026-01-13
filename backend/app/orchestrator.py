import re
import uuid
from .storage import add_message, get_recent
from .llm import chat as llm_chat
from .prompts import BASE_SYSTEM, FUN_SYSTEM
from .comfy import run_workflow

IMAGE_RE = re.compile(r"\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b", re.I)
EDIT_RE  = re.compile(r"\b(edit|inpaint|replace|remove|change)\b", re.I)
ANIM_RE  = re.compile(r"\b(animate|make (a )?video|image\s*to\s*video)\b", re.I)
URL_RE   = re.compile(r"(https?://\S+)")

def orchestrate(user_text: str, conversation_id: str | None, fun_mode: bool = False):
cid = conversation_id or str(uuid.uuid4())
add_message(cid, "user", user_text)

```
# Detect URL
url_match = URL_RE.search(user_text)
image_url = url_match.group(1) if url_match else ""

# 1) Animate (if has image url + animate intent)
if image_url and ANIM_RE.search(user_text):
    # default motion/seconds placeholders are supported in workflow
    res = run_workflow("img2vid", {"image_url": image_url, "motion": "subtle cinematic camera drift", "seconds": 6})
    video_url = (res["videos"][0] if res["videos"] else None)
    text = "Here you go."
    add_message(cid, "assistant", text)
    return {"conversation_id": cid, "text": text, "media": {"video_url": video_url}}

# 2) Edit (if has image url + edit intent)
if image_url and EDIT_RE.search(user_text):
    instruction = user_text
    res = run_workflow("edit", {"image_url": image_url, "instruction": instruction})
    text = "Done."
    add_message(cid, "assistant", text)
    return {"conversation_id": cid, "text": text, "media": {"images": res["images"]}}

# 3) Generate image
if IMAGE_RE.search(user_text):
    res = run_workflow("txt2img", {"prompt": user_text})
    text = "Generated a few variations."
    add_message(cid, "assistant", text)
    return {"conversation_id": cid, "text": text, "media": {"images": res["images"]}}

# 4) Normal chat
history = get_recent(cid, limit=24)
system = BASE_SYSTEM + ("\n" + FUN_SYSTEM if fun_mode else "")
messages = [{"role": "system", "content": system}]
for role, content in history:
    messages.append({"role": role, "content": content})

out = llm_chat(messages, temperature=(0.9 if fun_mode else 0.7), max_tokens=900)
text = out["choices"][0]["message"]["content"]
add_message(cid, "assistant", text)
return {"conversation_id": cid, "text": text, "media": None}
```

