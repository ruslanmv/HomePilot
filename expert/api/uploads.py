from fastapi import APIRouter, UploadFile, File
from expert.workspace.upload_manager import upload_manager
from expert.workspace.archive_registry import archive_registry

router = APIRouter()


@router.post("/uploads")
async def upload_archive(session_id: str, file: UploadFile = File(...)):
    uploaded = await upload_manager.save_upload(session_id, file)
    workspace = archive_registry.register_archive(session_id, uploaded)
    return {"session_id": session_id, "workspace_id": workspace["workspace_id"], "path": uploaded}
