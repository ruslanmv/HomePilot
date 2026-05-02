from pathlib import Path


class FileHandles:
    def ensure_dir(self, path: str) -> Path:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        return p
