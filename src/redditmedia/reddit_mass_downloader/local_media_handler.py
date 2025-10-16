# reddit_mass_downloader/local_media_handler.py

import json
from urllib.parse import urlparse
import re
import os
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List, Union
import html

from asyncpraw import Reddit
from asyncpraw.models import Submission

from .filename_utils import build_filename_clamped
from .config_overrides import (
    OUTPUT_ROOT,
    WRITE_SUBREDDIT_MANIFEST,
    WRITE_JSON_SIDECARS,
    ENABLE_COMPRESSION,
    MAX_FILE_SIZE_MB,
    MAX_FILENAME_LEN,  # NEW
)

from ..redditcommand.utils.media_utils import MediaDownloader, MediaUtils
from ..redditcommand.handle_direct_link import MediaLinkResolver
from ..redditcommand.utils.compressor import Compressor


def _ext_from_mime(m: Optional[str]) -> str:
    if not m:
        return ""
    m = m.lower()
    if m in ("image/jpg", "image/jpeg"):
        return ".jpg"
    if m == "image/png":
        return ".png"
    if m == "image/gif":
        return ".gif"
    if m in ("video/mp4", "image/mp4"):
        return ".mp4"
    return ""


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext or ""


class LocalMediaSaver:
    """
    Saves media for a post to disk:
      - if post is a Reddit gallery, resolves and downloads ALL items (image/video)
      - otherwise uses MediaLinkResolver to resolve a single direct media URL
      - downloads to C:\\Reddit\\<subreddit or collection_label>\\, writes JSON sidecar (+ manifest)
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

    # --- NEW: robust finalization for Windows locks (AV/indexer) ---
    async def _finalize_tmp(self, tmp_path: Path, final_path: Path, *, attempts: int = 5, delay_sec: float = 0.2) -> bool:
        """
        Try to atomically replace tmp_path -> final_path.
        Retries to avoid transient Windows locks. Falls back to copy+unlink.
        """
        if not tmp_path.exists():
            return final_path.exists()

        for _ in range(attempts):
            try:
                os.replace(str(tmp_path), str(final_path))
                return True
            except Exception:
                time.sleep(delay_sec)

        # Fallback: copy then unlink
        try:
            shutil.copyfile(str(tmp_path), str(final_path))
            try:
                tmp_path.unlink()
            except Exception:
                pass
            return True
        except Exception:
            if final_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                return True
        return final_path.exists()

    # === Robust gallery resolver: returns (url, ext) per item ===
    async def _resolve_gallery_items(self, post: Submission) -> List[Tuple[str, str]]:
        """Return list of (direct_url, ext) for a Reddit gallery.
        Handles crossposts by following the parent/original submission.
        """
        def extract_items(subm: Submission) -> List[Tuple[str, str]]:
            gdata = getattr(subm, "gallery_data", None)
            mmeta = getattr(subm, "media_metadata", None)
            if not gdata or not mmeta:
                return []
            out: List[Tuple[str, str]] = []
            items = gdata.get("items", []) or []
            for it in items:
                mid = it.get("media_id")
                if not mid:
                    continue
                md = mmeta.get(mid) or {}
                if (md.get("status") or "").lower() != "valid":
                    continue
                mime = md.get("m")
                s = md.get("s") or {}
                # Prefer video mp4 (for gifv), then image "u", then legacy "gif"
                candidate = s.get("mp4") or s.get("u") or s.get("gif")
                if not candidate:
                    previews = md.get("p") or []
                    if previews:
                        candidate = previews[-1].get("u")
                if not candidate:
                    continue
                candidate = html.unescape(candidate)
                ext = _ext_from_url(candidate) or _ext_from_mime(mime) or (".mp4" if s.get("mp4") else ".jpg")
                out.append((candidate, ext))
            return out

        # Make sure lazy fields are available
        try:
            await post.load()
        except Exception:
            pass

        # 1) If this *is* a gallery, use it directly
        if bool(getattr(post, "is_gallery", False)):
            items = extract_items(post)
            if items:
                return items

        # 2) Otherwise, chase the original submission (common for crossposts)
        candidate_ids: List[str] = []

        # from URL like https://www.reddit.com/gallery/<id>
        url = getattr(post, "url", "") or ""
        m = re.search(r"/gallery/([a-z0-9]+)", url, re.I)
        if m:
            candidate_ids.append(m.group(1).lower())

        # from crosspost_parent_list
        try:
            cpl = getattr(post, "crosspost_parent_list", None)
            if isinstance(cpl, list) and cpl:
                pid = cpl[0].get("id")
                if pid:
                    candidate_ids.append(str(pid).lower())
        except Exception:
            pass

        # from crosspost_parent fullname 't3_<id>'
        try:
            cpf = getattr(post, "crosspost_parent", None)
            if isinstance(cpf, str) and cpf.startswith("t3_"):
                candidate_ids.append(cpf.split("_", 1)[1].lower())
        except Exception:
            pass

        # Dedup while preserving order
        seen = set()
        cand_unique = []
        for cid in candidate_ids:
            if cid and cid not in seen:
                seen.add(cid)
                cand_unique.append(cid)

        # Try each candidate original
        for cid in cand_unique:
            try:
                orig = self.reddit.submission(id=cid)
                await orig.load()
                if bool(getattr(orig, "is_gallery", False)):
                    items = extract_items(orig)
                    if items:
                        return items
            except Exception:
                continue

        # Nothing found
        return []

    def _build_paths(
        self,
        post: Submission,
        resolved_url: str,
        *,
        index: Optional[int] = None,
        override_ext: Optional[str] = None
    ) -> Dict[str, Path]:
        sub = getattr(post.subreddit, "display_name", "unknown")
        subdir = self._subdir(sub)
        basename = resolved_url.split("?")[0]
        ext = override_ext or os.path.splitext(basename)[-1] or ".mp4"

        # Build subreddit_title_id.ext (clamped)
        title = getattr(post, "title", "") or ""
        base_filename = build_filename_clamped(sub, title, post.id, ext, max_name_len=MAX_FILENAME_LEN)

        # If gallery item, insert _NN *before* the _<id> so the id is last.
        if index is not None:
            stem, suffix = os.path.splitext(base_filename)              # e.g., "kpopfap_title_abc123", ".mp4"
            # Split off the trailing "_<id>"
            if "_" in stem:
                prefix, last = stem.rsplit("_", 1)                      # prefix="kpopfap_title", last="abc123"
                # Only treat as id if it matches the current post.id
                if last == post.id:
                    candidate = f"{prefix}_{index:02d}_{last}{suffix}"  # kpopfap_title_01_abc123.mp4
                else:
                    candidate = f"{stem}_{index:02d}{suffix}"           # fallback (should be rare)
            else:
                candidate = f"{stem}_{index:02d}{suffix}"

            if len(candidate) > MAX_FILENAME_LEN:
                # Trim only the *prefix* so we keep "_NN_<id>" intact at the end.
                overflow = len(candidate) - MAX_FILENAME_LEN
                # Recompute safe trim target
                if "_" in stem and stem.endswith(f"_{post.id}"):
                    prefix, _last = stem.rsplit("_", 1)
                    trimmed_prefix = prefix[:-overflow].rstrip("._-") if overflow < len(prefix) else prefix
                    candidate = f"{trimmed_prefix}_{index:02d}_{post.id}{suffix}"
                else:
                    # Generic trim if we couldn't detect the id reliably
                    trimmed_stem = stem[:-overflow].rstrip("._-") if overflow < len(stem) else stem
                    candidate = f"{trimmed_stem}_{index:02d}{suffix}"

            base_filename = candidate

        media_path = subdir / base_filename
        meta_path = media_path.with_suffix(media_path.suffix + ".json")  # computed, writing is optional
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

    async def _resolve_media_url(self, post: Submission) -> Union[str, List[Tuple[str, str]], None]:
        """Return a single URL (non-gallery) or list of (url, ext) tuples (gallery)."""
        url = getattr(post, "url", "") or ""

        # Ensure gallery handling first (some crossposts use reddit.com/gallery/<id>)
        try:
            await post.load()
        except Exception:
            pass

        if bool(getattr(post, "is_gallery", False)) or "reddit.com/gallery/" in url or "/gallery/" in url:
            items = await self._resolve_gallery_items(post)
            return items or None

        # Delegate ALL normalization to the resolver
        return await self.resolver.resolve(url, post=post)

    async def save_post(self, post: Submission) -> Optional[Union[Path, List[Path]]]:
        await self._ensure_ready()
        if not getattr(post, "url", None):
            return None

        resolved = await self._resolve_media_url(post)
        if not resolved:
            return None

        # --- GALLERY CASE: list of (url, ext) ---
        if isinstance(resolved, list):
            saved_paths: List[Path] = []
            total = len(resolved)
            for i, (item_url, item_ext) in enumerate(resolved, start=1):
                paths = self._build_paths(post, item_url, index=i, override_ext=item_ext)

                target_media = paths["media"]
                tmp_media = target_media.with_suffix(target_media.suffix + ".tmp")
                try:
                    if tmp_media.exists():
                        tmp_media.unlink()
                except Exception:
                    pass

                if os.path.isfile(item_url) and not item_url.lower().startswith(("http://", "https://")):
                    os.replace(item_url, tmp_media)
                else:
                    downloaded = await MediaDownloader.download_file(item_url, str(tmp_media))
                    if not downloaded:
                        continue

                # Optional: gif → mp4
                if str(tmp_media).lower().endswith(".gif"):
                    converted = await MediaUtils.convert_gif_to_mp4(str(tmp_media))
                    if converted:
                        try:
                            tmp_media.unlink()
                        except Exception:
                            pass
                        tmp_media = Path(converted)

                if ENABLE_COMPRESSION:
                    maybe = await Compressor.validate_and_compress(str(tmp_media), MAX_FILE_SIZE_MB)
                    if not maybe:
                        try:
                            tmp_media.unlink()
                        except Exception:
                            pass
                        continue
                    tmp_media = Path(maybe)

                # Robust finalize (retries + fallback)
                ok = await self._finalize_tmp(tmp_media, target_media)
                if not ok:
                    # Couldn’t finalize; skip sidecar to avoid orphaned JSON
                    continue

                # Build metadata (used for manifest; JSON sidecar optional)
                tc_obj = await MediaUtils.fetch_top_comment(post, return_author=True)
                top_comment_text, top_comment_author = self._top_comment_fields(tc_obj)
                meta = self._metadata(post, target_media, item_url, top_comment_text, top_comment_author)
                meta["gallery_index"] = i
                meta["gallery_total"] = total

                # Optional: write .json sidecar next to media
                if WRITE_JSON_SIDECARS:
                    tmp_meta = paths["meta"].with_suffix(paths["meta"].suffix + ".tmp")
                    try:
                        with open(tmp_meta, "w", encoding="utf-8") as f:
                            json.dump(meta, f, ensure_ascii=False, indent=2)
                        await self._finalize_tmp(tmp_meta, paths["meta"])
                    finally:
                        try:
                            if tmp_meta.exists():
                                tmp_meta.unlink()
                        except Exception:
                            pass

                if WRITE_SUBREDDIT_MANIFEST:
                    self._append_manifest(meta, paths["subdir"])

                saved_paths.append(target_media)

            return saved_paths or None

        # --- NON-GALLERY CASE: existing logic for a single URL ---
        paths = self._build_paths(post, resolved)

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

        if str(tmp_media).lower().endswith(".gif"):
            converted = await MediaUtils.convert_gif_to_mp4(str(tmp_media))
            if not converted:
                try:
                    tmp_media.unlink()
                except Exception:
                    pass
                return None
            try:
                tmp_media.unlink()
            except Exception:
                pass
            tmp_media = Path(converted)

        if ENABLE_COMPRESSION:
            maybe = await Compressor.validate_and_compress(str(tmp_media), MAX_FILE_SIZE_MB)
            if not maybe:
                try:
                    tmp_media.unlink()
                except Exception:
                    pass
                return None
            tmp_media = Path(maybe)

        ok = await self._finalize_tmp(tmp_media, target_media)
        if not ok:
            return None

        # Build metadata (for manifest; JSON sidecar optional)
        tc_obj = await MediaUtils.fetch_top_comment(post, return_author=True)
        top_comment_text, top_comment_author = self._top_comment_fields(tc_obj)
        meta = self._metadata(post, target_media, resolved, top_comment_text, top_comment_author)

        if WRITE_JSON_SIDECARS:
            tmp_meta = paths["meta"].with_suffix(paths["meta"].suffix + ".tmp")
            try:
                with open(tmp_meta, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                await self._finalize_tmp(tmp_meta, paths["meta"])
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
            "top_comment", "top_comment_author",
            # Optional gallery context (present for gallery items only)
            "gallery_index", "gallery_total",
        ]
        # make a shallow copy to ensure missing keys exist
        row = {k: meta.get(k) for k in fieldnames}
        with open(manifest, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if not exists:
                w.writeheader()
            w.writerow(row)
