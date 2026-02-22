# backend/app/vectordb_images.py
"""
Topology 4: Multimodal Knowledge RAG — Image Indexing Pipeline.

Additive module. Does NOT modify vectordb.py or any existing endpoints.

Converts images to searchable text using existing Ollama vision models,
then stores the text in the project's ChromaDB knowledge base via
the existing add_documents_to_project() function.

Pipeline:
  1. Receive image file path + project context
  2. Run analyze_image(mode="both") → caption + OCR text
  3. Chunk the combined text
  4. Store in ChromaDB with image metadata (source filename, type, etc.)

No new packages required — reuses:
  - multimodal.analyze_image (Ollama vision)
  - vectordb.add_documents_to_project (ChromaDB)
  - vectordb.chunk_text (text chunking)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import UPLOAD_DIR

# Supported image extensions for indexing
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def is_image_file(filename: str) -> bool:
    """Check if a filename has an image extension."""
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


async def index_image_to_knowledge(
    project_id: str,
    image_path: Path,
    original_filename: str,
    *,
    provider: str = "ollama",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    nsfw_mode: bool = False,
) -> Dict[str, Any]:
    """
    Process an image and add its content to the project's knowledge base.

    Steps:
      1. Run vision analysis (caption + OCR) on the image
      2. Combine results into indexable text
      3. Chunk and store in ChromaDB

    Args:
        project_id: Project identifier
        image_path: Path to the image file on disk
        original_filename: Original filename for metadata
        provider: Vision provider (default: ollama)
        base_url: Vision provider base URL
        model: Vision model name
        nsfw_mode: Allow unrestricted analysis

    Returns:
        Dict with ok, chunks_added, analysis summary, etc.
    """
    from .multimodal import analyze_image

    upload_path = Path(UPLOAD_DIR)

    # Step 1: Run vision analysis (caption + OCR)
    # Use the local file path as a /files/ URL for the multimodal module
    image_url = f"/files/{image_path.name}"

    try:
        result = await analyze_image(
            image_url=image_url,
            upload_path=upload_path,
            provider=provider,
            base_url=base_url,
            model=model,
            user_prompt=None,
            nsfw_mode=nsfw_mode,
            mode="both",
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"Vision analysis failed: {e}",
            "chunks_added": 0,
        }

    if not result.get("ok", False):
        return {
            "ok": False,
            "error": result.get("error", "Vision analysis returned no results"),
            "chunks_added": 0,
        }

    analysis_text = (result.get("analysis_text") or "").strip()
    if not analysis_text:
        return {
            "ok": False,
            "error": "Vision analysis returned empty text",
            "chunks_added": 0,
        }

    # Step 2: Build indexable document text
    doc_text = (
        f"[Image: {original_filename}]\n"
        f"Visual description and text content:\n\n"
        f"{analysis_text}"
    )

    # Step 3: Chunk and store in ChromaDB
    try:
        from .vectordb import add_documents_to_project, chunk_text, CHROMADB_AVAILABLE
    except ImportError:
        return {
            "ok": False,
            "error": "ChromaDB not available",
            "chunks_added": 0,
        }

    if not CHROMADB_AVAILABLE:
        return {
            "ok": False,
            "error": "ChromaDB not installed",
            "chunks_added": 0,
        }

    chunks = chunk_text(doc_text)
    if not chunks:
        return {
            "ok": False,
            "error": "No text chunks generated from analysis",
            "chunks_added": 0,
        }

    # Generate stable IDs based on image filename
    file_hash = hashlib.md5(original_filename.encode()).hexdigest()[:8]
    ids = [f"img_{file_hash}_{i}" for i in range(len(chunks))]

    metadatas = [{
        "source": original_filename,
        "source_type": "image",
        "chunk_index": i,
        "total_chunks": len(chunks),
        "vision_model": result.get("meta", {}).get("model", "unknown"),
    } for i in range(len(chunks))]

    chunks_added = add_documents_to_project(project_id, chunks, metadatas, ids)

    return {
        "ok": True,
        "chunks_added": chunks_added,
        "analysis_preview": analysis_text[:200] + ("..." if len(analysis_text) > 200 else ""),
        "source": original_filename,
        "source_type": "image",
    }


async def index_image_from_url(
    project_id: str,
    image_url: str,
    *,
    provider: str = "ollama",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    nsfw_mode: bool = False,
) -> Dict[str, Any]:
    """
    Index an image from a URL (local /files/ or remote) into the knowledge base.

    This is the version called by the agent's image.index tool —
    it works with any URL that analyze_image() can handle.
    """
    from .multimodal import analyze_image

    upload_path = Path(UPLOAD_DIR)

    # Derive a filename for metadata
    from urllib.parse import urlparse
    parsed = urlparse(image_url)
    filename = Path(parsed.path).name or "image"

    try:
        result = await analyze_image(
            image_url=image_url,
            upload_path=upload_path,
            provider=provider,
            base_url=base_url,
            model=model,
            user_prompt=None,
            nsfw_mode=nsfw_mode,
            mode="both",
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"Vision analysis failed: {e}",
            "chunks_added": 0,
        }

    if not result.get("ok", False):
        return {
            "ok": False,
            "error": result.get("error", "Vision analysis returned no results"),
            "chunks_added": 0,
        }

    analysis_text = (result.get("analysis_text") or "").strip()
    if not analysis_text:
        return {
            "ok": False,
            "error": "Vision analysis returned empty text",
            "chunks_added": 0,
        }

    doc_text = (
        f"[Image: {filename}]\n"
        f"Visual description and text content:\n\n"
        f"{analysis_text}"
    )

    try:
        from .vectordb import add_documents_to_project, chunk_text, CHROMADB_AVAILABLE
    except ImportError:
        return {"ok": False, "error": "ChromaDB not available", "chunks_added": 0}

    if not CHROMADB_AVAILABLE:
        return {"ok": False, "error": "ChromaDB not installed", "chunks_added": 0}

    chunks = chunk_text(doc_text)
    if not chunks:
        return {"ok": False, "error": "No text chunks generated", "chunks_added": 0}

    file_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
    ids = [f"img_{file_hash}_{i}" for i in range(len(chunks))]

    metadatas = [{
        "source": filename,
        "source_type": "image",
        "image_url": image_url,
        "chunk_index": i,
        "total_chunks": len(chunks),
        "vision_model": result.get("meta", {}).get("model", "unknown"),
    } for i in range(len(chunks))]

    chunks_added = add_documents_to_project(project_id, chunks, metadatas, ids)

    return {
        "ok": True,
        "chunks_added": chunks_added,
        "analysis_preview": analysis_text[:200] + ("..." if len(analysis_text) > 200 else ""),
        "source": filename,
        "source_type": "image",
        "image_url": image_url,
    }
