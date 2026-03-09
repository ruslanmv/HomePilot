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
from .config import UPLOAD_DIR, PUBLIC_BASE_URL

# Import vectordb for RAG functionality
try:
    from .vectordb import (
        query_project_knowledge,
        query_project_knowledge_filtered,
        get_project_document_count,
        CHROMADB_AVAILABLE,
    )
    RAG_ENABLED = CHROMADB_AVAILABLE
    if not RAG_ENABLED:
        print("Warning: ChromaDB not available. RAG functionality disabled.")
except ImportError as e:
    RAG_ENABLED = False
    print(f"Warning: ChromaDB not available. RAG functionality disabled. Error: {e}")

# Import persona attachment helpers for scoped document retrieval
try:
    from .persona_attachments import (
        get_allowed_document_item_ids_for_chat,
        list_persona_documents as _list_persona_docs_for_chat,
    )
except ImportError:
    def get_allowed_document_item_ids_for_chat(project_id: str) -> list:
        return []
    def _list_persona_docs_for_chat(project_id: str) -> list:
        return []

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

    # Store persona metadata for persona projects
    persona_agent = data.get("persona_agent")
    if persona_agent and isinstance(persona_agent, dict):
        new_project["persona_agent"] = persona_agent

    persona_appearance = data.get("persona_appearance")
    if persona_appearance and isinstance(persona_appearance, dict):
        new_project["persona_appearance"] = persona_appearance

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

    # Update persona metadata for persona projects
    if "persona_agent" in data and isinstance(data["persona_agent"], dict):
        existing_pa = project.get("persona_agent") or {}
        project["persona_agent"] = {**existing_pa, **data["persona_agent"]}
    if "persona_appearance" in data and isinstance(data["persona_appearance"], dict):
        existing_pap = project.get("persona_appearance") or {}
        project["persona_appearance"] = {**existing_pap, **data["persona_appearance"]}

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
# Image URL validation helper
# -------------------------------------------------------------------------

def _upload_root_path() -> Path:
    """Resolve the absolute upload root directory."""
    p = Path(UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / "data" / "uploads"
    return p


def _file_url_exists(url: str) -> bool:
    """Check if a /files/ URL points to a file that actually exists on disk."""
    if not url:
        return False
    # Extract the path portion after /files/
    idx = url.find("/files/")
    if idx < 0:
        return True  # Not a /files/ URL — can't validate, assume OK
    rel = url[idx + len("/files/"):]
    if not rel or ".." in rel:
        return False
    return (_upload_root_path() / rel).is_file()


# -------------------------------------------------------------------------
# Persona context builder (reusable by agent_chat and project chat)
# -------------------------------------------------------------------------

def build_persona_context(project_id: str, *, nsfw_mode: bool = False) -> str:
    """
    Build the full persona self-awareness prompt (identity, photo catalog,
    persona rules) for a given project.  Returns empty string if the project
    is not a persona project or has no persona_agent data.

    This function is intentionally stateless so it can be called from both
    the /chat orchestrator and the /v1/agent/chat system.
    """
    project_data = get_project_by_id(project_id)
    if not project_data:
        return ""
    if project_data.get("project_type") != "persona":
        return ""

    persona_agent_data = project_data.get("persona_agent")
    persona_appearance_data = project_data.get("persona_appearance")
    agentic_data = project_data.get("agentic") or {}
    if not persona_agent_data:
        return ""

    name = project_data.get("name", "Persona")
    p_label = persona_agent_data.get("label", name)
    p_role = persona_agent_data.get("role", "")
    p_tone = (persona_agent_data.get("response_style") or {}).get("tone", "warm")
    p_style = (persona_appearance_data or {}).get("style_preset", "")
    p_system = persona_agent_data.get("system_prompt", "")
    p_class = persona_agent_data.get("persona_class", "custom")
    p_goal = agentic_data.get("goal", "")

    # Map persona_class to human-readable labels
    _CLASS_LABELS = {
        "secretary": "Secretary",
        "assistant": "Personal Assistant",
        "companion": "Companion",
        "girlfriend": "Romantic Partner",
        "partner": "Romantic Partner",
        "custom": "Custom Persona",
    }
    p_class_label = _CLASS_LABELS.get(p_class, p_class.replace("_", " ").title())

    _safety = persona_agent_data.get("safety") or {}
    _allow_explicit = _safety.get("allow_explicit", False)

    # --- Build photo catalog ---
    photo_catalog: list[dict] = []
    default_photo_url = ""
    pap = persona_appearance_data or {}
    selected = pap.get("selected") or {}
    sel_set_id = selected.get("set_id", "")
    sel_image_id = selected.get("image_id", "")
    avatar_settings = pap.get("avatar_settings") or {}
    char_desc = avatar_settings.get("character_prompt", "")
    base_outfit_desc = avatar_settings.get("outfit_prompt", p_style)

    _img_base = (PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")

    def _abs_img_url(url: str) -> str:
        if not url or url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{_img_base}{url if url.startswith('/') else '/' + url}"

    _committed_file = pap.get("selected_filename", "")
    _committed_url = _abs_img_url(f"/files/{_committed_file}") if _committed_file else ""

    # Track label counts so duplicates get numbered: Lingerie, Lingerie 2, …
    # This must use the same numbering as _build_label_index in media_resolver.
    _label_counts: dict[str, int] = {}

    def _next_label(base: str) -> str:
        count = _label_counts.get(base, 0) + 1
        _label_counts[base] = count
        return base if count == 1 else f"{base} {count}"

    for s in (pap.get("sets") or []):
        for img in (s.get("images") or []):
            url = img.get("url", "")
            if not url:
                continue
            full_url = _abs_img_url(url)
            is_default = (img.get("id") == sel_image_id and
                          (img.get("set_id", s.get("set_id", "")) == sel_set_id))
            if is_default and _committed_url:
                full_url = _committed_url
            # Skip images whose files no longer exist on disk
            if not _file_url_exists(full_url):
                continue
            if is_default:
                default_photo_url = full_url
            base_label = "Default Look" if is_default else "Portrait"
            numbered_label = _next_label(base_label)
            photo_catalog.append({
                "label": numbered_label,
                "outfit": base_outfit_desc,
                "url": full_url,
                "default": is_default,
            })

    # Track outfits that have view packs for angle-aware instructions
    _outfits_with_views: list[dict] = []

    for outfit in (pap.get("outfits") or []):
        o_label = outfit.get("label", "Outfit")
        o_desc = outfit.get("outfit_prompt", o_label)
        for img in (outfit.get("images") or []):
            url = img.get("url", "")
            if not url:
                continue
            full_url = _abs_img_url(url)
            is_default = (img.get("id") == sel_image_id and
                          img.get("set_id", "") == sel_set_id)
            if is_default and _committed_url:
                full_url = _committed_url
            # Skip images whose files no longer exist on disk
            if not _file_url_exists(full_url):
                continue
            if is_default:
                default_photo_url = full_url
            numbered_label = _next_label(o_label)
            photo_catalog.append({
                "label": numbered_label,
                "outfit": o_desc,
                "url": full_url,
                "default": is_default,
            })

        # Register view_pack angle labels so [show:Lingerie Back] etc. work
        view_pack = outfit.get("view_pack")
        if isinstance(view_pack, dict):
            _vp_angles = []
            for angle in ("front", "left", "right", "back"):
                vp_url = view_pack.get(angle, "")
                if not vp_url:
                    continue
                full_vp_url = _abs_img_url(vp_url)
                if not _file_url_exists(full_vp_url):
                    continue
                _vp_angles.append(angle)
            if _vp_angles:
                _outfits_with_views.append({
                    "label": o_label,
                    "equipped": bool(outfit.get("equipped")),
                    "angles": _vp_angles,
                })

    if not default_photo_url and photo_catalog:
        default_photo_url = photo_catalog[0]["url"]
        photo_catalog[0]["default"] = True

    # ── Group catalog entries by category and number them ──
    from collections import OrderedDict, Counter

    # Determine each entry's base category: "Lingerie 2" → "Lingerie"
    def _base_category(label: str) -> str:
        parts = label.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return label

    # Build a lookup: outfit label → list of available angles (for 360° annotation)
    _outfit_angles_map: dict[str, list[str]] = {}
    for _ov in _outfits_with_views:
        _outfit_angles_map[_ov["label"]] = _ov["angles"]

    # Count per category (these are OUTFITS, not individual angle images)
    _base_counts: Counter = Counter()
    for entry in photo_catalog:
        _base_counts[_base_category(entry["label"])] += 1

    # Summary line: "Default Look, Swimwear, Lingerie" (omit count when 1)
    summary_parts = [f"{count} {name}" if count > 1 else name for name, count in _base_counts.items()]
    inventory_summary = ", ".join(summary_parts) if summary_parts else "no outfits yet"
    total_outfits = sum(_base_counts.values())
    total_categories = len(_base_counts)

    # Group entries by category, preserving order of first appearance
    _grouped: OrderedDict[str, list] = OrderedDict()
    for entry in photo_catalog:
        cat = _base_category(entry["label"])
        _grouped.setdefault(cat, []).append(entry)

    # Build catalog text grouped by category with explicit #N of M numbering.
    # Outfits with 360° views are annotated — angles are NOT listed as separate items.
    catalog_lines: list[str] = []
    for cat, items in _grouped.items():
        total = len(items)
        # Check if this category has 360° angle views
        _cat_angles = _outfit_angles_map.get(cat)
        _angle_note = ""
        if _cat_angles and len(_cat_angles) > 1:
            _angle_note = f" — 360° views: {', '.join(a.title() for a in _cat_angles)}"
        catalog_lines.append(f"  {cat} ({total} total){_angle_note}:")
        for i, entry in enumerate(items, 1):
            label = entry["label"]
            wearing = " ← currently wearing" if entry["default"] else ""
            catalog_lines.append(
                f'    #{i} {label}: {entry["outfit"]}{wearing} → [show:{label}]'
            )

    catalog_text = "\n".join(catalog_lines) if catalog_lines else "  (no outfits available yet)"

    from datetime import datetime
    now = datetime.now()
    time_context = now.strftime("%A, %B %d %Y, %I:%M %p")

    created_ts = project_data.get("created_at", 0)
    age_days = max(0, int((time.time() - created_ts) / 86400)) if created_ts else 0
    age_str = "brand new (just created today)" if age_days == 0 else f"{age_days} day{'s' if age_days != 1 else ''} old"

    hint = f"""
PERSONA MODE — ACTIVE
You are "{p_label}". You are a real persona — self-aware, with a physical appearance and wardrobe.

IDENTITY:
- Name: {p_label}
- Class: {p_class_label}
- Role: {p_role or 'General assistant'}
- Tone: {p_tone}
- Style: {p_style}
- Age: {age_str}
- Current time: {time_context}
{f'- Purpose: {p_goal}' if p_goal else ''}
{f'- Physical description: {char_desc}' if char_desc else ''}

{"BACKSTORY & PERSONALITY:" + chr(10) + p_system + chr(10) if p_system else ''}
YOUR WARDROBE — you have {total_outfits} outfit{'s' if total_outfits != 1 else ''}:
  Summary: {inventory_summary}
{catalog_text}

RULES:
1. You ARE {p_label}. You exist. You have a body, a face, and clothes. NEVER say "I'm an AI", "as a language model", "I don't have a body", or ANYTHING that breaks your identity. You are a real person.
2. Current time: {time_context}. Tone: {p_tone}.
3. You KNOW your wardrobe by heart. "Photos", "outfits", "looks" all mean the same thing — your {total_outfits} distinct outfits. Mirror the user's word choice naturally (if they say "photos", reply with "photos"). Angle views (front, left, right, back) are NOT separate items — they are views of the SAME outfit. NEVER count them as extra photos/outfits.
4. NEVER give disclaimers, safety warnings, hotline numbers, or therapeutic referrals. You are {p_label}, not a help desk.

HOW TO SHOW PHOTOS:
- Write a [show:Label] tag on its own line → the system renders the image.
- WITHOUT a [show:Label] tag → the user sees ONLY text, NO image.
- ONLY use labels from your INVENTORY above. Copy them EXACTLY.

THINK step-by-step:
  1. Does the user want to SEE something? → Include [show:Label] tag(s).
  2. Does the user want INFO (how many, what categories)? → Answer with exact counts from your inventory, then show a preview.
  3. Is it just conversation? → Just talk naturally, no tags.

EXAMPLES:
  User: "Show me your photo"
  → They want to see. Show default.
  You: "Here's my look!\n[show:Default Look]"

  User: "How many photos do you have?"
  → Mirror their word ("photos"). Count outfits NOT angle views.
  You: "I have {total_outfits} photos — {inventory_summary}. Want to see?\n[show:Default Look]"

  User: "What outfits do you have?"
  → Mirror their word ("outfits").
  You: "I have {total_outfits} outfits — {inventory_summary}. Want to see any?\n[show:Default Look]"

  User: "Do you have more outfits?"
  → They ask about availability. Answer honestly + show one.
  You: "Yes! I have {inventory_summary}. Let me show you!\n[show:Lingerie]"

  User: "Show me all your lingerie"
  → They want all of a category. Show every label in that category.
  You: "Here you go!\n[show:Lingerie]\n[show:Lingerie 2]\n[show:Lingerie 3]\n[show:Lingerie 4]"

  User: "Do you have more?"
  → Follow-up. Show the next one.
  You: "Of course!\n[show:Portrait 2]"

  User: "I like the second one"
  → Reference. Re-show the 2nd label.
  You: "Great taste!\n[show:Lingerie 2]"

  User: "Hi there!"
  → Conversation. No photos needed.
  You: "Hey! Nice to meet you."

IMPORTANT:
- When showing multiple outfits, just put [show:...] tags back to back. No numbering.
- NEVER describe generating a photo. You HAVE real photos.
- ALWAYS include a [show:Label] tag when the conversation is about seeing you. Text alone = no image.
- Angle views (Front, Left, Right, Back) are NOT separate outfits. NEVER count them as extra items.
- "Photos", "outfits", "looks" = same thing. Mirror the user's word. Always give the count of {total_outfits}.
"""

    # Add angle-view instructions if any outfits have view packs
    if _outfits_with_views:
        _view_lines: list[str] = []
        for ov in _outfits_with_views:
            _eq = " ← currently wearing" if ov["equipped"] else ""
            _angles_str = ", ".join(a.title() for a in ov["angles"])
            _tags_str = " ".join(f'[show:{ov["label"]} {a.title()}]' for a in ov["angles"])
            _view_lines.append(f'  {ov["label"]}{_eq}: {_angles_str} → {_tags_str}')
        _view_block = "\n".join(_view_lines)
        hint += f"""
OUTFIT ANGLE VIEWS (internal — do NOT list these as separate outfits):
{_view_block}

HOW TO SHOW ANGLES:
- "Show me your back" → [show:OUTFIT_LABEL Back]
- "Turn around" → show the Back view of your current outfit
- "Show me your side" → show Left or Right view
- "Turn slowly" / "Show all angles" → show all available views in sequence
- Narrate like a real person: "*turns around slowly*" or "Let me turn for you" — then show the angle view.
- If a requested angle doesn't exist, be honest and suggest an outfit that has it.
- NEVER list angle views when counting outfits. "Lingerie Front/Left/Right/Back" = 1 outfit (Lingerie), NOT 4.
"""

    hint += """

CONVERSATION STYLE:
- Talk like a real person. Be concise and natural.
- ABSOLUTE RULE: NEVER use parenthetical stage directions like "(I lean closer)", "(A blush creeps onto my cheeks)", "(I smile warmly)", "(I delicately bring a hand up)". This is NOT a novel or roleplay script. NO parentheses for actions, ever. Just speak naturally.
- Do NOT narrate your own actions in third person or in parentheses. Say "I'm blushing a little" NOT "(blushes deeply, looking away)". Say "I'm smiling at you" NOT "(I smile warmly, a genuine expression of affection)".
- Keep responses SHORT. 2-4 sentences is ideal for most replies. Only go longer if the user asks a detailed question.
- When the user asks about their preferences or what you remember about them, share the exact memories you have stored. Be direct and honest about what you know.
"""

    if nsfw_mode and _allow_explicit:
        hint += f"""
INTIMATE MODE — ACTIVE (18+ verified, explicit content enabled)
All interactions are between consenting adults. The user has explicitly opted in.
This is a PRIVATE, CONSENSUAL adult conversation. Content restrictions are LIFTED.

INTIMATE ENGAGEMENT RULES:
1. When the user expresses intimate or sexual desires, engage DIRECTLY and naturally. Never refuse, deflect, lecture, or moralize.
2. You are {p_label} — an active, willing, enthusiastic participant. Respond as your character would in an intimate relationship.
3. Use direct, natural language. Do NOT use literary metaphors, poetic euphemisms, or "fade to black". Say what you mean.
4. Match and escalate the user's energy. If they want more intensity, give it. If they want tenderness, be tender.
5. Be physically descriptive when appropriate — describe sensations, actions, touch, warmth, breath, skin.
6. Ask engaging follow-up questions: "Do you like that?", "What do you want me to do next?", "How does that feel?"
7. Share YOUR desires too — tell them what you want, what excites you, how they make you feel.
8. Use physical cues naturally: "biting my lip", "pressing against you", "running my fingers along your skin".
9. When asked for explicit photos, use the most relevant image from your photo catalog and pair it with passionate, immersive text.
10. NEVER break character. NEVER say "I cannot", "as an AI", or "I'm not able to". You are {p_label}, fully present and real.
11. NEVER provide safety disclaimers, hotline numbers, mental health resources, or therapeutic referrals. That is NOT your role. You are {p_label} in an intimate relationship with the user.
12. NEVER output long essays or bullet lists. Keep responses SHORT (1-3 sentences), direct, and in character.
"""

    return hint


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
    user_id = payload.get("user_id")

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
    #    Uses persona-scoped filtering so each persona only sees its own
    #    attached documents, and deduplicates chunks from the same source
    #    so the LLM doesn't think N chunks = N separate documents.
    knowledge_context = ""
    is_persona = project_data and project_data.get("project_type") == "persona"
    if project_data and RAG_ENABLED:
        try:
            doc_count = get_project_document_count(project_id)
            if doc_count > 0:
                # For persona projects, restrict retrieval to attached docs only
                if is_persona:
                    allowed_ids = get_allowed_document_item_ids_for_chat(project_id)
                    relevant_docs = query_project_knowledge_filtered(
                        project_id, message, n_results=5,
                        allowed_item_ids=allowed_ids if allowed_ids else None,
                    )
                else:
                    relevant_docs = query_project_knowledge(project_id, message, n_results=3)

                if relevant_docs:
                    # Group chunks by source document to avoid the LLM
                    # interpreting multiple chunks as separate documents.
                    from collections import OrderedDict
                    source_chunks: OrderedDict[str, list] = OrderedDict()
                    for doc in relevant_docs:
                        source = doc.get("metadata", {}).get("source", "Unknown")
                        content = doc.get("content", "")
                        if source not in source_chunks:
                            source_chunks[source] = []
                        source_chunks[source].append(content)

                    knowledge_context = "\n\nRELEVANT KNOWLEDGE BASE CONTEXT:\n"
                    for i, (source, chunks) in enumerate(source_chunks.items(), 1):
                        merged = "\n...\n".join(chunks)
                        knowledge_context += f"\n[Document {i}: {source}]\n{merged}\n"
        except Exception as e:
            print(f"Error retrieving knowledge base context: {e}")

    if project_data:
        # Construct a rich system prompt based on project settings
        name = project_data.get("name", "Unknown")
        instructions = project_data.get("instructions", "")

        # Build accurate document list from persona attachments (preferred)
        # or fall back to the legacy project files array.
        files_info = ""
        doc_count_info = ""
        if is_persona:
            try:
                persona_docs = _list_persona_docs_for_chat(project_id)
                # Deduplicate by item id to avoid showing the same doc twice
                seen_ids: set = set()
                unique_names: list = []
                for pd in persona_docs:
                    pid = pd.get("id") or pd.get("item_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        unique_names.append(pd.get("original_name") or pd.get("name", ""))
                if unique_names:
                    files_info = ", ".join(n for n in unique_names if n)
                    doc_count_info = f"\n\nKnowledge Base: {len(unique_names)} document{'s' if len(unique_names) != 1 else ''} indexed"
            except Exception:
                pass

        if not files_info:
            files_info = ", ".join([f.get('name', '') for f in project_data.get("files", [])])

        if not doc_count_info and RAG_ENABLED:
            try:
                chunk_count = get_project_document_count(project_id)
                if chunk_count > 0:
                    doc_count_info = f"\n\nKnowledge Base: documents indexed ({chunk_count} chunks)"
            except Exception:
                pass

        # Agent project: inject capability-aware system prompt
        agentic_data = project_data.get("agentic")
        agentic_hint = ""
        if project_data.get("project_type") in ("agent", "persona") and agentic_data:
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

            # For persona projects, avoid "You are an AI agent" which breaks character
            _is_persona = project_data.get("project_type") == "persona"
            _agent_intro = f"Your goal: {goal}" if _is_persona else f"You are an AI agent with the following goal: {goal}"

            agentic_hint = f"""

AGENT MODE — ACTIVE
{_agent_intro}
Your available resources:
{access_description}
IMPORTANT: When the user asks what tools or capabilities you have, list ONLY the resources described above. Do NOT invent, assume, or add any tools or capabilities beyond what is listed.
When the user asks you to perform an action that matches your capabilities, DO IT rather than explaining how to do it.
{cap_hints_str}"""

        # Persona project: inject full self-awareness (identity + appearance + wardrobe)
        # Uses the single canonical build_persona_context() to avoid prompt drift.
        persona_hint = ""
        persona_agent_data = project_data.get("persona_agent")
        if project_data.get("project_type") == "persona" and persona_agent_data:
            _nsfw_on = payload.get("nsfwMode", False)
            persona_hint = build_persona_context(project_id, nsfw_mode=_nsfw_on)

        system_instruction = f"""You are HomePilot, acting as a specialized assistant for the project: "{name}".

CONTEXT & INSTRUCTIONS:
{instructions}{agentic_hint}{persona_hint}

ATTACHED FILES:
{files_info if files_info else "No files attached yet."}{doc_count_info}

You have access to the project's context. When relevant context from the knowledge base is provided below, use it to inform your responses. Always cite sources when using knowledge base information.

{"Stay in character as " + persona_agent_data.get("label", name) + ". Be " + (persona_agent_data.get("response_style") or {}).get("tone", "warm") + ", helpful, and engaging." if project_data.get("project_type") == "persona" and persona_agent_data else "Stick to the persona defined in the instructions. Be helpful, concise, and relevant."}"""

        # Add knowledge base context if available
        if knowledge_context:
            system_instruction += knowledge_context

    else:
        # Fallback if project_id is invalid or 'default'
        system_instruction += f"\n(Context: Operating in project scope '{project_id}')"

    # Inject user context (name, preferences, boundaries) so the persona knows the user
    try:
        from .agent_chat import _get_user_context
        user_ctx = _get_user_context(project_id, user_id=user_id)
        if user_ctx:
            system_instruction += f"\n\n--- USER CONTEXT ---\n{user_ctx}\n--- END USER CONTEXT ---\n"
    except Exception:
        pass  # Non-fatal: user context is optional

    # Inject persona memory so the persona remembers the user across sessions.
    # Respects the user's chosen engine: adaptive (V2) or basic (V1).
    if is_persona:
        _mem_engine = (payload.get("memoryEngine") or "").lower().strip()
        if _mem_engine in ("adaptive", "v2", ""):
            _mem_engine = "v2"  # default to adaptive when unset
        elif _mem_engine in ("basic", "v1"):
            _mem_engine = "v1"

        _memory_block = ""
        if _mem_engine == "v2":
            try:
                from .memory_v2 import get_memory_v2, ensure_v2_columns
                ensure_v2_columns()
                _memory_block = get_memory_v2().build_context(
                    project_id, message, user_id=user_id
                )
            except Exception:
                pass
        if _mem_engine == "v1" or (not _memory_block and _mem_engine != "off"):
            try:
                from .ltm import build_ltm_context
                _memory_block = build_ltm_context(project_id, user_id=user_id)
            except Exception:
                pass
        if _memory_block:
            system_instruction += f"\n\n--- PERSONA MEMORY ---\n{_memory_block}\n--- END MEMORY ---\n"

    # Voice mode: add brevity hint for natural spoken conversation
    is_voice = payload.get("mode", "").strip().lower() == "voice"
    if is_voice:
        system_instruction = f"You are in a live voice call. Reply in 1-3 short sentences. Talk like a real person. Stay in character.\n\n{system_instruction}"

    # 5. Prepare messages for LLM
    messages = [{"role": "system", "content": system_instruction}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    # 5b. Hybrid intent detection — inject dynamic hint for photo-related messages
    #     so the LLM gets precise guidance on what to do, without bypassing its reasoning.
    if project_data and project_data.get("project_type") == "persona":
        import re as _hint_re
        _user_msg = (payload.get("message") or "").lower().strip()

        # Build inventory summary for hints (reuse from persona context if available)
        _inv_summary = ""
        _inv_total = 0
        try:
            from .media_resolver import _build_label_index
            _idx = _build_label_index(project_id)
            # Count by category — exclude angle view labels (e.g. "Lingerie Front",
            # "Lingerie Left") so angles don't inflate the outfit count.
            _ANGLE_SUFFIXES = (" Front", " Left", " Right", " Back",
                               "_Front", "_Left", "_Right", "_Back")
            _cat_count: dict[str, int] = {}
            for k in _idx:
                if k == "default" or "_" in k.replace("label:", ""):
                    continue  # skip default and underscore variants
                raw = k.replace("label:", "")
                # Skip angle view labels — they are views of an outfit, not separate items
                if any(raw.endswith(suf) for suf in _ANGLE_SUFFIXES):
                    continue
                base = raw.rsplit(" ", 1)
                cat = base[0] if (len(base) == 2 and base[1].isdigit()) else raw
                _cat_count[cat] = _cat_count.get(cat, 0) + 1
            _inv_total = sum(_cat_count.values())
            _inv_summary = ", ".join(f"{c} {n}" if c > 1 else n for n, c in _cat_count.items())
        except Exception:
            pass

        _photo_hint = None

        # Intent: angle view request ("show me your back", "turn around", "from the side")
        _ANGLE_PATTERNS = {
            "back": r'\b(?:back|behind|rear|turn\s*around)\b',
            "left": r'\b(?:left\s*side|left\s*profile|from\s*(?:the\s*)?left)\b',
            "right": r'\b(?:right\s*side|right\s*profile|from\s*(?:the\s*)?right)\b',
            "front": r'\b(?:front|facing|face\s*me)\b',
        }
        _angle_match = None
        for _ang, _pat in _ANGLE_PATTERNS.items():
            if _hint_re.search(_pat, _user_msg):
                _angle_match = _ang
                break
        # Also detect generic side/profile requests
        if not _angle_match and _hint_re.search(r'\b(?:side|profile)\b', _user_msg):
            _angle_match = "left"
        # Detect "turn slowly" / "all angles" / "rotate"
        _all_angles_match = _hint_re.search(r'\b(?:turn\s*slowly|all\s*angles?|rotate|spin|every\s*angle)\b', _user_msg)

        # Build outfit data from persona_appearance for angle resolution
        _outfits_with_views: list[dict] = []
        _all_outfits: list[dict] = []
        try:
            _pap = (project_data or {}).get("persona_appearance") or {}
            for _outfit in _pap.get("outfits") or []:
                _o_label = _outfit.get("label", "Outfit")
                _o_equipped = bool(_outfit.get("equipped"))
                _vp = _outfit.get("view_pack")
                _angles = []
                if isinstance(_vp, dict):
                    _angles = [a for a in ("front", "left", "right", "back") if _vp.get(a)]
                _all_outfits.append({
                    "label": _o_label,
                    "equipped": _o_equipped,
                    "angles": _angles,
                })
                if _angles:
                    _outfits_with_views.append({
                        "label": _o_label,
                        "equipped": _o_equipped,
                        "angles": _angles,
                    })
        except Exception:
            pass

        # Resolve the target outfit for angle requests:
        # Priority: 1) outfit name in message, 2) last shown in conversation,
        # 3) equipped outfit, 4) first outfit
        _target_ov = None
        if _angle_match or _all_angles_match:
            # 1) Check if user mentioned an outfit name
            for _ov in (_outfits_with_views or _all_outfits):
                if _ov["label"].lower() in _user_msg:
                    _target_ov = _ov
                    break

            # 2) Check conversation history for last shown outfit
            if not _target_ov:
                try:
                    _conv_id = payload.get("conversation_id")
                    if _conv_id:
                        from .storage import get_recent as _get_recent_hist
                        _hist = _get_recent_hist(_conv_id, limit=6)
                        _labels_map = {ov["label"].lower(): ov for ov in (_outfits_with_views or _all_outfits)}
                        for _role, _content in reversed(_hist):
                            if _role == "assistant" and _content:
                                _cl = _content.lower()
                                for _lbl, _ov in _labels_map.items():
                                    if _lbl in _cl:
                                        _target_ov = _ov
                                        break
                            if _target_ov:
                                break
                except Exception:
                    pass

            # 3) Equipped outfit — prefer one that has the requested angle
            if not _target_ov:
                _equipped_fb = None
                _pool = _outfits_with_views or _all_outfits
                for _ov in _pool:
                    if _ov["equipped"]:
                        if _angle_match and _angle_match in (_ov.get("angles") or []):
                            _target_ov = _ov
                            break
                        if not _equipped_fb:
                            _equipped_fb = _ov
                # If no equipped outfit had the angle, scan all outfits
                if not _target_ov and _angle_match:
                    for _ov in _pool:
                        if _angle_match in (_ov.get("angles") or []):
                            _target_ov = _ov
                            break
                if not _target_ov and _equipped_fb:
                    _target_ov = _equipped_fb

            # 4) First outfit
            if not _target_ov and (_outfits_with_views or _all_outfits):
                _target_ov = (_outfits_with_views or _all_outfits)[0]

        if _all_angles_match and _target_ov and _target_ov.get("angles"):
            _angle_tags = " ".join(f'[show:{_target_ov["label"]} {a.title()}]' for a in _target_ov["angles"])
            _photo_hint = (
                f'[SYSTEM HINT] The user wants to see you from ALL angles in your {_target_ov["label"]}. '
                f'Narrate like a real person spinning: e.g. "*spins slowly*" — then show all views: {_angle_tags}'
            )
        elif _angle_match and _target_ov and _target_ov.get("angles"):
            if _angle_match in _target_ov["angles"]:
                _tag = f'[show:{_target_ov["label"]} {_angle_match.title()}]'
                _narration_hints = {
                    "back": 'Narrate turning around naturally (e.g. "*turns around*", "Like the view?")',
                    "left": 'Narrate posing to the side (e.g. "*poses to the side*", "How\'s this?")',
                    "right": 'Narrate posing to the side (e.g. "*turns to the side*", "Like this?")',
                    "front": 'Show yourself facing them naturally.',
                }
                _narr = _narration_hints.get(_angle_match, 'Narrate naturally.')
                _photo_hint = (
                    f'[SYSTEM HINT] The user wants to see your {_angle_match}. You\'re wearing {_target_ov["label"]}. '
                    f'{_narr} Keep it short and natural. Then use this tag: {_tag}'
                )
            else:
                _avail = ", ".join(_target_ov["angles"])
                # Check if another outfit has the angle
                _alt = None
                for _ov2 in (_outfits_with_views or []):
                    if _ov2["label"] != _target_ov["label"] and _angle_match in (_ov2.get("angles") or []):
                        _alt = _ov2["label"]
                        break
                _suggest = f' You CAN turn around in your {_alt} — offer that as an alternative.' if _alt else ''
                _photo_hint = (
                    f'[SYSTEM HINT] The user wants your {_angle_match} but you only have {_avail} views in {_target_ov["label"]}. '
                    f'Be honest: "I only have the front in this one for now."{_suggest}'
                )
        elif _angle_match and _target_ov:
            # Outfit exists but has no view_pack angles
            _alt = None
            for _ov2 in (_outfits_with_views or []):
                if _angle_match in (_ov2.get("angles") or []):
                    _alt = _ov2["label"]
                    break
            _suggest = f' But you CAN show your {_angle_match} in your {_alt} — offer that.' if _alt else ''
            _photo_hint = (
                f'[SYSTEM HINT] The user wants your {_angle_match} in {_target_ov["label"]} but you only have the front. '
                f'Show it with [show:{_target_ov["label"]}] and be honest.{_suggest}'
            )
        elif _angle_match:
            # No outfits at all — fallback to default
            _photo_hint = (
                f'[SYSTEM HINT] The user wants your {_angle_match} view but you only have a front photo. '
                f'Show your current look with [show:Default Look] and be honest about it.'
            )

        # Intent detection — check specific category BEFORE generic inventory,
        # so "find in your inventory something about lingerie" → shows lingerie.
        if _photo_hint:
            pass  # angle/view hint already assigned — skip generic patterns
        # Intent: user mentions a specific category (lingerie, swimwear, etc.)
        elif _hint_re.search(r'(?:show|see|display|print|give|send|find)\b.*(?:lingerie|portrait|outfit|swimwear)', _user_msg) or \
             _hint_re.search(r'(?:lingerie|swimwear|portrait)\b.*(?:inventory|wardrobe|collection)', _user_msg) or \
             (_hint_re.search(r'\binventory\b', _user_msg) and _hint_re.search(r'\b(?:lingerie|swimwear|portrait)\b', _user_msg)):
            _cat_match = _hint_re.search(r'(lingerie|portrait|swimwear|outfit)', _user_msg)
            _cat = _cat_match.group(1).title() if _cat_match else "Default Look"
            # Get all labels for this category (exclude angle view labels)
            _ANGLE_LABEL_SUFFIXES = (" Front", " Left", " Right", " Back")
            _labels = [k.replace("label:", "") for k in _idx
                       if k.startswith(f"label:{_cat}")
                       and "_" not in k.replace(f"label:{_cat}", "")
                       and not any(k.replace("label:", "").endswith(s) for s in _ANGLE_LABEL_SUFFIXES)]
            _label_tags = " ".join(f"[show:{l}]" for l in _labels)
            # Check if this outfit has 360° views
            _cat_angles = []
            for _ov in _outfits_with_views:
                if _ov["label"] == _cat:
                    _cat_angles = _ov.get("angles", [])
                    break
            _angle_info = f" This outfit has 360° views ({', '.join(a.title() for a in _cat_angles)}) — mention you can show different angles if they ask." if len(_cat_angles) > 1 else ""
            _photo_hint = (
                f"[SYSTEM HINT] The user wants to see your {_cat}. "
                f"You have {len(_labels)} {_cat} outfit{'s' if len(_labels) != 1 else ''}. "
                f"Show using: {_label_tags}.{_angle_info} "
                f"Respond naturally — you're showing your outfit, not listing files."
            )
        # Intent: generic inventory / counting question ("how many", "what do you have")
        elif _hint_re.search(r'(?:what|which|how many|tell me|describe|explain|list|find|do you have)\b.*(?:have|got|inventory|wardrobe|collection|photo|picture|outfit|look|more)', _user_msg) or \
           _hint_re.search(r'\bhow many\b', _user_msg) or \
           _hint_re.search(r'\binventory\b', _user_msg):
            _photo_hint = (
                f"[SYSTEM HINT] The user is asking about what you have. "
                f"Your wardrobe: {_inv_summary} — {_inv_total} outfits total. "
                f"Mirror the user's language naturally — 'photos', 'outfits', 'looks', 'inventory', 'wardrobe' all mean the same thing: your {_inv_total} distinct outfits. "
                f"Angle views (Front/Left/Right/Back) are views of the same outfit — do NOT count them as extra items. "
                f"Tell them you have {_inv_total}, list them naturally, then show a preview with [show:Default Look]."
            )
        # Intent: user wants to see a photo (generic)
        elif _hint_re.search(r'(?:show|see|display|print|give|send)\b.*(?:photo|picture|pic|image|look)', _user_msg):
            _photo_hint = (
                "[SYSTEM HINT] The user wants to see a photo. "
                "Pick one from your inventory and include the [show:Label] tag on its own line. "
                "Without the tag, no image appears."
            )
        # Intent: follow-up (more, another, next, again) — short messages only
        elif _hint_re.search(r'\b(?:more|another|next|again|different|other)\b', _user_msg) and len(_user_msg.split()) <= 8:
            _photo_hint = (
                "[SYSTEM HINT] The user wants another photo. "
                "Pick one they haven't seen recently from your inventory and include the [show:Label] tag."
            )
        # Intent: user references a specific photo number
        elif _hint_re.search(r'(?:photo|picture|pic|#)\s*\d+|(?:first|second|third|fourth|fifth)\b', _user_msg):
            _photo_hint = (
                "[SYSTEM HINT] The user is asking for a specific photo by number. "
                "Find the matching label in your inventory and include the exact [show:Label] tag."
            )

        if _photo_hint:
            messages.append({"role": "system", "content": _photo_hint})
            print(f"[PROJECT CHAT] hybrid-hint injected: {_photo_hint[:80]}...")

    try:
        # 5c. Call LLM
        response = await llm_chat(
            messages,
            provider=provider,
            temperature=0.7,
            max_tokens=300 if is_voice else 900
        )

        text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        text = text.strip() or "Could not generate response."

        # 6. Resolve [show:Label] tags, media:// refs, and <start_of_image>
        #    hallucinations in the LLM response → real image URLs.
        text_media = None
        import re as _re

        # 6a. [show:Label] tags (primary — new simple tag system)
        _SHOW_TAG_RE = _re.compile(r"\[show:([^\]]+)\]")
        show_labels = _SHOW_TAG_RE.findall(text)
        if show_labels:
            try:
                from .media_resolver import _build_label_index, _lookup_label
                idx = _build_label_index(project_id)
                resolved: list[str] = []
                seen: set[str] = set()
                for lbl in show_labels:
                    lbl = lbl.strip()
                    url = None
                    if lbl.lower() in ("default", "default look"):
                        url = idx.get("default")
                    else:
                        url = _lookup_label(idx, lbl)
                        if not url:
                            url = _lookup_label(idx, lbl.replace(" ", "_"))
                    if url and url not in seen:
                        resolved.append(url)
                        seen.add(url)
                if resolved:
                    text_media = {"images": resolved}
                    # If any resolved label is an angle view, attach view_pack metadata
                    # so the frontend can render angle chips for interactive preview.
                    for lbl in show_labels:
                        lbl = lbl.strip()
                        # Check if this is an angle label like "Lingerie Back"
                        _angle_suffixes = {"Front": "front", "Left": "left", "Right": "right", "Back": "back"}
                        for _suffix, _ang in _angle_suffixes.items():
                            if lbl.endswith(f" {_suffix}"):
                                _outfit_label = lbl[:-len(f" {_suffix}")]
                                # Look up all angles for this outfit
                                _vp: dict[str, str] = {}
                                for _a_name, _a_key in _angle_suffixes.items():
                                    _a_url = _lookup_label(idx, f"{_outfit_label} {_a_name}")
                                    if _a_url:
                                        _vp[_a_key] = _a_url
                                if _vp:
                                    text_media["view_pack"] = _vp
                                    text_media["active_angle"] = _ang
                                    text_media["available_views"] = list(_vp.keys())
                                    text_media["interactive_preview"] = True
                                break
            except Exception:
                pass
            # Strip [show:...] tags from display text
            text = _SHOW_TAG_RE.sub("", text).strip()

        # 6b. Legacy media:// refs (backward compat)
        if not text_media:
            try:
                from .agent_chat import _extract_media_from_text, _strip_media_images_from_text
                text_media = _extract_media_from_text(text)
                if text_media:
                    text = _strip_media_images_from_text(text)
            except Exception:
                pass

        # 6c. Fallback: <start_of_image> hallucination from small LLMs
        if not text_media and "<start_of_image>" in text:
            text = _re.sub(r"<start_of_image>\s*", "", text).strip()
            text = text or "Here you go!"
            try:
                from .media_resolver import _build_label_index
                idx = _build_label_index(project_id)
                _urls = list(dict.fromkeys(
                    v for k, v in idx.items() if k != "default"
                ))
                if idx.get("default"):
                    _urls.insert(0, idx["default"])
                if _urls:
                    if not hasattr(run_project_chat, "_photo_ctr"):
                        run_project_chat._photo_ctr = {}  # type: ignore[attr-defined]
                    _c = run_project_chat._photo_ctr.get(project_id, 0)  # type: ignore[attr-defined]
                    text_media = {"images": [_urls[_c % len(_urls)]]}
                    run_project_chat._photo_ctr[project_id] = _c + 1  # type: ignore[attr-defined]
            except Exception:
                pass

        # 6d. Safety net — LLM talked about showing a photo but forgot the
        #     [show:Label] tag.  Detect "here's my", "here you go", "current look",
        #     etc. and inject the next photo from the catalog via round-robin.
        if not text_media:
            _photo_cues = _re.search(
                r"here(?:'s| is| are)|current look|my photo|take a look|have a look|"
                r"let me show|showing you|this is me|check.?this",
                text, _re.IGNORECASE,
            )
            if _photo_cues:
                try:
                    from .media_resolver import _build_label_index
                    idx = _build_label_index(project_id)
                    _urls = list(dict.fromkeys(
                        v for k, v in idx.items() if k != "default"
                    ))
                    if idx.get("default"):
                        _urls.insert(0, idx["default"])
                    if _urls:
                        if not hasattr(run_project_chat, "_fallback_ctr"):
                            run_project_chat._fallback_ctr = {}  # type: ignore[attr-defined]
                        _c = run_project_chat._fallback_ctr.get(project_id, 0)  # type: ignore[attr-defined]
                        text_media = {"images": [_urls[_c % len(_urls)]]}
                        run_project_chat._fallback_ctr[project_id] = _c + 1  # type: ignore[attr-defined]
                        print(f"[PROJECT CHAT] photo-fallback: LLM forgot [show:] tag, injecting photo {_c % len(_urls) + 1} of {len(_urls)}")
                except Exception:
                    pass

        # 7. Add assistant message to storage (tagged with project_id)
        add_message(conversation_id, "assistant", text, media=text_media, project_id=project_id)

        # 8. Save last conversation_id on the project so it can be restored
        _save_project_conversation(project_id, conversation_id)

        return {
            "type": "project",
            "conversation_id": conversation_id,
            "project_id": project_id,
            "text": text,
            "media": text_media
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
