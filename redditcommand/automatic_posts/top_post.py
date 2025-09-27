# redditcommand/automatic_posts/top_post.py

from typing import Optional, Tuple, Union

from telegram import Update, Bot
from asyncpraw.models import Submission

from redditcommand.config import RedditClientManager, TelegramConfig, TopPostConfig
from redditcommand.utils.filter_utils import FilterUtils
from redditcommand.utils.media_utils import MediaUtils
from redditcommand.automatic_posts.top_post_utils import TopPostUtils
from redditcommand.media_handler import MediaProcessor
from redditcommand.utils.file_state_utils import FollowedUserStore
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()

SubredditTarget = Union[Update, Tuple[Bot, int]]


class TopPostManager:
    def __init__(
        self,
        subreddit: Optional[str] = None,
        target: Optional[SubredditTarget] = None
    ):
        self.subreddit = subreddit
        self.reddit = None
        self.target = target
        self.timezone = TelegramConfig.LOCAL_TIMEZONE
        self.base_dir = TopPostConfig.ARCHIVE_BASE_DIR

    async def init_client(self):
        self.reddit = await RedditClientManager.get_client()

    async def resolve_global_subreddit(self):
        custom = FollowedUserStore.get_global_top_subreddit()
        if custom:
            self.subreddit = custom

    async def fetch_top_post(self, time_filter: str) -> Optional[Submission]:
        try:
            subreddit = await self.reddit.subreddit(self.subreddit)
            posts = [post async for post in subreddit.top(time_filter=time_filter, limit=50)]

            async with MediaProcessor(self.reddit, update=None) as processor:
                for post in posts:
                    if FilterUtils.should_skip(post, set(), None):
                        continue
                    await FilterUtils.attach_metadata(post)

                    resolved_url = await processor.resolve_media_url(post)
                    if not resolved_url:
                        continue

                    file_path = await processor.download_and_validate_media(resolved_url, post.id)
                    if not file_path:
                        continue

                    post.metadata["file_path"] = file_path
                    top_comment = await MediaUtils.fetch_top_comment(post, return_author=True)
                    post.metadata["top_comment"] = top_comment
                    if top_comment and not isinstance(top_comment, str):
                        post.metadata["top_comment_author"] = (
                            top_comment.author.name if top_comment.author else "[deleted]"
                        )
                    return post
            return None
        except Exception as e:
            logger.error(f"Error in fetch_top_post({time_filter}): {e}", exc_info=True)
            return None

    async def send_top_post(self, label: str, time_filter: str, target: SubredditTarget, archive: bool):
        self.target = target

        if not self.subreddit:
            await self.resolve_global_subreddit()
        if not self.subreddit:
            self.subreddit = TopPostConfig.DEFAULT_SUBREDDIT

        await self.init_client()

        post = await self.fetch_top_post(time_filter)
        if not post:
            message = f"Could not find a top post for {label.lower()}."
            await TopPostUtils.send_failure_message(target, message)
            return

        caption = TopPostUtils.build_caption(post, label)
        file_path = post.metadata["file_path"]

        if archive:
            TopPostUtils.archive_post(post, file_path, time_filter, self.timezone, self.base_dir)

        try:
            async with MediaProcessor(self.reddit, update=None) as processor:
                success = await processor.upload_media(file_path, target, caption)
                if not success:
                    raise RuntimeError("Media upload failed")
        except Exception as e:
            logger.error(f"Failed to send top post media: {e}", exc_info=True)
            fail_msg = f"Failed to send media for {label.lower()}."
            await TopPostUtils.send_failure_message(target, fail_msg)
