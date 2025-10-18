# redditmedia/redditcommand/filter_posts.py

from random import sample
from typing import List, Optional, Set
from asyncpraw.models import Submission

from .utils.log_manager import LogManager
from .utils.filter_utils import FilterUtils
from .config import SkipReasons

logger = LogManager.setup_main_logger()


class MediaPostFilter:
    def __init__(
        self,
        subreddit_name: str,
        media_type: Optional[str] = None,
        media_count: int = 1,
        processed_urls: Optional[Set[str]] = None,
        min_score: Optional[int] = None,
        blacklist_terms: Optional[List[str]] = None,
        pick_mode: str = "top",
    ):
        self.subreddit_name = subreddit_name
        self.media_type = media_type
        self.media_count = media_count
        self.processed_urls = processed_urls or set()
        self.min_score = min_score
        self.blacklist_terms = blacklist_terms or []
        self.pick_mode = (pick_mode or "top").lower()

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
            SkipReasons.WRONG_TYPE: 0,
            SkipReasons.LOW_SCORE: 0,
        }
        filtered = []

        for post in posts:
            reason = FilterUtils.should_skip(
                post,
                self.processed_urls,
                self.media_type,
                min_score=self.min_score,
                blacklist_terms=self.blacklist_terms,
            )
            if reason:
                skipped[reason] += 1
            else:
                await FilterUtils.attach_metadata(post)
                filtered.append(post)

        FilterUtils.log_skips(skipped)

        if not filtered:
            logger.info(f"No matching {self.media_type or 'media'} posts in r/{self.subreddit_name}")
            return []

        if self.pick_mode == "random":
            selected = sample(filtered, min(self.media_count, len(filtered)))
            logger.info(f"Selected {len(selected)} random post(s) from r/{self.subreddit_name}")
        else:
            # Pick highest scores first (stable, deterministic)
            # Tie-breakers: upvote_ratio, num_comments, created_utc
            def _key(p: Submission):
                score         = getattr(p, "score", 0) or 0
                upvote_ratio  = getattr(p, "upvote_ratio", 0.0) or 0.0
                num_comments  = getattr(p, "num_comments", 0) or 0
                created_utc   = getattr(p, "created_utc", 0.0) or 0.0
                # negative for descending sort
                return (-score, -upvote_ratio, -num_comments, -created_utc)

            filtered.sort(key=_key)
            selected = filtered[: self.media_count]
            if selected:
                hi = getattr(selected[0], "score", 0) or 0
                lo = getattr(selected[-1], "score", 0) or 0
                logger.info(
                    f"Selected {len(selected)} top-scoring post(s) "
                    f"from r/{self.subreddit_name} (score range: {lo}–{hi})"
                )
            else:
                logger.info(f"Selected 0 post(s) from r/{self.subreddit_name}")
        
        return selected
