from pathlib import Path
from expert.workspace.file_handles import FileHandles

UPLOAD_ROOT = Path(".uploads")


class UploadManager:
    def __init__(self):
        self.files = FileHandles()
        self.files.ensure_dir(str(UPLOAD_ROOT))

    async def save_upload(self, session_id: str, upload_file) -> str:
        session_dir = self.files.ensure_dir(str(UPLOAD_ROOT / session_id))
        target = session_dir / upload_file.filename
        content = await upload_file.read()
        target.write_bytes(content)
        return str(target)


upload_manager = UploadManager()
