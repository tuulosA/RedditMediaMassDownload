import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from asyncpraw import Reddit
from asyncpraw.models import Submission

from reddit_mass_downloader.filename_utils import slugify, with_unique_suffix
from reddit_mass_downloader.config_overrides import (
    OUTPUT_ROOT,
    FILENAME_TEMPLATE,
    WRITE_SUBREDDIT_MANIFEST,
    ENABLE_COMPRESSION,
    MAX_FILE_SIZE_MB,
)

from redditcommand.utils.media_utils import MediaDownloader, MediaUtils
from redditcommand.handle_direct_link import MediaLinkResolver
from redditcommand.utils.compressor import Compressor


class LocalMediaSaver:
    """
    Saves a single media for a post to disk:
      - if post is a Reddit gallery, resolves the FIRST image (same as the bot)
      - otherwise uses MediaLinkResolver to resolve direct media url
      - downloads to C:\Reddit\<subreddit>\, writes JSON sidecar (+ manifest)
      - includes top comment (text + author) in the metadata
    """
    def __init__(self, reddit: Reddit, root: Path = OUTPUT_ROOT, collection_label: Optional[str] = None):
        self.root = root
        self.reddit = reddit
        self.resolver = MediaLinkResolver()
        self.collection_label = collection_label

    async def _ensure_ready(self):
        await self.resolver.init()

    def _subdir(self, subreddit: str) -> Path:
        # If a collection label (e.g., from search terms) is provided,
        # save everything under that directory. Otherwise, keep per-subreddit.
        dir_name = self.collection_label or subreddit
        p = self.root / dir_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _created_str(post: Submission) -> str:
        try:
            dt = datetime.fromtimestamp(int(post.created_utc), tz=timezone.utc)
            return dt.strftime("%Y%m%d_%H%M%S")
        except Exception:
            return "00000000_000000"

    def _build_paths(self, post: Submission, resolved_url: str) -> Dict[str, Path]:
        sub = getattr(post.subreddit, "display_name", "unknown")
        subdir = self._subdir(sub)
        basename = resolved_url.split("?")[0]
        ext = os.path.splitext(basename)[-1] or ".mp4"
        slug = slugify(getattr(post, "title", ""))
        created = self._created_str(post)
        filename = FILENAME_TEMPLATE.format(id=post.id, created=created, subreddit=sub, slug=slug, ext=ext)

        # Deterministic final paths (no suffixing; we overwrite atomically)
        media_path = subdir / filename
        meta_path = media_path.with_suffix(media_path.suffix + ".json")
        return {"media": media_path, "meta": meta_path, "subdir": subdir}

    @staticmethod
    def _top_comment_fields(tc_obj_or_text) -> Tuple[Optional[str], Optional[str]]:
        """
        Normalize the result of MediaUtils.fetch_top_comment(..., return_author=True)
        into (text, author_name).
        """
        try:
            # When return_author=True, the helper returns a Comment object;
            # otherwise it can be a str (or None).
            if hasattr(tc_obj_or_text, "body"):
                text = getattr(tc_obj_or_text, "body", None)
                author = getattr(getattr(tc_obj_or_text, "author", None), "name", None)
            else:
                text = tc_obj_or_text if isinstance(tc_obj_or_text, str) else None
                author = None
            if text:
                text = text.strip()
                if len(text) > 1000:
                    text = text[:997] + "…"
            return text or None, author
        except Exception:
            return None, None

    def _metadata(
        self,
        post: Submission,
        media_path: Path,
        resolved_url: str,
        top_comment_text: Optional[str],
        top_comment_author: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "id": post.id,
            "title": getattr(post, "title", None),
            "author": getattr(getattr(post, "author", None), "name", None),
            "subreddit": getattr(getattr(post, "subreddit", None), "display_name", None),
            "permalink": f"https://reddit.com/comments/{post.id}",
            "url": getattr(post, "url", None),
            "resolved_url": resolved_url,
            "created_utc": getattr(post, "created_utc", None),
            "score": getattr(post, "score", None),
            "upvote_ratio": getattr(post, "upvote_ratio", None),
            "num_comments": getattr(post, "num_comments", None),
            "flair": getattr(post, "link_flair_text", None),

            # NEW:
            "top_comment": top_comment_text,
            "top_comment_author": top_comment_author,

            "saved_path": str(media_path),
        }

    async def _resolve_media_url(self, post: Submission) -> Optional[str]:
        url = getattr(post, "url", "") or ""
        if "reddit.com/gallery/" in url or "/gallery/" in url:
            return await MediaUtils.resolve_reddit_gallery(post.id, self.reddit)
        return await self.resolver.resolve(url, post=post)

    async def save_post(self, post: Submission) -> Optional[Path]:
        await self._ensure_ready()
        if not getattr(post, "url", None):
            return None

        resolved = await self._resolve_media_url(post)
        if not resolved:
            return None

        paths = self._build_paths(post, resolved)

        # --- download/move to temp, then atomic replace into final ---
        target_media = paths["media"]
        tmp_media = target_media.with_suffix(target_media.suffix + ".tmp")

        try:
            if tmp_media.exists():
                tmp_media.unlink()
        except Exception:
            pass

        if os.path.isfile(resolved) and not resolved.lower().startswith(("http://", "https://")):
            os.replace(resolved, tmp_media)
        else:
            downloaded = await MediaDownloader.download_file(resolved, str(tmp_media))
            if not downloaded:
                return None

        # Optional gif → mp4 conversion still on temp artifact
        if str(tmp_media).lower().endswith(".gif"):
            converted = await MediaUtils.convert_gif_to_mp4(str(tmp_media))
            if not converted:
                try: tmp_media.unlink()
                except Exception: pass
                return None
            try: tmp_media.unlink()
            except Exception: pass
            tmp_media = Path(converted)

        if ENABLE_COMPRESSION:
            maybe = await Compressor.validate_and_compress(str(tmp_media), MAX_FILE_SIZE_MB)
            if not maybe:
                try: tmp_media.unlink()
                except Exception: pass
                return None
            tmp_media = Path(maybe)

        # Atomic overwrite into final path
        os.replace(str(tmp_media), str(target_media))

        # --- build + write sidecar JSON atomically ---
        tc_obj = await MediaUtils.fetch_top_comment(post, return_author=True)
        top_comment_text, top_comment_author = self._top_comment_fields(tc_obj)

        meta = self._metadata(post, target_media, resolved, top_comment_text, top_comment_author)
        tmp_meta = paths["meta"].with_suffix(paths["meta"].suffix + ".tmp")
        try:
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_meta, paths["meta"])  # atomic replace
        finally:
            try:
                if tmp_meta.exists():
                    tmp_meta.unlink()
            except Exception:
                pass

        if WRITE_SUBREDDIT_MANIFEST:
            self._append_manifest(meta, paths["subdir"])

        return target_media

    @staticmethod
    def _append_manifest(meta: Dict[str, Any], subdir: Path) -> None:
        import csv
        manifest = subdir / "manifest.csv"
        exists = manifest.exists()
        fieldnames = [
            "saved_path", "id", "title", "author", "subreddit", "permalink", "url", "resolved_url",
            "created_utc", "score", "upvote_ratio", "num_comments", "flair",
            # NEW:
            "top_comment", "top_comment_author",
        ]
        with open(manifest, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if not exists:
                w.writeheader()
            w.writerow({k: meta.get(k) for k in fieldnames})
