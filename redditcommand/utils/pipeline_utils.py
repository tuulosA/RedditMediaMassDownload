# redditcommand/utils/pipeline_utils.py

import asyncio
from typing import List, Callable, Awaitable

from telegram import Update
from asyncpraw import Reddit
from asyncpraw.models import Submission

from redditcommand.config import Messages
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class PipelineHelper:
    @staticmethod
    async def initialize_client(client_initializer: Callable[[], Awaitable[Reddit]]) -> Reddit:
        try:
            return await asyncio.wait_for(client_initializer(), timeout=30)
        except asyncio.TimeoutError:
            raise RuntimeError("Reddit client initialization timed out.")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Reddit client: {e}")

    @staticmethod
    async def _safe_reply(update: Update, message: str) -> None:
        """
        Try update.message.reply_text first, then update.reply_text.
        Log a warning if neither is available or sending fails.
        """
        target = getattr(update, "message", update)
        if hasattr(target, "reply_text"):
            try:
                await target.reply_text(message)
                return
            except Exception as e:
                logger.warning(f"Failed to send message to user: {e}")
        else:
            logger.warning("No reply_text available on Update object to notify user.")

    @staticmethod
    async def notify_user(update: Update, message: str) -> None:
        logger.info(f"Notifying user: {message}")
        await PipelineHelper._safe_reply(update, message)

    @staticmethod
    async def validate_subreddits(update: Update, reddit_instance: Reddit, subreddit_names: List[str]) -> List[str]:
        valid, invalid = [], []

        for name in subreddit_names:
            if name.lower() == "random":
                valid.append(name)
                continue
            try:
                subreddit = await reddit_instance.subreddit(name)
                await subreddit.load()
                valid.append(name)
            except Exception as e:
                logger.warning(f"Subreddit {name} is invalid or inaccessible: {e}")
                invalid.append(name)

        if invalid and not valid:
            await PipelineHelper.notify_user(update, Messages.NO_VALID_SUBREDDITS)
            logger.warning(f"All subreddits invalid: {', '.join(invalid)}")
        else:
            logger.info(f"Valid subreddits: {', '.join(valid)}")

        return valid

    @staticmethod
    def log_post_summary(posts: List[Submission]) -> None:
        if posts:
            logger.info("Pipeline Summary:")
            for post in posts:
                logger.info(f"Title: {post.title}, URL: {post.url}")
        else:
            logger.info("No posts were processed.")

    @staticmethod
    async def notify_completion(update: Update, total_processed: int, media_count: int, posts: List[Submission]) -> None:
        if total_processed == 0:
            await PipelineHelper.notify_user(update, Messages.NO_POSTS_FOUND)
        elif total_processed < media_count:
            await PipelineHelper.notify_user(
                update,
                Messages.PARTIAL_RESULTS.format(processed=total_processed, requested=media_count)
            )

        PipelineHelper.log_post_summary(posts)
        logger.info("Pipeline completed successfully.")
