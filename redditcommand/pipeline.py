# redditcommand/pipeline.py

import random
import asyncio
from typing import List, Optional

from telegram import Update
from asyncpraw import Reddit

from redditcommand.utils.log_manager import LogManager
from redditcommand.config import RedditClientManager, MediaConfig, RetryConfig, RedditDefaults, PipelineConfig
from redditcommand.utils.pipeline_utils import PipelineHelper
from redditcommand.fetch import MediaPostFetcher
from redditcommand.media_handler import MediaProcessor

logger = LogManager.setup_main_logger()


class RedditMediaPipeline:
    def __init__(
        self,
        update: Update,
        subreddit_names: List[str],
        search_terms: List[str],
        sort: str = RedditDefaults.DEFAULT_SORT_NO_TIME_FILTER,
        time_filter: Optional[str] = None,
        media_count: int = 1,
        media_type: Optional[str] = None,
        include_comments: bool = False,
        include_flair: bool = False,
        include_title: bool = False,
        fetch_semaphore_limit: int = MediaConfig.DEFAULT_SEMAPHORE_LIMIT,
    ):
        self.update = update
        self.subreddit_names = subreddit_names
        self.search_terms = search_terms
        self.sort = sort
        self.time_filter = time_filter
        self.media_count = media_count
        self.media_type = media_type
        self.include_comments = include_comments
        self.include_flair = include_flair
        self.include_title = include_title
        self.semaphore_limit = fetch_semaphore_limit

        self.processed_urls = set()
        self.successfully_sent_posts = []
        self.total_processed = 0
        self.backoff = PipelineConfig.INITIAL_BACKOFF_SECONDS

        self.reddit: Optional[Reddit] = None
        self.fetcher: Optional[MediaPostFetcher] = None

    async def run(self):
        logger.info(f"Starting pipeline for subreddits: {', '.join(self.subreddit_names)}")

        try:
            self.reddit = await PipelineHelper.initialize_client(RedditClientManager.get_client)
            valid_subreddits = await PipelineHelper.validate_subreddits(self.update, self.reddit, self.subreddit_names)

            if not valid_subreddits and "random" not in self.subreddit_names:
                await PipelineHelper.notify_user(self.update, "No valid or accessible subreddits provided.")
                logger.warning("No valid subreddits to proceed with.")
                return

            self.fetcher = MediaPostFetcher(asyncio.Semaphore(self.semaphore_limit))
            await self.fetcher.init_client()

            async with MediaProcessor(self.reddit, self.update) as processor:
                for attempt in range(1, RetryConfig.RETRY_ATTEMPTS + 1):
                    remaining = self.media_count - self.total_processed
                    if remaining <= 0:
                        break

                    logger.info(f"Attempt {attempt}: fetching {remaining} post(s)")
                    posts = await self.fetcher.fetch_from_subreddits(
                        subreddit_names=valid_subreddits,
                        search_terms=self.search_terms,
                        sort=self.sort,
                        time_filter=self.time_filter,
                        media_type=self.media_type,
                        media_count=remaining,
                        update=self.update,
                        processed_urls=self.processed_urls,
                    )

                    if not posts:
                        sleep_duration = self.backoff * random.uniform(0.5, 1.5)
                        logger.warning(f"No new media found. Retrying after {sleep_duration:.2f}s.")
                        await asyncio.sleep(sleep_duration)
                        self.backoff = min(self.backoff * PipelineConfig.BACKOFF_MULTIPLIER, PipelineConfig.MAX_BACKOFF_SECONDS)
                        continue

                    self.processed_urls.update(post.url for post in posts)
                    if len(self.processed_urls) > PipelineConfig.MAX_PROCESSED_URLS:
                        logger.warning("Processed URL cache exceeded 10k entries. Resetting.")
                        self.processed_urls.clear()

                    sent = await processor.process_batch(
                        posts,
                        include_comments=self.include_comments,
                        include_flair=self.include_flair,
                        include_title=self.include_title
                    )
                    self.successfully_sent_posts.extend(sent)
                    self.total_processed += len(sent)

            await PipelineHelper.notify_completion(
                self.update,
                self.total_processed,
                self.media_count,
                self.successfully_sent_posts
            )

        except RuntimeError as e:
            logger.error(f"Pipeline error: {e}")
            await PipelineHelper.notify_user(self.update, str(e))

        except Exception as e:
            logger.error("Unexpected pipeline error", exc_info=True)
            await PipelineHelper.notify_user(self.update, "An unexpected error occurred.")
