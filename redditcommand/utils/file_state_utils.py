# redditcommand/utils/file_state_utils.py

import os
import json
from typing import Set, Dict, List, Optional

from redditcommand.config import FileStateConfig

class FollowedUserStore:
    FOLLOWED_USERS_PATH = FileStateConfig.FOLLOWED_USERS_PATH
    SEEN_POSTS_PATH = FileStateConfig.SEEN_POSTS_PATH
    FOLLOW_MAP_PATH = FileStateConfig.FOLLOW_MAP_PATH
    FILTER_MAP_PATH = FileStateConfig.FILTER_MAP_PATH
    SUBREDDIT_MAP_PATH = FileStateConfig.SUBREDDIT_MAP_PATH

    @classmethod
    def load_seen_post_ids(cls) -> Set[str]:
        if not os.path.exists(cls.SEEN_POSTS_PATH):
            return set()
        with open(cls.SEEN_POSTS_PATH, "r") as f:
            return set(json.load(f))

    @classmethod
    def save_seen_post_ids(cls, post_ids: Set[str]):
        with open(cls.SEEN_POSTS_PATH, "w") as f:
            json.dump(list(post_ids), f)

    @classmethod
    def load_user_follower_map(cls) -> Dict[str, List[str]]:
        if not os.path.exists(cls.FOLLOW_MAP_PATH):
            return {}
        with open(cls.FOLLOW_MAP_PATH, "r") as f:
            return json.load(f)

    @classmethod
    def save_user_follower_map(cls, data: Dict[str, List[str]]):
        with open(cls.FOLLOW_MAP_PATH, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def add_follower(cls, reddit_user: str, tg_username: str):
        data = cls.load_user_follower_map()
        followers = set(data.get(reddit_user, []))
        followers.add(tg_username)
        data[reddit_user] = list(followers)
        cls.save_user_follower_map(data)

    @classmethod
    def remove_follower(cls, reddit_user: str, tg_username: str):
        data = cls.load_user_follower_map()
        if reddit_user not in data:
            return

        followers = set(data.get(reddit_user, []))
        if tg_username in followers:
            followers.remove(tg_username)
            if followers:
                data[reddit_user] = list(followers)
            else:
                del data[reddit_user]
            cls.save_user_follower_map(data)

    @classmethod
    def load_user_filters(cls) -> Dict[str, List[str]]:
        if not os.path.exists(cls.FILTER_MAP_PATH):
            return {}
        with open(cls.FILTER_MAP_PATH, "r") as f:
            return json.load(f)

    @classmethod
    def save_user_filters(cls, data: Dict[str, List[str]]):
        with open(cls.FILTER_MAP_PATH, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def set_filters(cls, tg_username: str, terms: List[str]):
        filters = cls.load_user_filters()
        filters[tg_username] = [t.strip().lower() for t in terms if t.strip()]
        cls.save_user_filters(filters)

    @classmethod
    def get_filters(cls, tg_username: str) -> List[str]:
        return cls.load_user_filters().get(tg_username, [])

    @classmethod
    def clear_filters(cls, tg_username: str):
        filters = cls.load_user_filters()
        if tg_username in filters:
            del filters[tg_username]
            cls.save_user_filters(filters)

    @classmethod
    def get_global_top_subreddit(cls) -> Optional[str]:
        if not os.path.exists(cls.SUBREDDIT_MAP_PATH):
            return None
        with open(cls.SUBREDDIT_MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def set_global_top_subreddit(cls, subreddit: str):
        os.makedirs(os.path.dirname(cls.SUBREDDIT_MAP_PATH) or ".", exist_ok=True)
        with open(cls.SUBREDDIT_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(subreddit, f)

    @classmethod
    def clear_global_top_subreddit(cls):
        if os.path.exists(cls.SUBREDDIT_MAP_PATH):
            os.remove(cls.SUBREDDIT_MAP_PATH)
