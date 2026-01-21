"""
Vector database module for HomePilot using ChromaDB
Provides RAG (Retrieval Augmented Generation) capabilities for project knowledge bases
"""
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    chromadb = None
    Settings = None
    print("Warning: chromadb package not installed. Install with: pip install chromadb")

from .config import UPLOAD_DIR

# Export for use in other modules
__all__ = ['CHROMADB_AVAILABLE', 'get_chroma_client', 'query_project_knowledge', 'get_project_document_count', 'process_and_add_file']

# ChromaDB persistent storage location
CHROMA_DB_PATH = Path(UPLOAD_DIR) / "chroma_db"

# Initialize ChromaDB client
def get_chroma_client():
    """Get or create ChromaDB client with persistent storage"""
    if not CHROMADB_AVAILABLE:
        raise ImportError("ChromaDB is not installed. Install with: pip install chromadb")

    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(CHROMA_DB_PATH),
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True
        )
    )
    return client

def get_or_create_collection(project_id: str):
    """Get or create a collection for a specific project"""
    client = get_chroma_client()

    # Collection name must be alphanumeric + underscores
    collection_name = f"project_{hashlib.md5(project_id.encode()).hexdigest()[:16]}"

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"project_id": project_id}
    )

    return collection

def add_documents_to_project(
    project_id: str,
    documents: List[str],
    metadatas: Optional[List[Dict[str, Any]]] = None,
    ids: Optional[List[str]] = None
) -> int:
    """
    Add documents to a project's knowledge base

    Args:
        project_id: Project identifier
        documents: List of document texts
        metadatas: Optional metadata for each document
        ids: Optional IDs for each document (auto-generated if not provided)

    Returns:
        Number of documents added
    """
    if not documents:
        return 0

    collection = get_or_create_collection(project_id)

    # Generate IDs if not provided
    if ids is None:
        ids = [hashlib.md5(doc.encode()).hexdigest() for doc in documents]

    # Generate metadata if not provided
    if metadatas is None:
        metadatas = [{"source": "uploaded_file"} for _ in documents]

    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )

    return len(documents)

def query_project_knowledge(
    project_id: str,
    query: str,
    n_results: int = 3
) -> List[Dict[str, Any]]:
    """
    Query a project's knowledge base for relevant context

    Args:
        project_id: Project identifier
        query: Query text
        n_results: Number of results to return

    Returns:
        List of relevant document chunks with metadata
    """
    try:
        collection = get_or_create_collection(project_id)

        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )

        # Format results
        formatted_results = []
        if results and results['documents'] and len(results['documents']) > 0:
            documents = results['documents'][0]
            metadatas = results['metadatas'][0] if results['metadatas'] else [{}] * len(documents)
            distances = results['distances'][0] if results['distances'] else [0.0] * len(documents)

            for doc, meta, dist in zip(documents, metadatas, distances):
                formatted_results.append({
                    "content": doc,
                    "metadata": meta,
                    "similarity": 1.0 - dist  # Convert distance to similarity
                })

        return formatted_results

    except Exception as e:
        print(f"Error querying project knowledge: {e}")
        return []

def delete_project_knowledge(project_id: str) -> bool:
    """
    Delete all knowledge base data for a project

    Args:
        project_id: Project identifier

    Returns:
        True if successful
    """
    try:
        client = get_chroma_client()
        collection_name = f"project_{hashlib.md5(project_id.encode()).hexdigest()[:16]}"
        client.delete_collection(name=collection_name)
        return True
    except Exception as e:
        print(f"Error deleting project knowledge: {e}")
        return False

def get_project_document_count(project_id: str) -> int:
    """
    Get the number of documents in a project's knowledge base

    Args:
        project_id: Project identifier

    Returns:
        Number of documents
    """
    try:
        collection = get_or_create_collection(project_id)
        return collection.count()
    except Exception:
        return 0

# Text extraction utilities

def extract_text_from_file(file_path: Path) -> str:
    """
    Extract text from various file formats

    Args:
        file_path: Path to file

    Returns:
        Extracted text content
    """
    ext = file_path.suffix.lower()

    try:
        if ext == '.txt' or ext == '.md':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()

        elif ext == '.pdf':
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    return text
            except ImportError:
                return f"[PDF file: {file_path.name} - PyPDF2 not installed for text extraction]"

        else:
            return f"[Unsupported file type: {ext}]"

    except Exception as e:
        return f"[Error extracting text from {file_path.name}: {str(e)}]"

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """
    Split text into overlapping chunks for better retrieval

    Args:
        text: Text to chunk
        chunk_size: Size of each chunk in characters
        overlap: Overlap between chunks

    Returns:
        List of text chunks
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            # Look for period, question mark, or exclamation
            for i in range(end, start + chunk_size - 100, -1):
                if text[i] in '.!?\n':
                    end = i + 1
                    break

        chunks.append(text[start:end].strip())
        start = end - overlap

    return chunks

def process_and_add_file(project_id: str, file_path: Path) -> int:
    """
    Process a file and add it to the project's knowledge base

    Args:
        project_id: Project identifier
        file_path: Path to file

    Returns:
        Number of chunks added
    """
    # Extract text
    text = extract_text_from_file(file_path)

    if not text or text.startswith("["):
        return 0

    # Chunk text
    chunks = chunk_text(text)

    if not chunks:
        return 0

    # Generate metadata
    metadatas = [{
        "source": file_path.name,
        "chunk_index": i,
        "total_chunks": len(chunks)
    } for i in range(len(chunks))]

    # Generate IDs
    ids = [
        f"{hashlib.md5(file_path.name.encode()).hexdigest()[:8]}_{i}"
        for i in range(len(chunks))
    ]

    # Add to collection
    return add_documents_to_project(project_id, chunks, metadatas, ids)
