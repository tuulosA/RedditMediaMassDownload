import re

SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify_title(text: str, max_len: int = 80) -> str:
    """Sanitize a Reddit title for filenames."""
    text = (text or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = SAFE_CHAR_RE.sub("_", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("._-")
    return text or "post"

def build_filename_clamped(subreddit: str, title: str, post_id: str, ext: str, max_name_len: int = 200) -> str:
    """
    Build subreddit_title_id.ext and clamp the *filename* length (no path) to max_name_len.
    """
    sub_clean = (subreddit or "unknown").strip().lstrip("r/").replace(" ", "_").lower()
    title_slug = slugify_title(title, max_len=200)  # start generous, clamp precisely below

    base = f"{sub_clean}_{title_slug}_{post_id}{ext}"
    if len(base) <= max_name_len:
        return base

    # shrink title portion until it fits
    fixed_len = len(sub_clean) + 1 + 1 + len(post_id) + len(ext)  # sub + '_' + '_' + id + ext
    avail_for_title = max(8, max_name_len - fixed_len)
    title_slug = title_slug[:avail_for_title].rstrip("._-")
    return f"{sub_clean}_{title_slug}_{post_id}{ext}"