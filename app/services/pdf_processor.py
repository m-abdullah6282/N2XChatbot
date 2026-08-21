from pypdf import PdfReader
import re

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 0) -> list[str]:
    """Split knowledge documents at headings instead of fixed character offsets.

    A section such as ``SERVICES`` or ``Project 3: ...`` remains a single
    semantic chunk whenever it fits in ``chunk_size``.  Very large sections
    are only split at paragraph boundaries, never in the middle of a word or
    list item. ``overlap`` is retained for backwards-compatible callers but
    is intentionally unused: overlapping sections create duplicate search
    hits and less useful retrieval context.
    """
    del overlap
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    uppercase_heading_pattern = re.compile(r"^[A-Z][A-Z0-9/& -]{2,}$")
    project_heading_pattern = re.compile(r"^Project\s+\d+\s*:", re.IGNORECASE)
    sections: list[str] = []
    current: list[str] = []

    for line in normalized.split("\n"):
        # A top-level all-caps heading or Project N starts a distinct section.
        stripped_line = line.strip()
        is_heading = bool(
            uppercase_heading_pattern.match(stripped_line)
            or project_heading_pattern.match(stripped_line)
        )
        # Keep document titles with the first section, and keep container
        # headings (for example, ``PROJECTS``) with their first child.
        has_section_body = len([existing for existing in current if existing.strip()]) > 1
        if is_heading and has_section_body:
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = []
        current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section)
            continue

        # Prefer paragraph boundaries for unusually long prose sections.
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section) if paragraph.strip()]
        pending = ""
        for paragraph in paragraphs:
            candidate = f"{pending}\n\n{paragraph}".strip() if pending else paragraph
            if pending and len(candidate) > chunk_size:
                chunks.append(pending)
                pending = paragraph
            else:
                pending = candidate
        if pending:
            chunks.append(pending)

    return chunks
