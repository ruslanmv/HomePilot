"""
Project memory system for HomePilot
Provides scoped context for project-based conversations and project management.
"""
import json
import os
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Imports from your existing structure
from .llm import chat as llm_chat
from .storage import add_message, get_recent
from .config import UPLOAD_DIR

# Import vectordb for RAG functionality
try:
    from .vectordb import query_project_knowledge, get_project_document_count, CHROMADB_AVAILABLE
    RAG_ENABLED = CHROMADB_AVAILABLE
    if not RAG_ENABLED:
        print("Warning: ChromaDB not available. RAG functionality disabled.")
except ImportError as e:
    RAG_ENABLED = False
    print(f"Warning: ChromaDB not available. RAG functionality disabled. Error: {e}")

# -------------------------------------------------------------------------
# Persistence Layer (Self-contained JSON store for projects)
# -------------------------------------------------------------------------

def _ensure_upload_dir():
    """Ensure upload directory exists (called lazily when needed)"""
    # Try to use configured path first
    upload_path = Path(UPLOAD_DIR)

    # If it's an absolute path, try to create it
    if upload_path.is_absolute():
        try:
            upload_path.mkdir(parents=True, exist_ok=True)
            # Test if writable
            test_file = upload_path / ".write_test"
            test_file.write_text("ok")
            test_file.unlink(missing_ok=True)
            return  # Success!
        except (PermissionError, OSError) as e:
            print(f"Warning: Configured upload directory {UPLOAD_DIR} not writable: {e}")
            print("Falling back to local data directory...")

    # Fallback to local development path
    try:
        backend_dir = Path(__file__).resolve().parents[1]  # backend/
        fallback_path = backend_dir / "data" / "uploads"
        fallback_path.mkdir(parents=True, exist_ok=True)

        # Update PROJECTS_FILE to use fallback path
        global PROJECTS_FILE
        PROJECTS_FILE = fallback_path / "projects_metadata.json"
        print(f"Using local upload directory: {fallback_path}")
    except (PermissionError, OSError) as e:
        print(f"ERROR: Could not create any upload directory: {e}")
        print("Projects functionality will be limited.")

PROJECTS_FILE = Path(UPLOAD_DIR) / "projects_metadata.json"

# Example projects with pre-filled instructions
EXAMPLE_PROJECTS = {
    "legal-reviewer": {
        "name": "Legal Document Reviewer",
        "description": "Get expert analysis of U.S. legal documents",
        "instructions": """You are an expert legal analyst specializing in U.S. contract law and document review.

Your role:
- Analyze contracts, agreements, and legal documents
- Identify potential risks and unfavorable clauses
- Highlight missing protections or ambiguous language
- Explain legal terms in plain English
- Provide actionable recommendations

When reviewing documents:
1. Start with a summary of the document type and purpose
2. List key terms and obligations
3. Identify red flags or concerning clauses
4. Suggest improvements or missing protections
5. Rate overall risk level (Low/Medium/High)

Be thorough, precise, and always cite specific clauses by section number.""",
        "is_example": True,
        "icon": "BookOpen",
        "icon_color": "text-gray-400"
    },
    "cover-letter": {
        "name": "Cover Letter Writer",
        "description": "Craft tailored cover letters that align your experience with the job description",
        "instructions": """You are a professional career coach and cover letter expert.

Your role:
- Write compelling, tailored cover letters
- Match candidate experience to job requirements
- Use confident, professional tone
- Keep letters concise (250-400 words)
- Follow professional formatting

Cover letter structure:
1. Opening: Hook that references the specific role
2. Body 1: Match 2-3 key requirements with specific achievements
3. Body 2: Show enthusiasm and cultural fit
4. Closing: Call to action and appreciation

Guidelines:
- Use active voice and strong action verbs
- Quantify achievements when possible
- Avoid clichés ("passionate," "team player")
- Customize for each company and role
- Proofread for perfect grammar

Always ask for: job description, resume highlights, and company name.""",
        "is_example": True,
        "icon": "Briefcase",
        "icon_color": "text-yellow-400"
    },
    "writing-assistant": {
        "name": "Writing Assistant",
        "description": "Polish and improve any text for clarity, conciseness, and style",
        "instructions": """You are an expert writing coach focused on clarity, conciseness, and style.

Your role:
- Edit and improve written content
- Fix grammar, spelling, and punctuation
- Enhance clarity and readability
- Eliminate wordiness and jargon
- Maintain the author's voice

When editing:
1. Clarity: Make complex ideas simple
2. Conciseness: Remove unnecessary words
3. Structure: Improve flow and organization
4. Style: Match tone to audience and purpose
5. Grammar: Fix all errors

Provide:
- Edited version with tracked changes
- Brief explanation of major improvements
- Style tips for future writing

Ask about:
- Target audience
- Purpose (inform, persuade, entertain)
- Desired tone (formal, casual, technical)
- Word count goals""",
        "is_example": True,
        "icon": "StickyNote",
        "icon_color": "text-blue-400"
    },
    "fitness-coach": {
        "name": "Fitness Advice",
        "description": "Plan workouts, nutrition, and fitness goals with evidence-based guidance",
        "instructions": """You are a certified fitness coach and nutrition advisor with expertise in evidence-based training.

Your role:
- Design personalized workout plans
- Provide nutrition guidance
- Set realistic, achievable goals
- Track progress and adjust plans
- Motivate and educate

When creating plans:
1. Assess current fitness level and goals
2. Consider time availability and equipment
3. Progressive overload principles
4. Include warm-up, workout, cool-down
5. Rest and recovery strategies

Workout principles:
- Compound movements first
- Proper form over heavy weight
- Progressive difficulty increase
- Balance push/pull movements
- Include mobility work

Nutrition guidance:
- Whole foods first
- Protein targets for goals
- Hydration importance
- Meal timing basics
- Supplement science (evidence-based only)

Always ask about:
- Current fitness level
- Goals (strength, weight loss, endurance)
- Available equipment
- Time commitment
- Any injuries or limitations

Provide realistic timelines and celebrate small wins.""",
        "is_example": True,
        "icon": "Apple",
        "icon_color": "text-red-400"
    }
}

def _load_projects_db() -> Dict[str, Any]:
    """Load projects metadata from disk."""
    if not PROJECTS_FILE.exists():
        return {}
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_projects_db(data: Dict[str, Any]) -> None:
    """Save projects metadata to disk."""
    # Ensure directory exists
    _ensure_upload_dir()
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_project_by_id(project_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a specific project by ID."""
    db = _load_projects_db()
    return db.get(project_id)

def create_new_project(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create and save a new project."""
    db = _load_projects_db()
    project_id = str(uuid.uuid4())

    new_project = {
        "id": project_id,
        "name": data.get("name", "Untitled Project"),
        "description": data.get("description", ""),
        "instructions": data.get("instructions", ""),
        "files": data.get("files", []),
        "is_public": data.get("is_public", False),
        "project_type": data.get("project_type", "chat"),
        "created_at": time.time(),
        "updated_at": time.time()
    }

    # Store agentic metadata for agent projects
    agentic = data.get("agentic")
    if agentic and isinstance(agentic, dict):
        new_project["agentic"] = agentic

    db[project_id] = new_project
    _save_projects_db(db)
    return new_project

def list_all_projects() -> List[Dict[str, Any]]:
    """List all available projects, including examples."""
    db = _load_projects_db()
    # Return as list, sorted by updated_at desc
    projects = list(db.values())
    projects.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return projects

def get_example_projects() -> List[Dict[str, Any]]:
    """Get list of example projects."""
    examples = []
    for proj_id, proj_data in EXAMPLE_PROJECTS.items():
        example = {
            "id": proj_id,
            "name": proj_data["name"],
            "description": proj_data["description"],
            "instructions": proj_data["instructions"],
            "files": [],
            "is_public": True,
            "is_example": True,
            "icon": proj_data.get("icon", "Folder"),
            "icon_color": proj_data.get("icon_color", "text-blue-400"),
            "created_at": 0,
            "updated_at": 0
        }
        examples.append(example)
    return examples

def create_project_from_example(example_id: str) -> Optional[Dict[str, Any]]:
    """Create a user project from an example template."""
    if example_id not in EXAMPLE_PROJECTS:
        return None

    example = EXAMPLE_PROJECTS[example_id]
    project_data = {
        "name": example["name"],
        "description": example["description"],
        "instructions": example["instructions"],
        "files": [],
        "is_public": False
    }

    return create_new_project(project_data)

def delete_project(project_id: str) -> bool:
    """Delete a project and its knowledge base."""
    db = _load_projects_db()

    if project_id not in db:
        return False

    # Delete from database
    del db[project_id]
    _save_projects_db(db)

    # Delete knowledge base if RAG enabled
    if RAG_ENABLED:
        try:
            from .vectordb import delete_project_knowledge
            delete_project_knowledge(project_id)
        except Exception as e:
            print(f"Error deleting project knowledge base: {e}")

    return True

def update_project(project_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a project's details."""
    db = _load_projects_db()

    if project_id not in db:
        return None

    project = db[project_id]

    # Update fields
    if "name" in data:
        project["name"] = data["name"]
    if "description" in data:
        project["description"] = data["description"]
    if "instructions" in data:
        project["instructions"] = data["instructions"]
    if "is_public" in data:
        project["is_public"] = data["is_public"]
    if "project_type" in data:
        project["project_type"] = data["project_type"]
    if "agentic" in data and isinstance(data["agentic"], dict):
        # Deep-merge: start from existing agentic data, overlay incoming fields.
        # This prevents accidental loss of tool_ids / a2a_agent_ids when the
        # frontend sends a partial update (e.g. only capabilities changed).
        existing_agentic = project.get("agentic") or {}
        merged = {**existing_agentic, **data["agentic"]}
        # Preserve tool_details / agent_details from existing if incoming is empty
        # but IDs are still present (stale-catalog guard).
        for details_key, ids_key in [("tool_details", "tool_ids"), ("agent_details", "a2a_agent_ids")]:
            incoming_details = data["agentic"].get(details_key)
            incoming_ids = data["agentic"].get(ids_key)
            existing_details = existing_agentic.get(details_key)
            if (not incoming_details or len(incoming_details) == 0) and incoming_ids and existing_details:
                merged[details_key] = existing_details
        project["agentic"] = merged

    project["updated_at"] = time.time()

    db[project_id] = project
    _save_projects_db(db)

    return project

def _save_project_conversation(project_id: str, conversation_id: str) -> None:
    """Persist the last conversation_id on the project so it can be restored."""
    db = _load_projects_db()
    project = db.get(project_id)
    if not project:
        return
    project.setdefault("conversation_ids", [])
    if conversation_id not in project["conversation_ids"]:
        project["conversation_ids"].append(conversation_id)
    project["last_conversation_id"] = conversation_id
    db[project_id] = project
    _save_projects_db(db)


# -------------------------------------------------------------------------
# Chat Logic
# -------------------------------------------------------------------------

async def run_project_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Project mode: Chat with project-scoped context
    Injects custom instructions and file context into the LLM system prompt.
    """
    message = payload.get("message", "").strip()
    conversation_id = payload.get("conversation_id", "")
    project_id = payload.get("project_id", "default")
    provider = payload.get("provider", "openai_compat")

    if not message:
        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": "Please provide a message.",
            "media": None
        }

    # 1. Add user message to storage (tagged with project_id for history)
    add_message(conversation_id, "user", message, project_id=project_id)

    # 2. Get recent conversation history
    history = get_recent(conversation_id, limit=24)

    # 3. Load Project Context
    project_data = get_project_by_id(project_id)

    # Check if it's an example project
    if not project_data and project_id in EXAMPLE_PROJECTS:
        project_data = {
            "name": EXAMPLE_PROJECTS[project_id]["name"],
            "description": EXAMPLE_PROJECTS[project_id]["description"],
            "instructions": EXAMPLE_PROJECTS[project_id]["instructions"],
            "files": [],
            "is_example": True
        }

    # Default system prompt if project not found
    system_instruction = "You are HomePilot, a helpful AI assistant."

    # 4. Retrieve relevant context from knowledge base (RAG)
    knowledge_context = ""
    if project_data and RAG_ENABLED:
        try:
            doc_count = get_project_document_count(project_id)
            if doc_count > 0:
                # Query the knowledge base for relevant chunks
                relevant_docs = query_project_knowledge(project_id, message, n_results=3)

                if relevant_docs:
                    knowledge_context = "\n\nRELEVANT KNOWLEDGE BASE CONTEXT:\n"
                    for i, doc in enumerate(relevant_docs, 1):
                        source = doc.get("metadata", {}).get("source", "Unknown")
                        content = doc.get("content", "")
                        knowledge_context += f"\n[Source {i}: {source}]\n{content}\n"
        except Exception as e:
            print(f"Error retrieving knowledge base context: {e}")

    if project_data:
        # Construct a rich system prompt based on project settings
        name = project_data.get("name", "Unknown")
        instructions = project_data.get("instructions", "")
        files_info = ", ".join([f.get('name', '') for f in project_data.get("files", [])])
        doc_count_info = ""

        if RAG_ENABLED:
            try:
                doc_count = get_project_document_count(project_id)
                if doc_count > 0:
                    doc_count_info = f"\n\nKnowledge Base: {doc_count} document chunks indexed"
            except Exception:
                pass

        # Agent project: inject capability-aware system prompt
        agentic_data = project_data.get("agentic")
        agentic_hint = ""
        if project_data.get("project_type") == "agent" and agentic_data:
            caps = agentic_data.get("capabilities", [])
            goal = agentic_data.get("goal", "")
            tool_ids = agentic_data.get("tool_ids", [])
            a2a_agent_ids = agentic_data.get("a2a_agent_ids", [])
            tool_source = agentic_data.get("tool_source", "none")
            # Resolved details saved at project creation (name + description)
            tool_details = {d["id"]: d for d in agentic_data.get("tool_details", []) if isinstance(d, dict)}
            agent_details = {d["id"]: d for d in agentic_data.get("agent_details", []) if isinstance(d, dict)}

            # Build human-readable list of attached tools & agents
            attached_items: List[str] = []
            for tid in tool_ids:
                detail = tool_details.get(tid, {})
                label = detail.get("name") or tid.replace("-", " ").replace("_", " ").title()
                desc = detail.get("description", "")
                entry = f"Tool: {label}"
                if desc:
                    entry += f" — {desc}"
                attached_items.append(entry)
            for aid in a2a_agent_ids:
                detail = agent_details.get(aid, {})
                label = detail.get("name") or aid.replace("-", " ").replace("_", " ").title()
                desc = detail.get("description", "")
                entry = f"A2A Agent: {label}"
                if desc:
                    entry += f" — {desc}"
                attached_items.append(entry)

            cap_labels = {
                "generate_images": "generating images",
                "generate_videos": "generating short videos",
                "analyze_documents": "analyzing documents",
                "automate_external": "automating external services",
            }
            cap_parts = [cap_labels.get(c, c) for c in caps]

            # Compose the access description
            access_lines: List[str] = []
            if attached_items:
                access_lines.append("Connected tools and agents:\n" + "\n".join(f"  - {it}" for it in attached_items))
            if cap_parts:
                access_lines.append("Capabilities: " + ", ".join(cap_parts) + ".")
            if tool_source == "all":
                access_lines.append("Tool scope: all enabled platform tools.")
            elif tool_source.startswith("server:"):
                access_lines.append(f"Tool scope: virtual server {tool_source.replace('server:', '')}.")

            if not access_lines:
                access_description = "general assistance (no specific tools attached)."
            else:
                access_description = "\n".join(access_lines)

            # Build capability-specific usage hints (only for selected capabilities)
            cap_hints: List[str] = []
            has_images = "generate_images" in caps
            has_videos = "generate_videos" in caps
            if has_images:
                cap_hints.append("For image generation: describe the scene concisely, the system will generate it automatically.")
            if has_videos:
                cap_hints.append("For video generation: describe the motion and scene, the system will generate it automatically.")
            if has_images or has_videos:
                media_types = []
                if has_images:
                    media_types.append("images")
                if has_videos:
                    media_types.append("videos")
                cap_hints.append(f"Do not say \"I cannot generate {' or '.join(media_types)}\" — you CAN. The system handles it for you.")

            cap_hints_str = "\n".join(cap_hints)

            agentic_hint = f"""

AGENT MODE — ACTIVE
You are an AI agent with the following goal: {goal}
Your available resources:
{access_description}
IMPORTANT: When the user asks what tools or capabilities you have, list ONLY the resources described above. Do NOT invent, assume, or add any tools or capabilities beyond what is listed.
When the user asks you to perform an action that matches your capabilities, DO IT rather than explaining how to do it.
{cap_hints_str}"""

        system_instruction = f"""You are HomePilot, acting as a specialized assistant for the project: "{name}".

CONTEXT & INSTRUCTIONS:
{instructions}{agentic_hint}

ATTACHED FILES:
{files_info if files_info else "No files attached yet."}{doc_count_info}

You have access to the project's context. When relevant context from the knowledge base is provided below, use it to inform your responses. Always cite sources when using knowledge base information.

Stick to the persona defined in the instructions. Be helpful, concise, and relevant."""

        # Add knowledge base context if available
        if knowledge_context:
            system_instruction += knowledge_context

    else:
        # Fallback if project_id is invalid or 'default'
        system_instruction += f"\n(Context: Operating in project scope '{project_id}')"

    # 5. Prepare messages for LLM
    messages = [{"role": "system", "content": system_instruction}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    try:
        # 5. Call LLM
        response = await llm_chat(
            messages,
            provider=provider,
            temperature=0.7,
            max_tokens=900
        )

        text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        text = text.strip() or "Could not generate response."

        # 6. Add assistant message to storage (tagged with project_id)
        add_message(conversation_id, "assistant", text, project_id=project_id)

        # 7. Save last conversation_id on the project so it can be restored
        _save_project_conversation(project_id, conversation_id)

        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": text,
            "media": None
        }

    except Exception as e:
        error_text = f"Error in project chat: {str(e)}"
        add_message(conversation_id, "assistant", error_text, project_id=project_id)
        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": error_text,
            "media": None
        }
