# redditcommand/config.py

import os
import asyncpraw
from datetime import timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

class RedditConfig:
    @staticmethod
    def load_reddit_config():
        """
        Loads Reddit API credentials from environment variables.
        """
        required_keys = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT", "REDDIT_USERNAME", "REDDIT_PASSWORD"]
        config = {key: os.getenv(key) for key in required_keys}

        # Ensure all required keys are present
        missing_keys = [key for key, value in config.items() if not value]
        if missing_keys:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_keys)}")

        return config

    @staticmethod
    async def initialize_reddit():
        """
        Initializes and returns an asyncpraw Reddit client.
        """
        config = RedditConfig.load_reddit_config()
        return asyncpraw.Reddit(
            client_id=config["REDDIT_CLIENT_ID"],
            client_secret=config["REDDIT_CLIENT_SECRET"],
            user_agent=config["REDDIT_USER_AGENT"],
            username=config["REDDIT_USERNAME"],
            password=config["REDDIT_PASSWORD"],
        )

class RedditClientManager:
    _client = None

    @classmethod
    async def get_client(cls):
        """
        Returns a shared instance of the Reddit client, initializing it if necessary.
        """
        if cls._client is None:
            cls._client = await RedditConfig.initialize_reddit()
        return cls._client

class TimeoutConfig:
    DOWNLOAD_TIMEOUT = 300

class RetryConfig:
    RETRY_ATTEMPTS = 1

class MediaConfig:
    MAX_FILE_SIZE_MB = 50
    DEFAULT_SEMAPHORE_LIMIT = 10
    MAX_MEDIA_COUNT = 10
    POST_LIMIT = 100

class PipelineConfig:
    INITIAL_BACKOFF_SECONDS = 1.0
    MAX_BACKOFF_SECONDS = 10
    BACKOFF_MULTIPLIER = 1.1
    MAX_PROCESSED_URLS = 10_000

class SchedulerConfig:
    DAILY_POST_HOUR = 20
    WEEKLY_POST_HOUR = 21
    MONTHLY_POST_HOUR = 0
    YEARLY_POST_HOUR = 0
    WEEKLY_POST_DAYS = (0,)  # Sunday
    FOLLOW_CHECK_INTERVAL_SECONDS = 300
    FOLLOW_CHECK_FIRST_DELAY = 10

class FollowUserConfig:
    POST_AGE_THRESHOLD_SECONDS = 43200

class TelegramConfig:
    LOCAL_TIMEZONE = timezone(timedelta(hours=3))

class LogConfig:
    SKIP_LOG_PATH = "logs/skip_debug.log"
    ACCEPTED_LOG_PATH = "logs/accepted_debug.log"

class RedditDefaults:
    DEFAULT_SORT_WITH_TIME_FILTER = "top"
    DEFAULT_SORT_NO_TIME_FILTER = "hot"

class RedditVideoConfig:
    DASH_RESOLUTIONS = ["1080", "720", "480", "360"]

class CommentFilterConfig:
    BLACKLIST_TERMS = {
        "http", "www", ".com", "[deleted]", "sauce", "[removed]",
        "u/", "source", "![gif]"
    }

class MediaValidationConfig:
    VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webm", ".gifv")

    VALID_SOURCES = [
        "/gallery/", "v.redd.it", "i.redd.it", "imgur.com", "streamable.com",
        "redgifs.com", "kick.com", "twitch.tv", "youtube.com", "youtu.be",
        "twitter.com", "x.com"
    ]

    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
    VIDEO_EXTENSIONS = (".mp4", ".webm", ".gifv", ".gif")

    SOURCE_HINTS = {
        "image": ["/gallery/"],
        "video": ["v.redd.it", "streamable.com", "redgifs.com"]
    }

class FileStateConfig:
    FOLLOWED_USERS_PATH = "followed_users.json"
    SEEN_POSTS_PATH = "seen_user_posts.json"
    FOLLOW_MAP_PATH = "follower_map.json"
    FILTER_MAP_PATH = "user_filters.json"
    SUBREDDIT_MAP_PATH = "followed_subreddit.json"

class TopPostConfig:
    DEFAULT_SUBREDDIT = "cats"
    ARCHIVE_BASE_DIR = "auto_posts"

class SkipReasons:
    NON_MEDIA = "non-media"
    PROCESSED = "processed"
    GFYCAT = "gfycat"
    WRONG_TYPE = "wrong type"
    BLACKLISTED = "blacklisted"

    @classmethod
    def all(cls) -> list[str]:
        return [
            cls.NON_MEDIA,
            cls.PROCESSED,
            cls.GFYCAT,
            cls.WRONG_TYPE,
            cls.BLACKLISTED,
        ]

class Messages:
    USAGE_MESSAGE = (
        "Usage: /r [all/year/month/week/day] [subreddit(s)] [term(s)] [count] [image/video] "
        "[-c] [-f] [-t] [-a]\n\n"
        "Flags:\n"
        "  -c  Include top comment\n"
        "  -f  Include flair\n"
        "  -t  Include title\n"
        "  -a  Include all (title, flair, comment)"
    )

    INVALID_FORMAT_MESSAGE = (
        "Invalid command format.\nExample: /r week cats orange 3 video -a"
    )

    MAX_COUNT_EXCEEDED_MESSAGE = (
        f"Maximum of {MediaConfig.MAX_MEDIA_COUNT} media files can be fetched at a time."
    )

    NO_ARGUMENTS_PROVIDED = "No arguments provided."
    NO_SUBREDDITS_PROVIDED = "Please specify at least one valid subreddit."
    INVALID_SUBREDDIT_FORMAT = "Invalid subreddit format. Ensure names are comma-separated."

    UNEXPECTED_ERROR = "An unexpected error occurred. Please try again."

    TELEGRAM_USERNAME_REQUIRED = "You need a Telegram @username to use this feature."

    FOLLOW_USER_USAGE = "Usage: /follow <reddit_username>"
    UNFOLLOW_USER_USAGE = "Usage: /unfollow <reddit_username>"
    USER_NOT_FOUND = "Reddit user u/{username} was not found or is private."
    CHECK_USER_ERROR = "An error occurred while checking the Reddit user."
    NOW_FOLLOWING = "You're now following u/{username}!"
    ALREADY_FOLLOWING = "You're already following u/{username}."
    UNFOLLOWED = "You've unfollowed u/{username}."
    NOT_FOLLOWING_ANYONE = "You're not following any Reddit users."
    FOLLOWING_LIST_HEADER = "You're currently following:\n{users}"

    FILTERS_CLEARED = "Your filters have been cleared."
    NO_VALID_TERMS = "No valid terms provided."
    FILTERS_SET = "Filter terms set: {terms}"
    NO_ACTIVE_FILTERS = "You have no active filters."
    ACTIVE_FILTERS_TEMPLATE = "Your active filters: {filters}"

    NO_VALID_SUBREDDITS = "No valid or accessible subreddits provided."
    NO_POSTS_FOUND = "No posts found."
    PARTIAL_RESULTS = "Only {processed}/{requested} posts found."

    NO_POPULAR_SUBREDDITS = "Failed to fetch random subreddit."
    RANDOM_FETCH_FAILED = "Random subreddit fetch failed."

    PROVIDE_DEFAULT_SUBREDDIT = "Please provide a subreddit name. Usage: /setsubreddit [subreddit]"
    DEFAULT_SUBREDDIT_SET = "Default subreddit for top posts set to: r/{subreddit}"
