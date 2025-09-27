# redditcommand/filter_posts.py

from random import sample
from typing import List, Optional, Set
from asyncpraw.models import Submission

from redditcommand.utils.log_manager import LogManager
from redditcommand.utils.filter_utils import FilterUtils
from redditcommand.config import SkipReasons

logger = LogManager.setup_main_logger()


class MediaPostFilter:
    def __init__(
        self,
        subreddit_name: str,
        media_type: Optional[str] = None,
        media_count: int = 1,
        processed_urls: Optional[Set[str]] = None,
    ):
        self.subreddit_name = subreddit_name
        self.media_type = media_type
        self.media_count = media_count
        self.processed_urls = processed_urls or set()

    async def filter(self, posts: List[Submission]) -> List[Submission]:
        logger.info(f"Filtering r/{self.subreddit_name} | Total posts: {len(posts)}")
        if not posts:
            logger.warning(f"No posts to filter in r/{self.subreddit_name}")
            return []

        skipped = {
            SkipReasons.NON_MEDIA: 0,
            SkipReasons.BLACKLISTED: 0,
            SkipReasons.PROCESSED: 0,
            SkipReasons.GFYCAT: 0,
            SkipReasons.WRONG_TYPE: 0
        }
        filtered = []

        for post in posts:
            reason = FilterUtils.should_skip(post, self.processed_urls, self.media_type)
            if reason:
                skipped[reason] += 1
            else:
                await FilterUtils.attach_metadata(post)
                filtered.append(post)

        FilterUtils.log_skips(skipped)

        if not filtered:
            logger.info(f"No matching {self.media_type or 'media'} posts in r/{self.subreddit_name}")
            return []

        selected = sample(filtered, min(self.media_count, len(filtered)))
        logger.info(f"Selected {len(selected)} post(s) from r/{self.subreddit_name}")
        return selected
