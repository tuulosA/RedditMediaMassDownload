# redditcommand/utils/name_utils.py
import os
import re
from typing import Tuple
from asyncpraw.models import Submission

SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def slugify_title(text: str, max_len: int = 160) -> str:
    # Kept for compatibility (unused by build below)
    text = (text or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = SAFE_CHAR_RE.sub("_", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("._-")
    return text or "post"

def build_filename(subreddit: str, title: str, post_id: str, ext: str, max_name_len: int = 200) -> str:
    """
    Telegram-bot filename builder (titleless):
    Return 'subreddit_id.ext' clamped to max_name_len (Windows/Telegram-safe).
    """
    sub = (subreddit or "unknown").strip().lstrip("r/").replace(" ", "_").lower()
    base = f"{sub}_{post_id}{ext}"
    # Practically this is short enough, but clamp anyway for safety.
    if len(base) <= max_name_len:
        return base
    # If somehow too long, trim subreddit part but preserve id + ext.
    fixed_len = len("_") + len(post_id) + len(ext)  # '_' + id + ext
    avail_for_sub = max(1, max_name_len - fixed_len)
    sub = sub[:avail_for_sub].rstrip("._-") or "r"
    return f"{sub}_{post_id}{ext}"

def temp_paths_for_vreddit(post: Submission, ext: str = ".mp4") -> Tuple[str, str, str]:
    """
    Return (canonical_out, video_tmp, audio_tmp) under a temp dir using subreddit_id.
    """
    from redditcommand.utils.tempfile_utils import TempFileManager  # lazy import
    temp_dir = TempFileManager.create_temp_dir("vreddit_")

    sub = getattr(getattr(post, "subreddit", None), "display_name", None) or "unknown"
    pid = getattr(post, "id", "") or "unknown"

    final_name = build_filename(sub, "", pid, ext)
    canonical_out = os.path.join(temp_dir, final_name)
    stem, _ = os.path.splitext(final_name)
    video_tmp = os.path.join(temp_dir, f"{stem}__video_tmp.mp4")
    audio_tmp = os.path.join(temp_dir, f"{stem}__audio_tmp.m4a")
    return canonical_out, video_tmp, audio_tmp

def temp_path_for_generic(post: Submission, ext: str = ".mp4", prefix: str = "reddit_media_") -> str:
    """
    Return a temp file path '<temp>/<subreddit_id><ext>'.
    """
    from redditcommand.utils.tempfile_utils import TempFileManager  # lazy import
    temp_dir = TempFileManager.create_temp_dir(prefix)

    sub = getattr(getattr(post, "subreddit", None), "display_name", None) or "unknown"
    pid = getattr(post, "id", "") or "unknown"

    final_name = build_filename(sub, "", pid, ext)
    return os.path.join(temp_dir, final_name)

def yt_dlp_output_template(post: Submission, ext: str = "mp4", prefix: str = "ytdlp_video_") -> Tuple[str, str]:
    """
    Return (temp_dir, output_template_without_ext). Caller passes '%(ext)s'.
    Uses 'subreddit_id.ext' (no title) to keep IDs intact on Telegram.
    """
    from redditcommand.utils.tempfile_utils import TempFileManager  # lazy import
    temp_dir = TempFileManager.create_temp_dir(prefix)

    sub = getattr(getattr(post, "subreddit", None), "display_name", None) or "unknown"
    pid = getattr(post, "id", "") or "unknown"

    base = build_filename(sub, "", pid, f".{ext}")
    base_no_ext, _ = os.path.splitext(base)
    return temp_dir, os.path.join(temp_dir, base_no_ext)
