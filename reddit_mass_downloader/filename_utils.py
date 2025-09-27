import re
from pathlib import Path

SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(text: str, max_len: int = 80) -> str:
    text = text or ""
    text = text.strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = SAFE_CHAR_RE.sub("_", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("_-")
    return text or "post"


def with_unique_suffix(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    for i in range(2, 10_000):
        p = path.with_name(f"{stem}({i}){ext}")
        if not p.exists():
            return p
    return path.with_name(f"{stem}(9999){ext}")
