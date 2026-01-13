from fastapi import FastAPI, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import uuid
from .config import UPLOAD_DIR, CORS_ORIGINS
from .auth import require_api_key
from .storage import init_db
from .orchestrator import orchestrate

app = FastAPI(title="HomePilot Orchestrator", version="2.0.0")

app.add_middleware(
CORSMiddleware,
allow_origins=CORS_ORIGINS or ["http://localhost:3000"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

class ChatIn(BaseModel):
message: str
conversation_id: str | None = None
fun_mode: bool = False

@app.on_event("startup")
def _startup():
os.makedirs(UPLOAD_DIR, exist_ok=True)
init_db()

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

@app.get("/health")
def health():
return {"ok": True}

@app.post("/chat", dependencies=[Depends(require_api_key)])
def chat(inp: ChatIn):
return orchestrate(inp.message, inp.conversation_id, inp.fun_mode)

@app.post("/upload", dependencies=[Depends(require_api_key)])
def upload(file: UploadFile = File(...)):
# Save upload and return a URL the frontend can pass to /chat edit/animate
ext = os.path.splitext(file.filename or "")[1].lower()[:10]
name = f"{uuid.uuid4().hex}{ext or '.png'}"
path = os.path.join(UPLOAD_DIR, name)
with open(path, "wb") as f:
f.write(file.file.read())
return {"url": f"[http://localhost:8000/files/{name}"}](http://localhost:8000/files/{name}%22})
