import asyncio
from typing import List, Optional

from asyncpraw import Reddit

from redditcommand.config import RedditClientManager
from redditcommand.utils.log_manager import LogManager
from redditcommand.fetch import MediaPostFetcher
from redditcommand.utils.session import GlobalSession

from reddit_mass_downloader.local_media_handler import LocalMediaSaver

logger = LogManager.setup_main_logger()


class DownloaderPipeline:
    """
    Pulls posts using the existing redditcommand fetch layer (no changes there),
    then saves media locally with LocalMediaSaver (handles galleries + top comment).
    """

    def __init__(
        self,
        subreddits: List[str],
        search_terms: Optional[List[str]] = None,
        sort: str = "hot",
        time_filter: Optional[str] = None,
        media_type: Optional[str] = None,
        media_count: int = 1,
    ):
        self.subreddits = subreddits
        self.search_terms = search_terms or []
        self.sort = sort
        self.time_filter = time_filter
        self.media_type = media_type
        self.media_count = media_count

        self.reddit: Optional[Reddit] = None
        self.fetcher: Optional[MediaPostFetcher] = None

    async def run(self) -> int:
        saved_count = 0
        try:
            # Reuse the same client as the bot stack
            self.reddit = await RedditClientManager.get_client()
            self.fetcher = MediaPostFetcher()
            await self.fetcher.init_client()

            posts = await self.fetcher.fetch_from_subreddits(
                subreddit_names=self.subreddits,
                search_terms=self.search_terms,
                sort=self.sort,
                time_filter=self.time_filter,
                media_type=self.media_type,
                media_count=self.media_count,
                update=None,  # no Telegram Update in CLI
                invalid_subreddits=set(),
                processed_urls=set(),
            )

            if not posts:
                logger.info("No posts fetched by downloader pipeline.")
                return 0

            saver = LocalMediaSaver(self.reddit)
            await saver._ensure_ready()

            # Save sequentially to keep logs/user output tidy
            for post in posts:
                try:
                    path = await saver.save_post(post)
                    if path:
                        saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving post {getattr(post, 'id', '?')}: {e}", exc_info=True)

            return saved_count

        finally:
            try:
                await GlobalSession.close()
            except Exception:
                pass
            try:
                if self.reddit is not None and hasattr(self.reddit, "close"):
                    await self.reddit.close()
            except Exception:
                pass
