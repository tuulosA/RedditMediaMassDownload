# redditcommand/media_handler.py

import asyncio
import aiohttp
import os
import urllib.parse

from typing import Optional
from telegram import Update
from telegram.error import TimedOut
from asyncpraw import Reddit
from asyncpraw.models import Submission

from .config import MediaConfig, RetryConfig
from .handle_direct_link import MediaLinkResolver

from redditcommand.utils.log_manager import LogManager
from redditcommand.utils.media_utils import MediaSender, MediaUtils, MediaDownloader, CaptionBuilder
from redditcommand.utils.compressor import Compressor
from redditcommand.utils.tempfile_utils import TempFileManager
from redditcommand.utils.session import GlobalSession

logger = LogManager.setup_main_logger()


class MediaProcessor:
    def __init__(self, reddit: Reddit, update: Update):
        self.reddit = reddit
        self.update = update
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = await GlobalSession.get()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Do not close GlobalSession here if it is shared
        self.session = None

    async def _maybe_notify_compression(self, file_path: str):
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except Exception:
            return

        # Notify only when it’s larger than the Telegram target limit but <= 100MB (our compressor hard cap)
        if size_mb > MediaConfig.MAX_FILE_SIZE_MB and size_mb <= 100:
            msg = f"Large file ({size_mb:.1f} MB). Compressing before sending..."
            try:
                # Support both shapes: update.message.reply_text(...) and update.reply_text(...)
                target = getattr(self.update, "message", self.update)
                if hasattr(target, "reply_text"):
                    await target.reply_text(msg)
            except Exception as e:
                logger.warning(f"Failed to send compression notice: {e}")

    async def process_batch(self, media_list, include_comments, include_flair, include_title):
        tasks = [
            self.process_single(media, include_comments, include_flair, include_title)
            for media in media_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [result for result in results if isinstance(result, Submission)]

    async def process_single(self, media, include_comments=False, include_flair=False, include_title=False):
        if not media.url:
            logger.warning("Media URL is missing or invalid.")
            return None

        try:
            caption = await CaptionBuilder.build(media, include_comments, include_flair, include_title)
            resolved_url = await self.resolve_media_url(media)
            if not resolved_url:
                return None

            file_path = await self.download_and_validate_media(resolved_url, media.id)
            if not file_path:
                return None

            if await self.upload_media(file_path, self.update, caption):
                return media

        except Exception as e:
            logger.error(f"Error processing media {media.url}: {e}", exc_info=True)
        return None

    async def resolve_media_url(self, post: Submission) -> Optional[str]:
        try:
            media_url = post.url
            if media_url.startswith("/tmp") and await MediaUtils.validate_file(media_url):
                return media_url
            if "gallery" in media_url:
                return await MediaUtils.resolve_reddit_gallery(media_url.split("/")[-1], self.reddit)

            resolver = MediaLinkResolver()
            await resolver.init()
            return await resolver.resolve(media_url, post=post)
        except Exception as e:
            logger.error(f"Error resolving media URL for post {post.id}: {e}", exc_info=True)
            return None

    async def download_and_validate_media(self, resolved_url: str, post_id: Optional[str] = None) -> Optional[str]:
        file_path = await self.download_file(resolved_url, post_id)
        if not file_path:
            return None

        await self._maybe_notify_compression(file_path)

        final_path = await Compressor.validate_and_compress(file_path, MediaConfig.MAX_FILE_SIZE_MB)
        if final_path:
            return final_path

        logger.warning(f"File too large after download: {file_path}")
        TempFileManager.cleanup_file(file_path)
        return None

    async def download_file(self, resolved_url: str, post_id: Optional[str]) -> Optional[str]:
        if os.path.isfile(resolved_url):
            return resolved_url if await MediaUtils.validate_file(resolved_url) else None

        if not resolved_url.startswith(("http://", "https://")):
            return resolved_url if await MediaUtils.validate_file(resolved_url) else None

        temp_dir = TempFileManager.create_temp_dir("reddit_media_")
        path = urllib.parse.urlparse(resolved_url).path
        ext = os.path.splitext(path)[1] or ".mp4"
        final_id = post_id or TempFileManager.extract_post_id_from_url(resolved_url) or "unknown"
        file_path = os.path.join(temp_dir, f"reddit_{final_id}{ext}")

        file_path = await MediaDownloader.download_file(resolved_url, file_path)
        if file_path and file_path.endswith(".gif"):
            converted = await MediaUtils.convert_gif_to_mp4(file_path)
            TempFileManager.cleanup_file(file_path)
            return converted

        return file_path

    async def upload_media(self, file_path: str, target, caption: Optional[str]) -> bool:
        handler = MediaSender.determine_type_and_send(file_path)
        if not handler:
            logger.warning(f"Unsupported media type: {file_path}")
            return False

        for attempt in range(RetryConfig.RETRY_ATTEMPTS):
            try:
                await handler(file_path, target, caption=caption)
                logger.info(f"Successfully sent media: {file_path}")
                TempFileManager.cleanup_file(file_path)
                return True
            except TimedOut:
                logger.warning(f"Timed out on attempt {attempt + 1} for file: {file_path}")
                TempFileManager.cleanup_file(file_path)
                return True
            except Exception as e:
                logger.error(f"Upload failed on attempt {attempt + 1}: {e}", exc_info=True)

        logger.error(f"Failed to send media after {RetryConfig.RETRY_ATTEMPTS} attempts: {file_path}")
        TempFileManager.cleanup_file(file_path)
        return False
