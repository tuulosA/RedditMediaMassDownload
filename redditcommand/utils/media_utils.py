# redditcommand/utils/media_utils.py

import os
import asyncio
import aiohttp

from typing import Optional, Union
from asyncpraw import Reddit
from asyncpraw.models import Submission, Comment
from telegram import InputFile, Bot, Update
from PIL import Image

from urllib.parse import urlparse

from redditcommand.utils.tempfile_utils import TempFileManager
from redditcommand.config import TimeoutConfig, CommentFilterConfig
from redditcommand.utils.session import GlobalSession
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class MediaSender:
    @staticmethod
    def determine_type_and_send(file_path: str):
        ext = os.path.splitext(urlparse(file_path).path)[1].lower()
        if ext in (".mp4"):
            return MediaSender.send_video
        if ext in (".jpg", ".jpeg", ".png"):
            return MediaSender.send_photo

        logger.warning(f"Unsupported media type for: {file_path}")
        return None

    @staticmethod
    def resolve_target(target):
        if isinstance(target, Update):
            return target.get_bot(), target.effective_chat.id
        elif isinstance(target, tuple) and len(target) == 2:
            return target
        else:
            bot = Bot(token=os.getenv("TELEGRAM_API_KEY"))
            chat_id = int(os.getenv("TELEGRAM_CHAT_ID"))
            return bot, chat_id

    @staticmethod
    async def send_video(file_path: str, target, caption: Optional[str] = None):
        bot, chat_id = MediaSender.resolve_target(target)

        try:
            from cv2 import VideoCapture, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT
            cap = VideoCapture(file_path)
            width = int(cap.get(CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(CAP_PROP_FRAME_HEIGHT))
            cap.release()
        except Exception as e:
            logger.warning(f"OpenCV failed to get dimensions: {e}")
            width = height = 0

        if not (width and height):
            raise ValueError(f"Invalid video dimensions for: {file_path}")

        with open(file_path, "rb") as f:
            telegram_file = InputFile(f, filename=os.path.basename(file_path))
            await bot.send_video(
                chat_id=chat_id,
                video=telegram_file,
                width=width,
                height=height,
                supports_streaming=True,
                caption=caption,
            )

    @staticmethod
    async def send_photo(file_path: str, target, caption: Optional[str] = None):
        bot, chat_id = MediaSender.resolve_target(target)
        try:
            with Image.open(file_path) as img:
                if img.width < 10 or img.height < 10:
                    raise ValueError(f"Image too small: {img.width}x{img.height} - {file_path}")
        except Exception as e:
            logger.warning(f"Photo validation failed for {file_path}: {e}")
            return

        with open(file_path, "rb") as f:
            telegram_file = InputFile(f, filename=os.path.basename(file_path))
            await bot.send_photo(
                chat_id=chat_id,
                photo=telegram_file,
                caption=caption,
            )

class MediaUtils:
    @staticmethod
    async def convert_gif_to_mp4(gif_path: str) -> Optional[str]:
        if not await MediaUtils.validate_file(gif_path):
            logger.error(f"File not found for conversion: {gif_path}")
            return None

        mp4_path = gif_path.replace(".gif", ".mp4")
        command = [
            "ffmpeg", "-y", "-i", gif_path,
            "-movflags", "faststart",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            mp4_path,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info(f"Successfully converted: {mp4_path}")
                TempFileManager.cleanup_file(gif_path)
                return mp4_path
            logger.error(f"FFmpeg error: {stderr.decode()}")
        except Exception as e:
            logger.error(f"GIF to MP4 conversion error: {e}", exc_info=True)
        return None

    @staticmethod
    async def validate_file(file_path: str) -> bool:
        def check():
            return os.path.exists(file_path) and os.path.getsize(file_path) > 0

        is_valid = await asyncio.to_thread(check)
        logger.info(f"Validated file: {file_path}" if is_valid else f"Invalid file: {file_path}")
        return is_valid

    @staticmethod
    async def resolve_reddit_gallery(post_id: str, reddit: Reddit) -> Optional[str]:
        try:
            submission = await reddit.submission(id=post_id)
            await submission.load()

            gallery_order = submission.gallery_data["items"]
            media_metadata = submission.media_metadata

            for item in gallery_order:
                media_id = item["media_id"]
                media_info = media_metadata.get(media_id)
                if media_info and "s" in media_info and "u" in media_info["s"]:
                    return media_info["s"]["u"].replace("&amp;", "&")

            logger.warning(f"No valid image found in gallery for post {post_id}")
            return None
        except Exception as e:
            logger.error(f"Gallery resolution failed for post {post_id}: {e}", exc_info=True)
            return None

    @staticmethod
    async def fetch_top_comment(post: Submission, return_author: bool = False) -> Optional[Union[str, Comment]]:
        try:
            await post.comments()
            for c in post.comments.list():
                if c.body and not any(term in c.body.lower() for term in CommentFilterConfig.BLACKLIST_TERMS):
                    return c if return_author else c.body
        except Exception as e:
            logger.warning(f"Top comment fetch failed: {e}")
        return None

class MediaDownloader:
    @staticmethod
    async def find_first_valid_url(urls: list[str], session: Optional[aiohttp.ClientSession] = None) -> Optional[str]:
        session = session or await GlobalSession.get()
        for url in urls:
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"Valid URL found: {url}")
                        return url
            except aiohttp.ClientError:
                logger.debug(f"Failed to access: {url}")
        return None

    @staticmethod
    async def download_file(url: str, file_path: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[str]:
        session = session or await GlobalSession.get()
        try:
            timeout = aiohttp.ClientTimeout(total=TimeoutConfig.DOWNLOAD_TIMEOUT)
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    with open(file_path, 'wb') as f:
                        while chunk := await response.content.read(1024 * 1024):
                            f.write(chunk)
                    logger.info(f"Downloaded to {file_path}")
                    return file_path
                else:
                    logger.error(f"Download failed. Status: {response.status} for URL: {url}")
        except asyncio.TimeoutError:
            logger.error(f"Download timed out for URL: {url}")
        except Exception as e:
            logger.error(f"Error downloading from {url}: {e}", exc_info=True)
        return None
    
class CaptionBuilder:
    @staticmethod
    async def build(
        media: Submission,
        include_comments: bool,
        include_flair: bool,
        include_title: bool,
        max_length: int = 1024
    ) -> Optional[str]:
        parts = []
        if include_title and media.title:
            parts.append(media.title.strip())
        if include_flair and media.link_flair_text:
            parts.append(f"[{media.link_flair_text.strip()}]")
        if include_comments:
            top_comment = await MediaUtils.fetch_top_comment(media)
            if top_comment:
                parts.append(f"💬 {top_comment.strip()}")

        caption = "\n".join(parts)
        if len(caption) > max_length:
            logger.warning(f"Caption too long ({len(caption)}), truncating.")
            caption = caption[:max_length - 3] + "…"

        return caption or None
    
# --- ADD: simple A/V mux helper (no re-encode if possible) ---
class AVMuxer:
    @staticmethod
    async def mux_av(video_path: str, audio_path: str, out_path: str) -> Optional[str]:
        """
        Try to container-mux video+audio without re-encoding. If that fails,
        retry with a light re-encode to guarantee success.
        Returns out_path on success, else None.
        """
        import asyncio, os
        from redditcommand.utils.tempfile_utils import TempFileManager
        from redditcommand.utils.log_manager import LogManager
        logger = LogManager.setup_main_logger()

        # 1) Copy (fast)
        copy_cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            out_path
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *copy_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, err = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return out_path
            logger.warning(f"A/V copy mux failed, retrying with re-encode. ffmpeg: {err.decode(errors='ignore')[:300]}")
        except Exception as e:
            logger.warning(f"A/V copy mux exception, retrying with re-encode: {e}")

        # 2) Light re-encode fallback (keeps size modest)
        reenc_cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-vcodec", "libx264", "-crf", "23", "-preset", "fast",
            "-acodec", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out_path
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *reenc_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, err = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return out_path
            logger.error(f"A/V re-encode mux failed. ffmpeg: {err.decode(errors='ignore')[:300]}")
        except Exception as e:
            logger.error(f"A/V re-encode mux exception: {e}", exc_info=True)

        # Ensure we don’t leave a broken file behind
        TempFileManager.cleanup_file(out_path)
        return None

