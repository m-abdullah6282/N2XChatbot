from pypdf import PdfReader
import re

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text


_UPPERCASE_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9/& .(){}+:'%-]{2,}$")
_PROJECT_HEADING_RE = re.compile(r"^Project\s+\d+\s*:", re.IGNORECASE)
_COLON_LABEL_RE = re.compile(r"^.{1,50}:\s*$")
_BULLET_LINE_RE = re.compile(r"^[ \t]*[●•▪*\-]\s")
_SEPARATOR_BAR_RE = re.compile(r"\s\|\s")


def _is_colon_label(line: str) -> bool:
    """Short label lines ending in ``:`` ("MISSION:", "Tech Stack:", "NOTE:")."""
    return bool(line and _COLON_LABEL_RE.match(line))


def _is_entry_title(line: str, following: list[str]) -> bool:
    """Sub-entry titles inside a section: a short, non-sentence, non-bullet
    title ("AI Employee OS — Agentic AI Platform", "LCM Sports E-Commerce
    Platform") immediately followed by a ``Label: ...`` line ("Tech Stack: ...").
    Format-agnostic: any document whose entries carry a leading label line —
    a resume/CV project, a datasheet row, a product spec — splits the same way.
    """
    if not (3 <= len(line) <= 60):
        return False
    if line.endswith((".", ":", ";", ",")):
        return False
    # Already a "Label: value" line (e.g. "Website: www.x.com", "Email: n@d.co")
    # — that is content, not a section title marking a transition.
    if ":" in line[:24]:
        return False
    for ahead in following[:2]:
        ahead = ahead.strip()
        if not ahead:
            continue
        if _is_colon_label(ahead) or ":" in ahead[:24]:
            return True
    return False


def _split_long_section(section: str, chunk_size: int) -> list[str]:
    """Split an oversized section at its natural boundaries: paragraph gaps
    first, then still-oversized paragraphs at bullet items (so a list of
    projects/products is not cut mid-entry) and finally raw parity only if the
    paragraph really has no boundary at all."""
    chunks: list[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
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

    # A single paragraph still over budget (no blank lines, e.g. a dense CV
    # project list) is split before each bullet marker, packing consecutive
    # bullets of the same entry together while keeping headers attached.
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            final.append(chunk)
            continue
        items: list[list[str]] = [[]]
        for line in chunk.split("\n"):
            if _BULLET_LINE_RE.match(line):
                items.append([line])
            else:
                items[-1].append(line)
        buf: list[str] = items[0][:]
        for item in items[1:]:
            if buf and len("\n".join(buf + item).strip()) > chunk_size:
                packed = "\n".join(buf).strip()
                if packed:
                    final.append(packed)
                buf = item
            else:
                buf = buf + item
        packed = "\n".join(buf).strip()
        if packed:
            final.append(packed)
    return final


def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 0) -> list[str]:
    """Split knowledge documents at headings instead of fixed character offsets.

    Heading detection is deliberately format-agnostic so ANY document style
    splits the same way — ALL-CAPS blocks ("SERVICES"), title-case CV section
    headers ("PROFESSIONAL EXPERIENCE"), "Project 1:" lines, short labels
    ending in ":" ("MISSION:", "Tech Stack:"), short title lines followed by a
    blank line, and entry titles that precede a "Label: ..." line. Nothing is
    hardcoded for one document's formatting.

    A section remains a single semantic chunk whenever it fits in
    ``chunk_size``; very large sections are split at paragraph boundaries and
    then at bullet items, never in the middle of a word or list entry.
    ``overlap`` is retained for backwards-compatible callers but is
    intentionally unused: overlapping sections create duplicate search hits
    and less useful retrieval context.
    """
    del overlap
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    lines = normalized.split("\n")
    sections: list[str] = []
    current: list[str] = []

    for index, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            current.append(line)
            continue
        following = lines[index + 1 : index + 4]
        next_line_blank = not (following[0].strip() if following else "")

        is_heading = bool(
            _UPPERCASE_HEADING_RE.match(stripped_line)
            or _PROJECT_HEADING_RE.match(stripped_line)
            or _is_colon_label(stripped_line)
            or _is_entry_title(stripped_line, following)
            or (
                # Short title-like line directly followed by a blank line
                # (e.g. the header block of a resume). "Label: value" lines
                # like "Website: www.x.com" are excluded.
                2 <= len(stripped_line) <= 60
                and next_line_blank
                and ":" not in stripped_line[:24]
                and not _SEPARATOR_BAR_RE.search(stripped_line)
                and stripped_line.endswith((":", ".")) is False
            )
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
        chunks.extend(_split_long_section(section, chunk_size))

    return chunks
