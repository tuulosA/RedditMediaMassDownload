# redditcommand/utils/reddit_video_resolver.py
# Robust resolver for dead external links where the reddit-hosted video still exists.

import aiohttp
import os
import re
from asyncpraw.models import Submission
from typing import Optional, Tuple, Any, Dict, List

from redditcommand.config import RedditVideoConfig
from redditcommand.utils.tempfile_utils import TempFileManager
from redditcommand.utils.session import GlobalSession
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class RedditVideoResolver:
    # ---------- Helpers to extract v.redd.it from the Submission itself ----------

    @staticmethod
    def _extract_vreddit_from_reddit_video(rv: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        rv is something like post.secure_media.get("reddit_video")
        It may contain keys like fallback_url, dash_url, hls_url, scrubber_media_url.
        """
        if not isinstance(rv, dict):
            return None
        # Prefer dash_url; if not present, try fallback_url (usually a DASH_* file)
        candidates = [
            rv.get("dash_url"),
            rv.get("fallback_url"),
            rv.get("scrubber_media_url"),
            rv.get("hls_url"),
        ]
        for url in candidates:
            if not url:
                continue
            m = re.search(r"(https://v\.redd\.it/[A-Za-z0-9]+)", url)
            if m:
                return m.group(1)
        return None

    @classmethod
    def _extract_vreddit_from_submission(cls, post: Submission) -> Optional[str]:
        try:
            # 1) secure_media / media (you already have)
            sm = getattr(post, "secure_media", None)
            if isinstance(sm, dict) and "reddit_video" in sm:
                url = cls._extract_vreddit_from_reddit_video(sm.get("reddit_video"))
                if url:
                    logger.debug("[Resolver] Found v.redd.it via secure_media")
                    return url

            m = getattr(post, "media", None)
            if isinstance(m, dict) and "reddit_video" in m:
                url = cls._extract_vreddit_from_reddit_video(m.get("reddit_video"))
                if url:
                    logger.debug("[Resolver] Found v.redd.it via media")
                    return url

            # 2) **preview.reddit_video_preview** (NEW)
            pv = getattr(post, "preview", None)
            if isinstance(pv, dict) and "reddit_video_preview" in pv:
                url = cls._extract_vreddit_from_reddit_video(pv.get("reddit_video_preview"))
                if url:
                    logger.debug("[Resolver] Found v.redd.it via preview.reddit_video_preview")
                    return url

            # 3) crosspost_parent_list (you already have)
            cpl = getattr(post, "crosspost_parent_list", None)
            if isinstance(cpl, list):
                for parent in cpl:
                    if isinstance(parent, dict):
                        rv = (parent.get("secure_media") or {}).get("reddit_video") \
                            or (parent.get("media") or {}).get("reddit_video") \
                            or (parent.get("preview") or {}).get("reddit_video_preview")
                        url = cls._extract_vreddit_from_reddit_video(rv)
                        if url:
                            logger.debug("[Resolver] Found v.redd.it via crosspost_parent_list")
                            return url
        except Exception as e:
            logger.debug(f"[Resolver] Error inspecting submission media fields: {e}")
        return None

    # ---------- Network helpers ----------

    @staticmethod
    async def _get_session() -> aiohttp.ClientSession:
        return await GlobalSession.get()

    @staticmethod
    def _default_headers() -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (resolver; +https://github.com/yourbot)",
            # NSFW interstitials are gated by this cookie; it’s safe to set.
            "Cookie": "over18=1",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }

    @staticmethod
    async def fetch_post_html(url: str, session: Optional[aiohttp.ClientSession] = None) -> str:
        session = session or await RedditVideoResolver._get_session()
        async with session.get(url, headers=RedditVideoResolver._default_headers(), allow_redirects=True) as resp:
            return await resp.text()

    @staticmethod
    async def fetch_post_json(post_id: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Public JSON for a post (no auth). raw_json=1 to avoid HTML entities.
        """
        session = session or await RedditVideoResolver._get_session()
        url = f"https://www.reddit.com/comments/{post_id}.json?raw_json=1"
        try:
            async with session.get(url, headers=RedditVideoResolver._default_headers(), allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.debug(f"[Resolver] JSON fetch status {resp.status} for {post_id}")
                    return None
                return await resp.json(content_type=None)
        except Exception as e:
            logger.debug(f"[Resolver] JSON fetch exception for {post_id}: {e}")
            return None

    # ---------- Extraction from HTML/JSON strings ----------

    @staticmethod
    def _extract_vreddit_from_html_like(text: str) -> Optional[str]:
        """
        Find https://v.redd.it/<id> in either plain or JSON-escaped form.
        """
        # Plain
        m = re.search(r"(https://v\.redd\.it/[A-Za-z0-9]+)", text)
        if m:
            return m.group(1)
        # JSON-escaped (https:\/\/v.redd.it\/abc123)
        m = re.search(r"https:\\/\\/v\.redd\.it\\/([A-Za-z0-9]+)", text)
        if m:
            return f"https://v.redd.it/{m.group(1)}"
        return None

    @classmethod
    def extract_vreddit_base_from_json(cls, data: List[Dict[str, Any]]) -> Optional[str]:
        """
        Walk the JSON looking for reddit_video fields or any v.redd.it URL.
        """
        try:
            # Comments JSON returns a list: [postListing, commentsListing]
            if not isinstance(data, list) or not data:
                return None

            def walk(obj: Any) -> Optional[str]:
                if isinstance(obj, dict):
                    # Direct reddit_video block
                    if "reddit_video" in obj and isinstance(obj["reddit_video"], dict):
                        url = cls._extract_vreddit_from_reddit_video(obj["reddit_video"])
                        if url:
                            return url
                    # Any string field containing v.redd.it
                    for v in obj.values():
                        found = walk(v)
                        if found:
                            return found
                elif isinstance(obj, list):
                    for item in obj:
                        found = walk(item)
                        if found:
                            return found
                elif isinstance(obj, str):
                    maybe = cls._extract_vreddit_from_html_like(obj)
                    if maybe:
                        return maybe
                return None

            return walk(data)
        except Exception as e:
            logger.debug(f"[Resolver] JSON parse error: {e}")
            return None

    # ---------- Existing DASH probing ----------

    @classmethod
    async def find_dash_url(cls, base_url: str, session: Optional[aiohttp.ClientSession] = None) -> str:
        session = session or await cls._get_session()
        for res in RedditVideoConfig.DASH_RESOLUTIONS:
            url = f"{base_url}/DASH_{res}.mp4"
            try:
                async with session.head(url, headers=cls._default_headers(), timeout=5) as resp:
                    if resp.status == 200:
                        return url
            except aiohttp.ClientError as e:
                logger.debug(f"[Resolver] DASH_{res} not accessible: {e}")
            except Exception as e:
                logger.error(f"[Resolver] Unexpected error while checking DASH_{res}: {e}", exc_info=True)
        return ""

    # ---------- Public entry points ----------

    @staticmethod
    def slugify_title(title: str) -> str:
        title = title.lower()
        title = re.sub(r"[^a-z0-9\s]", "", title)
        title = re.sub(r"\s+", "_", title)
        return title.strip("_")

    @classmethod
    def build_mobile_url(cls, subreddit: str, post_id: str, title: str) -> str:
        slug = cls.slugify_title(title or "")
        return f"https://old.reddit.com/r/{subreddit}/comments/{post_id}/{slug}/"  # use old.reddit: simpler markup

    @classmethod
    async def resolve_video(cls, post: Submission, session: Optional[aiohttp.ClientSession] = None) -> Optional[str]:
        """
        Resolve a reddit-hosted (v.redd.it) video for a Submission.
        Always return '<tmpdir>/reddit_<postid>.mp4' (no '_v' suffix), with audio muxed in
        when available; otherwise return the video-only stream under the same canonical name.
        """
        try:
            session = session or await cls._get_session()

            # ---------- find base v.redd.it ----------
            base_url = cls._extract_vreddit_from_submission(post)
            if base_url:
                logger.info(f"[Resolver] Using v.redd.it from submission fields: {base_url}")

            if not base_url:
                data = await cls.fetch_post_json(post.id, session)
                if data:
                    base_url = cls.extract_vreddit_base_from_json(data)
                    if base_url:
                        logger.info(f"[Resolver] Found v.redd.it via JSON: {base_url}")

            if not base_url:
                html = await cls.fetch_post_html(
                    cls.build_mobile_url(getattr(post.subreddit, "display_name", "unknown"), post.id, post.title or ""),
                    session,
                )
                base_url = cls._extract_vreddit_from_html_like(html)
                if base_url:
                    logger.info(f"[Resolver] Found v.redd.it via HTML: {base_url}")

            if not base_url:
                logger.warning(f"[Resolver] No v.redd.it URL found for post {post.id}")
                return None

            # ---------- choose best DASH video ----------
            dash_video_url = await cls.find_dash_url(base_url, session)
            if not dash_video_url:
                logger.warning(f"[Resolver] No DASH video variant found at {base_url}")
                return None

            # ---------- paths (canonical out name; tmp for staging) ----------
            temp_dir = TempFileManager.create_temp_dir("reddit_video_")
            canonical_out = os.path.join(temp_dir, f"reddit_{post.id}.mp4")
            video_tmp     = os.path.join(temp_dir, f"reddit_{post.id}__video_tmp.mp4")
            audio_tmp     = os.path.join(temp_dir, f"reddit_{post.id}__audio_tmp.m4a")

            # small helpers
            def _headers() -> Dict[str, str]:
                return cls._default_headers()

            async def _probe(url: str) -> bool:
                # Some CDNs 403 on HEAD; try HEAD then GET.
                try:
                    async with session.head(url, headers=_headers(), timeout=5) as r:
                        if r.status == 200:
                            return True
                except Exception:
                    pass
                try:
                    async with session.get(url, headers=_headers(), timeout=5) as r:
                        return r.status == 200
                except Exception:
                    return False

            async def _download(url: str, dst: str) -> Optional[str]:
                try:
                    async with session.get(url, headers=_headers()) as r:
                        if r.status != 200:
                            logger.info(f"[Resolver] Download got {r.status} for {url}")
                            return None
                        with open(dst, "wb") as f:
                            while True:
                                chunk = await r.content.read(1024 * 1024)
                                if not chunk:
                                    break
                                f.write(chunk)
                    return dst
                except Exception as e:
                    logger.debug(f"[Resolver] Download error for {url}: {e}")
                    return None

            # ---------- download video ----------
            v_path = await _download(dash_video_url, video_tmp)
            if not v_path:
                return None
            logger.info(f"[Resolver] Downloaded video track to {v_path}")

            # ---------- try audio, then mux ----------
            audio_candidates = [
                f"{base_url}/DASH_audio.mp4",
                f"{base_url}/DASH_audio.mp4?source=fallback",
            ]
            audio_url = None
            for cand in audio_candidates:
                if await _probe(cand):
                    audio_url = cand
                    break

            if audio_url:
                a_path = await _download(audio_url, audio_tmp)
                if a_path:
                    try:
                        from redditcommand.utils.media_utils import AVMuxer
                        muxed = await AVMuxer.mux_av(v_path, a_path, canonical_out)
                    except Exception as e:
                        logger.warning(f"[Resolver] Mux exception: {e}")
                        muxed = None

                    if muxed:
                        # clean up temps
                        try:
                            TempFileManager.cleanup_file(video_tmp)
                            TempFileManager.cleanup_file(audio_tmp)
                        except Exception:
                            pass
                        logger.info(f"[Resolver] Successfully muxed to {canonical_out}")
                        return canonical_out
                    else:
                        logger.warning("[Resolver] Mux failed; will return video-only under canonical name.")
                else:
                    logger.info(f"[Resolver] Audio detected but failed to download: {audio_url}")
            else:
                logger.info(f"[Resolver] No audio available at {base_url}/DASH_audio.mp4")

            # ---------- no audio (or mux failed): rename tmp video -> canonical ----------
            try:
                if v_path != canonical_out:
                    os.replace(v_path, canonical_out)  # atomic on same FS
            except Exception as e:
                logger.error(f"[Resolver] Failed to rename video to canonical name: {e}", exc_info=True)
                return v_path  # last resort

            try:
                TempFileManager.cleanup_file(audio_tmp)
            except Exception:
                pass

            logger.info(f"[Resolver] Returning video-only (canonical): {canonical_out}")
            return canonical_out

        except Exception as e:
            logger.error(f"[Resolver] Error during video resolution for post {post.id}: {e}", exc_info=True)
            return None
