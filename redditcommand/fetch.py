# redditcommand/fetch.py

import asyncio
import random
from typing import Optional, List, Set
from asyncpraw.models import Submission

from .config import RedditClientManager, MediaConfig, RedditDefaults
from .filter_posts import MediaPostFilter
from redditcommand.utils.fetch_utils import RedditPostFetcher, FetchOrchestrator
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class MediaPostFetcher:
    def __init__(self, semaphore: Optional[asyncio.Semaphore] = None):
        self.semaphore = semaphore or asyncio.Semaphore(MediaConfig.DEFAULT_SEMAPHORE_LIMIT)
        self.reddit = None

    async def init_client(self):
        if not self.reddit:
            self.reddit = await RedditClientManager.get_client()

    async def fetch_from_subreddits(
        self,
        subreddit_names: List[str],
        search_terms: Optional[List[str]] = None,
        sort: str = RedditDefaults.DEFAULT_SORT_NO_TIME_FILTER,
        time_filter: Optional[str] = None,
        media_type: Optional[str] = None,
        media_count: int = 1,
        update=None,
        invalid_subreddits: Optional[Set[str]] = None,
        processed_urls: Optional[Set[str]] = None,
    ) -> List[Submission]:
        await self.init_client()

        invalid_subreddits = invalid_subreddits or set()
        processed_urls = processed_urls or set()
        processed_post_ids = set()
        media_posts: List[Submission] = []

        valid_subreddits = [s for s in subreddit_names if s not in invalid_subreddits]
        if not valid_subreddits:
            logger.warning("No valid subreddits to fetch from.")
            return []

        random.shuffle(valid_subreddits)

        n = len(valid_subreddits)
        requested_total = max(0, media_count)

        base = requested_total // n
        remainder = requested_total % n

        allocations = {}
        for idx, s in enumerate(valid_subreddits):
            alloc = base + (1 if idx < remainder else 0)
            if alloc > 0:
                allocations[s] = alloc

        async def run_wave(subs_to_fetch, per_sub_alloc):
            tasks = [
                self.fetch_from_single_subreddit(
                    subreddit_name=s,
                    search_terms=search_terms,
                    sort=sort,
                    time_filter=time_filter,
                    media_type=media_type,
                    target_count=per_sub_alloc[s],
                    processed_post_ids=processed_post_ids,
                    update=update,
                    processed_urls=processed_urls,
                )
                for s in subs_to_fetch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            out = []
            for s_name, result in zip(subs_to_fetch, results):
                if isinstance(result, Exception):
                    logger.error(f"Subreddit '{s_name}' task failed: {result}", exc_info=True)
                elif isinstance(result, list):
                    out.extend(result)
                else:
                    logger.warning(f"Unexpected result from subreddit '{s_name}': {type(result)}")
            return out

        subs_wave1 = list(allocations.keys())
        posts_wave1 = await run_wave(subs_wave1, allocations)
        media_posts.extend(posts_wave1)

        seen_urls: Set[str] = set()
        unique_by_url: List[Submission] = []
        for post in media_posts:
            url = getattr(post, "url", None)
            if not url:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            unique_by_url.append(post)

        remaining_needed = requested_total - len(unique_by_url)
        if remaining_needed > 0:
            subs_wave2 = []
            zero_alloc_subs = [s for s in valid_subreddits if s not in allocations]
            subs_wave2.extend(zero_alloc_subs[:remaining_needed])

            if len(subs_wave2) < remaining_needed:
                for s in valid_subreddits:
                    if s in subs_wave2:
                        continue
                    subs_wave2.append(s)
                    if len(subs_wave2) >= remaining_needed:
                        break

            if subs_wave2:
                per_sub_alloc2 = {s: 1 for s in subs_wave2}
                posts_wave2 = await run_wave(subs_wave2, per_sub_alloc2)
                for post in posts_wave2:
                    url = getattr(post, "url", None)
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    unique_by_url.append(post)
                    if len(unique_by_url) >= requested_total:
                        break

        logger.info(
            f"Collected {len(unique_by_url)} unique posts after up to two waves. "
            f"Returning up to {media_count} posts."
        )
        return unique_by_url[:media_count]


    async def fetch_from_single_subreddit(
        self,
        subreddit_name: str,
        search_terms: Optional[List[str]],
        sort: str,
        time_filter: Optional[str],
        media_type: Optional[str],
        target_count: int,
        processed_post_ids: Set[str],
        update,
        processed_urls: Set[str],
    ) -> List[Submission]:
        async with self.semaphore:
            try:
                posts, display_name = await FetchOrchestrator.get_posts(
                    reddit=self.reddit,
                    subreddit_name=subreddit_name,
                    search_terms=search_terms,
                    sort=sort,
                    time_filter=time_filter,
                    update=update
                )

                if not posts:
                    logger.info(f"No results from r/{display_name or subreddit_name}")
                    return []

                filterer = MediaPostFilter(
                    subreddit_name=display_name or subreddit_name,
                    media_type=media_type,
                    media_count=target_count,
                    processed_urls=processed_urls,
                )
                filtered = await filterer.filter(posts)
                unique = await RedditPostFetcher.filter_duplicates(filtered, processed_post_ids)
                logger.info(f"r/{display_name}: {len(unique)} unique posts")
                return unique

            except Exception as e:
                logger.error(f"Error from subreddit '{subreddit_name}': {e}", exc_info=True)
                return []
