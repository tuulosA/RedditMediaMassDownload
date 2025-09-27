# redditcommand/utils/command_utils.py

from telegram import Update
from telegram.ext import CallbackContext
from typing import List, Tuple, Optional

from redditcommand.config import Messages, MediaConfig
from redditcommand.utils.file_state_utils import FollowedUserStore
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class CommandParser:
    @staticmethod
    async def parse(update: Update, context: CallbackContext) -> Tuple:
        if not context.args:
            raise ValueError(Messages.INVALID_FORMAT_MESSAGE)

        time_filter, args = CommandParser.extract_time_filter(context.args)
        if not args:
            raise ValueError(Messages.NO_SUBREDDITS_PROVIDED)

        subreddit_names = CommandParser.parse_subreddits(args[0])
        media_count, media_type, search_terms, include_comments, include_flair, include_title = CommandParser.parse_other_args(args[1:])

        if media_count > MediaConfig.MAX_MEDIA_COUNT:
            raise ValueError(Messages.MAX_COUNT_EXCEEDED_MESSAGE)

        command_data = {
            'time_filter': time_filter,
            'subreddits': subreddit_names,
            'search_terms': search_terms,
            'media_count': media_count,
            'media_type': media_type,
            'include_comments': include_comments,
            'include_flair': include_flair,
            'include_title': include_title,
        }
        logger.info(f"Command parsed for {update.message.from_user.username}: {command_data}")

        return time_filter, subreddit_names, search_terms, media_count, media_type, include_comments, include_flair, include_title

    @staticmethod
    def extract_time_filter(args: List[str]) -> Tuple[Optional[str], List[str]]:
        time_filter = args[0].lower() if args[0].lower() in ["all", "year", "month", "week", "day"] else None
        return time_filter, args[1:] if time_filter else args

    @staticmethod
    def parse_subreddits(arg: str) -> List[str]:
        if arg.lower() == "random":
            return ["random"]
        subreddits = [sub.strip() for sub in arg.split(",") if sub.strip()]
        if not subreddits:
            raise ValueError(Messages.INVALID_SUBREDDIT_FORMAT)
        return subreddits

    @staticmethod
    def parse_other_args(args: List[str]) -> Tuple[int, Optional[str], List[str], bool, bool, bool]:
        media_count = 1
        media_type = None
        search_terms = []
        include_comments = False
        include_flair = False
        include_title = False

        for arg in args:
            lowered = arg.lower()
            if lowered == "-a":
                include_comments = include_flair = include_title = True
            elif lowered == "-c":
                include_comments = True
            elif lowered == "-f":
                include_flair = True
            elif lowered == "-t":
                include_title = True
            elif lowered.isdigit():
                count = int(lowered)
                if count <= MediaConfig.MAX_MEDIA_COUNT:
                    media_count = count
                else:
                    raise ValueError(Messages.MAX_COUNT_EXCEEDED_MESSAGE)
            elif lowered in ["image", "video"]:
                media_type = lowered
            else:
                search_terms.append(lowered)

        return media_count, media_type, search_terms, include_comments, include_flair, include_title


class CommandUtils:
    @staticmethod
    def get_username(update: Update) -> Optional[str]:
        return update.message.from_user.username

    @staticmethod
    async def require_username(update: Update) -> Optional[str]:
        username = CommandUtils.get_username(update)
        if not username:
            await update.message.reply_text(Messages.TELEGRAM_USERNAME_REQUIRED)
        return username

    @staticmethod
    def sanitize_reddit_username(raw: str) -> str:
        return raw.lstrip("u/").strip().lower()

    @staticmethod
    def get_followed_users(tg_user: str) -> List[str]:
        followed_map = FollowedUserStore.load_user_follower_map()
        return [u for u, followers in followed_map.items() if tg_user in followers]

    @staticmethod
    async def show_user_filters(update: Update, username: str):
        filters = FollowedUserStore.get_filters(username)
        if not filters:
            await update.message.reply_text(Messages.NO_ACTIVE_FILTERS)
        else:
            await update.message.reply_text(Messages.ACTIVE_FILTERS_TEMPLATE.format(filters=", ".join(filters)))
