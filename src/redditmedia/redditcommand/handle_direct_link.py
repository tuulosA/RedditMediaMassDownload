# redditmedia/redditcommand/handle_direct_link.py

import os
import re
import aiohttp
import asyncio
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from typing import Optional
from redgifs.aio import API as RedGifsAPI
from redgifs.errors import HTTPException as RedgifsHTTPError
from asyncpraw.models import Submission

from .config import RedditVideoConfig

from .utils.log_manager import LogManager
from .utils.tempfile_utils import TempFileManager
from .utils.media_utils import MediaDownloader, AVMuxer
from .utils.reddit_video_resolver import RedditVideoResolver
from .utils.session import GlobalSession
from .utils.name_utils import (
    temp_paths_for_vreddit,
    temp_path_for_generic,
    yt_dlp_output_template,
)


logger = LogManager.setup_main_logger()


class MediaLinkResolver:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def init(self):
        self.session = await GlobalSession.get()

    # ---- NEW: normalize incoming URLs (esp. Redgifs) -------------------------
    @staticmethod
    def _normalize_media_url(u: str) -> str:
        """
        Normalize common media hosts to canonical forms (drop fragments/queries).
        For Redgifs, force: https://www.redgifs.com/watch/<slug>
        """
        if not u:
            return u

        # quick short-circuit if not Redgifs
        if "redgifs.com" not in u:
            parts = urlsplit(u)
            # drop fragment only by default; keep query (some hosts need it)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))

        # Redgifs: extract slug from /watch/<id> or /ifr/<id> (ignore query/fragment)
        parts = urlsplit(u)
        path = parts.path or "/"
        m = re.search(r"/(?:watch|ifr)/([a-z0-9]+)", path, flags=re.I)
        if m:
            slug = m.group(1)
        else:
            # fall back: last path segment (e.g., https://redgifs.com/<slug>)
            segs = [p for p in path.split("/") if p]
            slug = segs[-1] if segs else ""

        if not slug:
            # no usable slug; at least drop fragment/query
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

        return f"https://www.redgifs.com/watch/{slug}"

    async def resolve(self, media_url: str, post: Optional[Submission] = None) -> Optional[str]:
        if self.session is None:
            await self.init()

        # Normalize once up front
        media_url = self._normalize_media_url(media_url)

        try:
            if "v.redd.it" in media_url:
                return await self._v_reddit(media_url, post)
            if "imgur.com" in media_url:
                return await self._imgur(media_url, post)
            if "streamable.com" in media_url:
                return await self._streamable(media_url, post)
            if "redgifs.com" in media_url:
                return await self._redgifs(media_url, post)
            if any(domain in media_url for domain in ["kick.com", "twitch.tv", "youtube.com", "youtu.be", "x.com", "twitter.com"]):
                return await self._yt_dlp(media_url, post)
            if media_url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".mp4")):
                return media_url

            logger.warning(f"Unsupported URL format: {media_url}")

        # >>> allow “not found” style errors to bubble so callers can report them
        except FileNotFoundError:
            raise

        except Exception as e:
            logger.error(f"Error resolving direct link for {media_url}: {e}", exc_info=True)
        return None

    async def _v_reddit(self, media_url: str, post: Optional[Submission]) -> Optional[str]:
        """
        Download best available DASH video + audio when present, mux to a single file,
        and ALWAYS return 'reddit_{post_id}.mp4' (no _v suffix for mute videos).
        Tries:
          1) Direct DASH video
          2) DASH_audio.mp4 (with headers) and DASH_audio.mp4?source=fallback
          3) Fallback to yt-dlp on the v.redd.it URL to merge bestvideo+bestaudio
        """

        base = media_url.rstrip("/")
        dash_video_urls = [f"{base}/DASH_{res}.mp4" for res in RedditVideoConfig.DASH_RESOLUTIONS]
        dash_audio_urls = [f"{base}/DASH_audio.mp4", f"{base}/DASH_audio.mp4?source=fallback"]

        def _headers():
            # Same idea as your resolver: avoid 403/NSFW interstitials
            return {
                "User-Agent": "Mozilla/5.0 (resolver; +https://github.com/yourbot)",
                "Cookie": "over18=1",
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            }

        async def _probe_audio_with_headers(url: str) -> bool:
            # Try HEAD first, then tiny GET if origin dislikes HEAD
            try:
                async with self.session.head(url, headers=_headers(), timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            try:
                async with self.session.get(url, headers=_headers(), timeout=5) as resp:
                    return resp.status == 200
            except Exception:
                return False

        async def _download_audio_with_headers(url: str, out_path: str) -> Optional[str]:
            try:
                async with self.session.get(url, headers=_headers()) as resp:
                    if resp.status != 200:
                        return None
                    with open(out_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                return out_path
            except Exception:
                return None

        # --- main flow ---
        try:
            # 1) Choose highest working DASH video
            video_url = await MediaDownloader.find_first_valid_url(dash_video_urls, session=self.session)
            if not video_url:
                logger.info(f"No valid DASH video for {media_url}")
                return None

            # ensure we have a post for naming
            if post is None:
                class _Stub: pass
                post = _Stub()
                setattr(post, "id", TempFileManager.extract_post_id_from_url(media_url) or "unknown")
                setattr(post, "title", "video")
                class _Sub: pass
                sub = _Sub(); setattr(sub, "display_name", "unknown")
                setattr(post, "subreddit", sub)

            out_path, video_tmp, audio_tmp = temp_paths_for_vreddit(post, ext=".mp4")

            # 2) Download video
            video_tmp = await MediaDownloader.download_file(video_url, video_tmp, session=self.session)
            if not video_tmp:
                return None

            # 3) Try to detect + fetch audio directly (with headers; try both URLs)
            audio_ok = False
            audio_url_found = None
            for au in dash_audio_urls:
                if await _probe_audio_with_headers(au):
                    audio_url_found = au
                    audio_ok = True
                    break

            if audio_ok and audio_url_found:
                a_path = await _download_audio_with_headers(audio_url_found, audio_tmp)
                if a_path:
                    muxed = await AVMuxer.mux_av(video_tmp, a_path, out_path)
                    if muxed:
                        try:
                            TempFileManager.cleanup_file(video_tmp)
                            TempFileManager.cleanup_file(audio_tmp)
                        except Exception:
                            pass
                        return out_path
                    else:
                        logger.warning("vreddit mux failed after audio download; will try yt-dlp fallback.")

            # 4) Fallback: yt-dlp
            try:
                ytdlp_path = await self._download_with_ytdlp(media_url, post)
                if ytdlp_path and os.path.exists(ytdlp_path):
                    if ytdlp_path != out_path:
                        try:
                            os.replace(ytdlp_path, out_path)
                        except Exception:
                            out_path = ytdlp_path
                    try:
                        TempFileManager.cleanup_file(video_tmp)
                        TempFileManager.cleanup_file(audio_tmp)
                    except Exception:
                        pass
                    return out_path
            except Exception as e:
                logger.debug(f"yt-dlp fallback failed for vreddit: {e}")

            # 5) Final fallback: video-only
            try:
                if video_tmp != out_path:
                    os.replace(video_tmp, out_path)
            except Exception as e:
                logger.error(f"Failed to rename video-only to canonical name: {e}", exc_info=True)
                return video_tmp

            try:
                TempFileManager.cleanup_file(audio_tmp)
            except Exception:
                pass

            logger.info("No DASH audio or mux possible; returning video-only.")
            return out_path

        except Exception as e:
            logger.error(f"Error resolving v.redd.it media: {e}", exc_info=True)
        return None

    async def _imgur(self, media_url: str, post: Optional[Submission]) -> Optional[str]:
        """
        Prefer yt-dlp for Imgur so that, when the source has audio, we fetch
        a progressive muxed file. If yt-dlp fails and the Reddit post actually
        has a reddit-hosted mirror, fall back to the resolver.
        """
        try:
            # Ensure we have a post object for naming (subreddit_title_id), like other handlers.
            is_stub = False
            if post is None:
                is_stub = True
                class _Stub: pass
                post = _Stub()
                setattr(post, "id", TempFileManager.extract_post_id_from_url(media_url) or "unknown")
                setattr(post, "title", "video")
                class _Sub: pass
                sub = _Sub(); setattr(sub, "display_name", "unknown")
                setattr(post, "subreddit", sub)

            # Use yt-dlp with our centralized output template (subreddit_title_id.mp4)
            ytdlp_file = await self._download_with_ytdlp(media_url, post)
            if ytdlp_file:
                return ytdlp_file

            # Only try the reddit-hosted fallback when we have a real Submission
            if not is_stub and isinstance(post, Submission):
                fallback = await RedditVideoResolver.resolve_video(post)
                if fallback:
                    return fallback

            logger.warning(f"Imgur: yt-dlp and resolver fallback both failed for {media_url}")
        except Exception as e:
            logger.error(f"Error processing Imgur: {e}", exc_info=True)
        return None

    async def _streamable(self, media_url: str, post: Optional[Submission]) -> Optional[str]:
        try:
            base = media_url.split("?")[0].rstrip("/")
            parts = [p for p in base.split("/") if p]
            shortcode = parts[-1] if parts else ""
            if not shortcode or any(c in shortcode for c in "/?#&"):
                logger.warning(f"Invalid Streamable shortcode from URL: {media_url}")
                return None

            api_url = f"https://api.streamable.com/videos/{shortcode}"
            async with self.session.get(api_url) as resp:
                if resp.status != 200:
                    logger.info(f"Streamable API returned {resp.status} for {shortcode}")
                    return None
                data = await resp.json()

            files = data.get("files", {}) or {}
            path = None
            if "mp4" in files and isinstance(files["mp4"], dict):
                path = files["mp4"].get("url")
            if not path and "mp4-mobile" in files and isinstance(files["mp4-mobile"], dict):
                path = files["mp4-mobile"].get("url")

            if not path:
                logger.info(f"No downloadable file in Streamable response for {shortcode}")
                return None

            resolved = f"https:{path}" if path and not path.startswith("http") else path
            if not resolved:
                return None

            # Generic temp file using subreddit_title_id.ext
            # Ensure `post` exists; if not, create a tiny stub (same idea as above)
            if post is None:
                class _Stub: pass
                post = _Stub()
                setattr(post, "id", TempFileManager.extract_post_id_from_url(media_url) or "unknown")
                setattr(post, "title", "video")
                class _Sub: pass
                sub = _Sub(); setattr(sub, "display_name", "unknown")
                setattr(post, "subreddit", sub)

            file_path = temp_path_for_generic(post, ext=".mp4", prefix="reddit_streamable_")   # in _streamable
            # or prefix="reddit_redgifs_" in _redgifs
            # or prefix="reddit_imgur_" in _imgur (if you need a direct download; yt-dlp block below handles its own)

            return await MediaDownloader.download_file(resolved, file_path, session=self.session)
        except Exception as e:
            logger.error(f"Streamable error: {e}", exc_info=True)
        return None

    async def _redgifs(self, media_url: str, post: Optional[Submission]) -> Optional[str]:
        """
        Resolve a Redgifs URL robustly:
        - Normalize and extract the gif id
        - Login once
        - Retry get_gif() on transient statuses (429, 5xx, 503 AuthorizationServiceUnavailable)
        - Re-login on 401/403 once
        - Treat 404/410 as missing (raise FileNotFoundError so caller can report)
        - On repeated transient failures, return None (skip post)
        """
        try:
            # Normalize again defensively (cheap)
            media_url = self._normalize_media_url(media_url)

            parts = urlsplit(media_url)
            path = parts.path or "/"

            # Accept /watch/<id>, /ifr/<id>, or /<id>
            m = re.search(r"/(?:watch|ifr)/([a-z0-9]+)", path, flags=re.I)
            if m:
                gif_id = m.group(1)
            else:
                segs = [p for p in path.split("/") if p]
                gif_id = segs[-1] if segs else ""

            if not gif_id or any(c in gif_id for c in "/?#&"):
                logger.warning(f"Invalid RedGifs id from URL: {media_url}")
                return None

            api = RedGifsAPI()
            try:
                await api.login()

                max_retries = 5
                backoff_base = 1.5
                gif = None

                for attempt in range(max_retries):
                    try:
                        gif = await api.get_gif(gif_id)
                        break  # success
                    except RedgifsHTTPError as e:
                        # status is not always present; try both spots
                        status = getattr(e, "status", None) or getattr(getattr(e, "response", None), "status", None)
                        msg = (str(e) or "").lower()

                        # Permanent: deleted / not found
                        if status == 410 or "gifdeleted" in msg or "gone" in msg:
                            raise FileNotFoundError("redgifs: deleted (410)") from e
                        if status == 404:
                            raise FileNotFoundError("redgifs: not found (404)") from e

                        # Token/perm hiccup: try re-login once per failure then retry
                        if status in (401, 403):
                            try:
                                await api.login()
                            except Exception:
                                pass
                            await asyncio.sleep(1.0)
                            continue

                        # Transient: rate/servers/down
                        if status in (429, 500, 502, 503, 504) or status is None:
                            await asyncio.sleep(min(30.0, (backoff_base ** attempt)))
                            continue

                        # Unknown / non-retryable → skip this post
                        logger.warning("Redgifs non-retryable error %s on %s: %s", status, gif_id, e)
                        return None
                    except Exception as e:
                        # Network/JSON/etc — treat as transient
                        await asyncio.sleep(min(30.0, (backoff_base ** attempt)))

                if gif is None:
                    logger.warning("Redgifs still failing after %d retries; skipping %s", max_retries, gif_id)
                    return None

                # Choose a downloadable URL
                url = (
                    getattr(gif.urls, "hd", None)
                    or getattr(gif.urls, "sd", None)
                    or getattr(gif.urls, "file_url", None)
                )
                if not url:
                    raise FileNotFoundError("redgifs: no downloadable URL")

                # Ensure `post` exists for naming
                if post is None:
                    class _Stub: pass
                    post = _Stub()
                    setattr(post, "id", TempFileManager.extract_post_id_from_url(media_url) or "unknown")
                    setattr(post, "title", "video")
                    class _Sub: pass
                    sub = _Sub(); setattr(sub, "display_name", "unknown")
                    setattr(post, "subreddit", sub)

                file_path = temp_path_for_generic(post, ext=".mp4", prefix="reddit_redgifs_")
                return await MediaDownloader.download_file(url, file_path, session=self.session)

            finally:
                try:
                    await api.close()
                except Exception:
                    pass

        except FileNotFoundError:
            # allow 404/410 to bubble to caller (so the pipeline can log a clean "not found")
            raise
        except Exception as e:
            logger.error(f"RedGifs error: {e}", exc_info=True)
        return None

    async def _yt_dlp(self, media_url: str, post: Optional[Submission]) -> Optional[str]:
        # Ensure a post object exists (for subreddit_title_id naming)
        if post is None:
            class _Stub: pass
            post = _Stub()
            setattr(post, "id", TempFileManager.extract_post_id_from_url(media_url) or "unknown")
            setattr(post, "title", "video")
            class _Sub: pass
            sub = _Sub(); setattr(sub, "display_name", "unknown")
            setattr(post, "subreddit", sub)

        return await self._download_with_ytdlp(media_url, post)

    async def _download_with_ytdlp(self, url: str, post: Submission) -> Optional[str]:
        """
        Download a video with yt-dlp to a temp directory using an output template.
        Forces an mp4 merge/remux and handles timeouts. Returns the final file path
        or None on failure.
        """
        # get "<temp_dir>", "<temp_dir>/<subreddit_title_id>" (no extension)
        temp_dir, out_no_ext = yt_dlp_output_template(post, ext="mp4", prefix="ytdlp_video_")
        output_tpl = f"{out_no_ext}.%(ext)s"

        command = [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--no-part",
            "--no-mtime",
            "--no-playlist",
            "--no-check-certificate",
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "--merge-output-format", "mp4",
            "--output", output_tpl,
            url,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=getattr(RedditVideoConfig, "YTDLP_TIMEOUT", 600),
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error("yt-dlp timed out")
                TempFileManager.cleanup_file(temp_dir)
                return None

            if process.returncode != 0:
                err = (stderr.decode(errors="ignore") or "").strip()
                logger.error(f"yt-dlp failed: {err}")
                TempFileManager.cleanup_file(temp_dir)
                return None

            candidates = [f"{out_no_ext}.mp4", f"{out_no_ext}.m4v"]
            for cand in candidates:
                if os.path.exists(cand):
                    return cand
            base = Path(out_no_ext).name
            for name in os.listdir(temp_dir):
                if name.startswith(base):
                    p = os.path.join(temp_dir, name)
                    if os.path.isfile(p):
                        return p

            logger.error("yt-dlp succeeded but no output file was found")
        except Exception as e:
            logger.error(f"yt-dlp exception: {e}", exc_info=True)

        TempFileManager.cleanup_file(temp_dir)
        return None
