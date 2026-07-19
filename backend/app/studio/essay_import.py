"""
Essay ingestion for the essay-to-video pipeline (Batch 0).

Turns a ruslanmv.com essay - pasted markdown, a rendered-page URL, or a raw
Jekyll markdown URL - into a structured EssaySource, then segments it into
scene beats whose narration is the essay's OWN sentences, verbatim.

Design contract (docs/design/essay-to-video/BATCH-0-script-ingestion.md):
  - Segmentation is deterministic, so narration can always be verified by
    substring match against the source. The LLM is only asked for
    shot planning (image prompts + scene_kind refinement), never for prose.
  - Either ingestion path (URL or markdown) produces the same EssaySource,
    so nothing downstream cares which one ran.
  - No new dependencies: stdlib parsing + httpx (already a backend dep).

Env:
  ESSAY_IMPORT_SOURCE=url|repo   (default "url"; "repo" tries raw markdown
                                  first when the URL points at a git host)
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from .models import SceneKind, SCENE_KIND_TO_RENDERER


# ============================================================================
# Data model
# ============================================================================

class EssaySection(BaseModel):
    heading: str
    body: str                       # the essay's own words, verbatim (markdown stripped)
    is_thesis_line: bool = False    # bolded/blockquote lines the essay itself calls out


class EssaySource(BaseModel):
    title: str
    subtitle: str = ""
    author: str = "Ruslan Magana Vsevolodovna"
    sections: List[EssaySection] = Field(default_factory=list)
    existing_audio_url: Optional[str] = None
    existing_audio_duration_sec: Optional[float] = None
    source_links: List[str] = Field(default_factory=list)   # for the CTA scene


# Negative-prompt addendum for the "Technical / Editorial" visual style:
# keep diffusion output away from the generic-AI-video look.
TECHNICAL_EDITORIAL_NEGATIVE = (
    "photorealistic human faces, stock footage, stock photo, corporate clipart, "
    "motivational poster, visual clutter, busy composition, lens flare, "
    "text, letters, words, captions, watermark, logo"
)

TECHNICAL_EDITORIAL_STYLE_PREFIX = (
    "technical editorial style, dark minimal background, "
    "cyan-blue-violet accent gradient, clean geometric abstract shapes, "
    "calm documentary atmosphere, high contrast, uncluttered"
)


# ============================================================================
# Markdown ingestion
# ============================================================================

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_FENCE_RE = re.compile(r"^(```|~~~)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_AUDIO_URL_RE = re.compile(r"https?://\S+\.(?:mp3|m4a|wav|ogg)\b", re.IGNORECASE)


def _strip_inline_markdown(text: str) -> str:
    """Reduce inline markdown to plain narratable text, keeping the words."""
    text = _MD_IMAGE_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.strip()


def _parse_front_matter(md: str) -> Tuple[dict, str]:
    """Extract Jekyll front matter (title/subtitle/audio) without a YAML dep."""
    m = _FRONT_MATTER_RE.match(md)
    if not m:
        return {}, md
    fm: dict = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w[\w-]*):\s*(.+?)\s*$", line)
        if kv:
            fm[kv.group(1).lower()] = kv.group(2).strip("'\"")
    return fm, md[m.end():]


def parse_markdown(md: str, fallback_title: str = "") -> EssaySource:
    """Parse essay markdown (Jekyll post or plain) into an EssaySource."""
    front_matter, body_md = _parse_front_matter(md)

    title = front_matter.get("title", "") or fallback_title
    subtitle = front_matter.get("subtitle", "") or front_matter.get("description", "")
    author = front_matter.get("author", "") or "Ruslan Magana Vsevolodovna"
    audio_url = front_matter.get("audio", "") or front_matter.get("audio_url", "") or None

    sections: List[EssaySection] = []
    links: List[str] = []
    current_heading = ""
    current_lines: List[str] = []
    quote_lines: List[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current_lines
        body = _strip_inline_markdown("\n".join(current_lines))
        # Single-space the body so scene narration is an exact substring of it
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            sections.append(EssaySection(heading=current_heading or title, body=body))
        current_lines = []

    def add_thesis(text: str) -> None:
        flush()  # keep document order: prose so far, then the callout
        sections.append(EssaySection(
            heading=current_heading or title, body=text, is_thesis_line=True,
        ))

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            add_thesis(" ".join(quote_lines))
            quote_lines = []

    for raw_line in body_md.splitlines():
        if _FENCE_RE.match(raw_line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # code blocks are not narratable prose

        for url in _AUDIO_URL_RE.findall(raw_line):
            audio_url = audio_url or raw_line[raw_line.find("http"):].split()[0].rstrip(")\"'")
        links.extend(url for _, url in _MD_LINK_RE.findall(raw_line))

        heading = _HEADING_RE.match(raw_line)
        if heading:
            flush_quote()
            if not title and heading.group(1) == "#":
                title = _strip_inline_markdown(heading.group(2))
                continue
            flush()
            current_heading = _strip_inline_markdown(heading.group(2))
            continue

        stripped = raw_line.strip()
        if stripped.startswith(">"):
            quote = _strip_inline_markdown(stripped.lstrip("> "))
            if quote:
                quote_lines.append(quote)
            continue
        flush_quote()
        # A line that is entirely bold reads as a thesis callout
        bold_only = re.fullmatch(r"\*\*([^*]+)\*\*", stripped)
        if bold_only:
            add_thesis(bold_only.group(1).strip())
            continue
        current_lines.append(raw_line)

    flush_quote()
    flush()

    audio_match = _AUDIO_URL_RE.search(audio_url or "")
    return EssaySource(
        title=title or fallback_title or "Untitled Essay",
        subtitle=subtitle,
        author=author,
        sections=sections,
        existing_audio_url=audio_match.group(0) if audio_match else (audio_url or None),
        source_links=list(dict.fromkeys(links)),
    )


# ============================================================================
# HTML (rendered page) ingestion
# ============================================================================

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript"}
_HEADING_TAGS = {"h2", "h3"}


class _EssayHTMLParser(HTMLParser):
    """Tolerant extraction of title / section headings / prose / audio / links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.subtitle = ""
        self.audio_url: Optional[str] = None
        self.links: List[str] = []
        self.sections: List[Tuple[str, List[str], bool]] = []  # heading, paragraphs, thesis
        self._heading = ""
        self._paragraphs: List[str] = []
        self._text: List[str] = []
        self._capture: Optional[str] = None  # h1|h2|h3|p|li|blockquote|title
        self._skip_depth = 0
        self._blockquote_depth = 0

    def _flush_section(self) -> None:
        if self._paragraphs:
            self.sections.append((self._heading, self._paragraphs, False))
        self._paragraphs = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in ("audio", "source") and attrs_d.get("src") and not self.audio_url:
            self.audio_url = attrs_d["src"]
        if tag == "a" and attrs_d.get("href", "").startswith("http"):
            self.links.append(attrs_d["href"])
        if tag == "blockquote":
            self._blockquote_depth += 1
        if tag in ("title", "h1", "p", "li") or tag in _HEADING_TAGS:
            self._capture = tag
            self._text = []

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "blockquote":
            self._blockquote_depth = max(0, self._blockquote_depth - 1)
        if tag != self._capture:
            return
        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        self._capture = None
        if not text:
            return
        if tag == "title" and not self.title:
            self.title = re.split(r"\s+[|–—-]\s+", text)[0].strip()
        elif tag == "h1":
            self.title = text
        elif tag in _HEADING_TAGS:
            self._flush_section()
            self._heading = text
        elif tag in ("p", "li"):
            if self._blockquote_depth:
                self._flush_section()  # keep document order: prose so far, then the quote
                self.sections.append((self._heading, [text], True))
            elif not self.subtitle and not self.sections and not self._paragraphs and self._heading == "":
                self.subtitle = text
                self._paragraphs.append(text)
            else:
                self._paragraphs.append(text)

    def handle_data(self, data):
        if self._capture and not self._skip_depth:
            self._text.append(data)

    def close(self):
        super().close()
        self._flush_section()


def parse_html(html: str, fallback_title: str = "") -> EssaySource:
    parser = _EssayHTMLParser()
    parser.feed(html)
    parser.close()

    sections = [
        EssaySection(
            heading=heading or parser.title or fallback_title,
            body=" ".join(paragraphs).strip(),
            is_thesis_line=is_thesis,
        )
        for heading, paragraphs, is_thesis in parser.sections
        if " ".join(paragraphs).strip()
    ]
    return EssaySource(
        title=parser.title or fallback_title or "Untitled Essay",
        subtitle=parser.subtitle,
        sections=sections,
        existing_audio_url=parser.audio_url,
        source_links=list(dict.fromkeys(parser.links)),
    )


# ============================================================================
# Fetching
# ============================================================================

def _to_raw_markdown_url(url: str) -> Optional[str]:
    """github.com blob URLs -> raw.githubusercontent.com; raw .md URLs pass through."""
    if url.endswith((".md", ".markdown")):
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return url
    return None


def fetch_essay(url: str, timeout: float = 20.0) -> EssaySource:
    """
    Fetch and parse an essay from a URL.

    ESSAY_IMPORT_SOURCE=repo prefers raw Jekyll markdown when the URL points
    at one (github blob or *.md); anything else falls back to the rendered
    page. Both paths yield the same EssaySource shape.
    """
    import httpx

    mode = os.getenv("ESSAY_IMPORT_SOURCE", "url").strip().lower()
    raw_url = _to_raw_markdown_url(url) if mode == "repo" or url.endswith((".md", ".markdown")) else None

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        if raw_url:
            resp = client.get(raw_url)
            resp.raise_for_status()
            return parse_markdown(resp.text)
        resp = client.get(url)
        resp.raise_for_status()
        text = resp.text
        content_type = resp.headers.get("content-type", "")

    looks_like_html = "html" in content_type or text.lstrip()[:1] == "<"
    if looks_like_html:
        return parse_html(text)
    return parse_markdown(text)


def ingest(script_text: Optional[str] = None, script_url: Optional[str] = None) -> EssaySource:
    """Single entry point: pasted text wins, then URL."""
    if script_text and script_text.strip():
        text = script_text.strip()
        if text[:1] == "<" and "</" in text:
            return parse_html(text)
        return parse_markdown(text)
    if script_url and script_url.strip():
        return fetch_essay(script_url.strip())
    raise ValueError("script mode requires script_text or script_url")


# ============================================================================
# Deterministic segmentation: essay sections -> scene beats
# ============================================================================

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_DIAGRAM_WORDS = re.compile(
    r"\b(architecture|pipeline|diagram|workflow|flow|layer|module|component|"
    r"schema|topology|stack|graph|routing?|orchestrat\w+)\b", re.IGNORECASE)
_PROOF_WORDS = re.compile(
    r"(\d+(\.\d+)?\s*%|\b\d+x\b|\bbenchmark\w*|\bresults?\b|\baccuracy\b|"
    r"\blatency\b|\bthroughput\b|\bscore[sd]?\b)", re.IGNORECASE)

_TARGET_WORDS_PER_BEAT = 55
_MAX_BEATS_PER_SECTION = 3


def _classify(section: EssaySection, heading: str, text: str,
              is_first: bool, is_last: bool) -> SceneKind:
    if section.is_thesis_line:
        return "quote"
    if is_first:
        return "hero"
    if is_last:
        return "cta"
    probe = f"{heading} {text}"
    if _DIAGRAM_WORDS.search(probe):
        return "diagram"
    if _PROOF_WORDS.search(text):
        return "proof"
    return "transition"


def _split_beats(body: str) -> List[str]:
    """Group a section's sentences into 1-3 beats near the target word count."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body) if s.strip()]
    if not sentences:
        return []
    total_words = sum(len(s.split()) for s in sentences)
    n_beats = min(_MAX_BEATS_PER_SECTION, max(1, round(total_words / _TARGET_WORDS_PER_BEAT)))
    beats: List[List[str]] = [[] for _ in range(n_beats)]
    counts = [0] * n_beats
    idx = 0
    for s in sentences:
        beats[idx].append(s)
        counts[idx] += len(s.split())
        if counts[idx] >= total_words / n_beats and idx < n_beats - 1:
            idx += 1
    return [" ".join(b) for b in beats if b]


def segment_essay(essay: EssaySource, default_duration_sec: float = 5.0,
                  visual_style: str = "technical editorial") -> List[dict]:
    """
    Deterministically segment an EssaySource into SceneOutline-shaped dicts.

    Narration is verbatim essay sentences by construction - this function is
    the guarantee behind "segment, don't invent". The LLM shot-planning pass
    may later overwrite image_prompt/negative_prompt/scene_kind, never narration.
    """
    scenes: List[dict] = []
    n_sections = len(essay.sections)

    for si, section in enumerate(essay.sections):
        beats = [section.body] if section.is_thesis_line else _split_beats(section.body)
        for beat in beats:
            kind = _classify(section, section.heading, beat,
                             is_first=(si == 0 and not scenes),
                             is_last=(si == n_sections - 1))
            scenes.append({
                "scene_number": len(scenes) + 1,
                "title": section.heading or essay.title,
                "description": beat[:160],
                "narration": beat,
                "image_prompt": default_image_prompt(kind, section.heading or essay.title,
                                                     visual_style),
                "negative_prompt": "",   # filled by the caller's default
                "duration_sec": default_duration_sec,
                "scene_kind": kind,
                "renderer_kind": SCENE_KIND_TO_RENDERER.get(kind, "diffusion"),
                "section_heading": section.heading,
            })
    return scenes


def default_image_prompt(kind: SceneKind, heading: str, visual_style: str) -> str:
    """Deterministic fallback image prompt used when the LLM pass is skipped/fails."""
    subject = {
        "hero": f"wide atmospheric opening visual evoking '{heading}'",
        "diagram": f"abstract geometric composition suggesting a technical diagram about {heading}, no readable text",
        "quote": f"minimal dark backdrop with soft gradient glow, space for an overlaid quote about {heading}",
        "proof": f"abstract data-visualization texture, glowing chart-like shapes about {heading}, no readable numbers",
        "cta": "calm closing visual, dark background with gradient accent light",
        "transition": f"subtle abstract transition visual related to {heading}",
    }[kind]
    return f"{TECHNICAL_EDITORIAL_STYLE_PREFIX}, {subject}" \
        if "technical" in visual_style.lower() else f"{visual_style} style, {subject}"


# ============================================================================
# Condensed script for Shorts / teasers (Batch 4)
# ============================================================================

def condense_essay(essay: EssaySource, max_beats: int = 6,
                   default_duration_sec: float = 5.0,
                   visual_style: str = "technical editorial") -> List[dict]:
    """
    Pick the Short/teaser subset from the full beat list, matching the
    brief's Hook / Problem / Core idea / Proof / CTA shape.

    This is SELECTION, not generation - every chosen beat is a verbatim
    segment_essay() beat, so the verbatim-narration guarantee carries over
    to the short formats unchanged. An optional LLM pass may reorder the
    choice (build_condense_prompt below) but can only pick scene numbers,
    never write text.
    """
    beats = segment_essay(essay, default_duration_sec, visual_style)
    if len(beats) <= max_beats:
        return [dict(b) for b in beats]

    def first(kind: str, exclude: set) -> Optional[dict]:
        return next((b for b in beats
                     if b["scene_kind"] == kind and b["scene_number"] not in exclude), None)

    chosen: List[dict] = []
    picked: set = set()

    def take(beat: Optional[dict]) -> None:
        if beat and beat["scene_number"] not in picked:
            chosen.append(beat)
            picked.add(beat["scene_number"])

    take(first("quote", picked) or beats[0])       # hook: the thesis line
    take(beats[0])                                  # problem/setup opener
    take(first("diagram", picked))                  # core idea
    take(first("proof", picked))                    # proof point
    take(first("cta", picked) or beats[-1])         # CTA close

    # top up with remaining beats in document order, then trim
    for b in beats:
        if len(chosen) >= max_beats:
            break
        take(b)

    chosen.sort(key=lambda b: b["scene_number"])
    condensed = []
    for i, b in enumerate(chosen[:max_beats]):
        nb = dict(b)
        nb["scene_number"] = i + 1
        condensed.append(nb)
    return condensed


def build_condense_prompt(beats: List[dict], max_beats: int) -> Tuple[str, str]:
    """Optional LLM refinement of the condensed selection: it may only
    return scene numbers to keep, in order - selection, never prose."""
    system = f"""You are editing a long-form video down to a short-form teaser.
You will see numbered beats (their text is final and immutable). Choose up to
{max_beats} beat numbers that best follow the shape:
hook -> problem -> core idea -> proof -> call to action.
Output ONLY a JSON object: {{"keep": [1, 4, 7]}}"""
    lines = [f'{b["scene_number"]}. [{b.get("scene_kind", "")}] {b["narration"][:200]}'
             for b in beats]
    return system, "\n".join(lines) + "\n\nReturn the JSON object now:"


def apply_condense_selection(beats: List[dict], selection: object,
                             max_beats: int) -> Optional[List[dict]]:
    """Apply an LLM keep-list. Returns None if the selection is unusable
    (caller keeps the deterministic choice)."""
    if isinstance(selection, dict):
        selection = selection.get("keep")
    if not isinstance(selection, list):
        return None
    by_number = {b["scene_number"]: b for b in beats}
    kept = [by_number[n] for n in selection
            if isinstance(n, int) and n in by_number][:max_beats]
    if len(kept) < 2:
        return None
    kept.sort(key=lambda b: b["scene_number"])
    out = []
    for i, b in enumerate(kept):
        nb = dict(b)
        nb["scene_number"] = i + 1
        out.append(nb)
    return out


# ============================================================================
# LLM shot planning (prompts only - the endpoint owns the LLM call)
# ============================================================================

def build_shot_planning_prompt(essay: EssaySource, scenes: List[dict],
                               visual_style: str) -> Tuple[str, str]:
    """
    Build (system, user) prompts asking the LLM ONLY for shot planning:
    refine scene_kind and write image prompts. It never sees a way to change
    narration - output is keyed by scene number and merged field-by-field.
    """
    system = f"""You are a shot planner for a technical documentary video. You do NOT write narration.
For each scene you are given (its narration is final and immutable), decide:
  - scene_kind: one of hero, diagram, quote, proof, cta, transition
  - image_prompt: a diffusion prompt for a BACKGROUND visual in "{visual_style}" style.
    Never ask for readable text, words, labels, numbers, or diagrams with captions -
    text is rendered separately by a deterministic engine.
Output ONLY a JSON object of the form:
{{"scenes": [{{"scene_number": 1, "scene_kind": "hero", "image_prompt": "..."}}]}}"""

    lines = [f"Essay: {essay.title}"]
    for s in scenes:
        lines.append(
            f'{s["scene_number"]}. [{s.get("section_heading", "")}] '
            f'(current guess: {s.get("scene_kind", "transition")}) {s["narration"][:220]}'
        )
    user = "\n".join(lines) + "\n\nReturn the JSON array now:"
    return system, user


_VALID_KINDS = {"hero", "diagram", "quote", "proof", "cta", "transition"}


def apply_shot_plan(scenes: List[dict], plan: object) -> int:
    """Merge an LLM shot plan into scenes. Narration is never touched. Returns #applied."""
    if isinstance(plan, dict):
        plan = plan.get("scenes")
    if not isinstance(plan, list):
        return 0
    by_number = {s["scene_number"]: s for s in scenes}
    applied = 0
    for entry in plan:
        if not isinstance(entry, dict):
            continue
        scene = by_number.get(entry.get("scene_number"))
        if not scene:
            continue
        kind = str(entry.get("scene_kind", "")).strip().lower()
        if kind in _VALID_KINDS:
            scene["scene_kind"] = kind
            scene["renderer_kind"] = SCENE_KIND_TO_RENDERER.get(kind, "diffusion")
        prompt = str(entry.get("image_prompt", "")).strip()
        if prompt:
            scene["image_prompt"] = prompt
        applied += 1
    return applied
