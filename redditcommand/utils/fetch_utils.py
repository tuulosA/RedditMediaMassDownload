import asyncio
import random
from typing import List, Optional, Set, Tuple
from asyncpraw.models import Subreddit, Submission

from redditcommand.config import RedditClientManager, MediaConfig, Messages
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


async def _safe_reply(update, message: str) -> None:
    target = getattr(update, "message", update)
    if hasattr(target, "reply_text"):
        try:
            await target.reply_text(message)
        except Exception as e:
            logger.warning(f"Failed to send message to user: {e}")
    else:
        logger.warning("No reply_text available on Update object to notify user.")


class SubredditFetcher:
    @staticmethod
    async def fetch_and_validate(subreddit_name: str, update) -> Optional[Subreddit]:
        if subreddit_name.strip().lower() == "random":
            return await SubredditFetcher._fetch_random(update)

        if not subreddit_name.strip():
            await SubredditFetcher._log_and_notify(update, "Subreddit name cannot be empty.", warning=True)
            return None

        try:
            reddit = await RedditClientManager.get_client()
            subreddit = await reddit.subreddit(subreddit_name)
            await subreddit.load()
            logger.info(f"Loaded subreddit: r/{subreddit_name}")
            return subreddit
        except Exception as e:
            return await SubredditFetcher._handle_error(e, subreddit_name, update)

    @staticmethod
    async def _fetch_random(update) -> Optional[Subreddit]:
        try:
            reddit = await RedditClientManager.get_client()
            subreddit = await reddit.random_subreddit()
            await subreddit.load()
            logger.info(f"Loaded random subreddit: r/{subreddit.display_name}")
            return subreddit
        except Exception as e:
            logger.error(f"Random subreddit fetch failed: {e}", exc_info=True)
            await SubredditFetcher._log_and_notify(update, "Failed to load a random subreddit.", warning=True)
            return None

    @staticmethod
    async def _handle_error(e: Exception, subreddit_name: str, update) -> None:
        error_map = {
            "Redirect": "Subreddit does not exist.",
            "Forbidden": "Access to this subreddit is restricted.",
        }
        error_message = error_map.get(e.__class__.__name__, str(e))
        return await SubredditFetcher._log_and_notify(update, f"r/{subreddit_name}: {error_message}", warning=True)

    @staticmethod
    async def _log_and_notify(update, message: str, warning: bool = False) -> None:
        if warning:
            logger.warning(message)
        else:
            logger.info(message)
        await _safe_reply(update, message)


class RedditPostFetcher:
    @staticmethod
    def _build_title_flair_and_query(terms: List[str]) -> str:
        # (title:"orange" OR flair_name:"orange") AND (title:"boy" OR flair_name:"boy")
        parts = []
        for t in terms:
            t = t.strip()
            if not t:
                continue
            t_quoted = t.replace('"', '\\"')
            parts.append(f'(title:"{t_quoted}" OR flair_name:"{t_quoted}")')
        return " AND ".join(parts) if parts else ""

    @staticmethod
    def _matches_all_terms(post: Submission, terms: List[str]) -> bool:
        title = (getattr(post, "title", "") or "").lower()
        flair = (getattr(post, "link_flair_text", "") or "").lower()
        return all((term.lower() in title) or (term.lower() in flair) for term in terms if term.strip())

    @staticmethod
    async def search(subreddit: Subreddit, terms: List[str], sort: str, time_filter: Optional[str]) -> List[Submission]:
        try:
            if not terms:
                return [
                    post async for post in subreddit.search(
                        query="",
                        sort=sort,
                        time_filter=time_filter or "all",
                        limit=MediaConfig.POST_LIMIT,
                    )
                ]

            query = RedditPostFetcher._build_title_flair_and_query(terms)

            results = [
                post async for post in subreddit.search(
                    query=query,
                    sort=sort,
                    time_filter=time_filter or "all",
                    limit=MediaConfig.POST_LIMIT,
                )
            ]

            # Client-side guarantee: keep only posts where every term is in title or flair
            filtered = [p for p in results if RedditPostFetcher._matches_all_terms(p, terms)]

            # De-dupe by id while preserving order
            seen: Set[str] = set()
            out: List[Submission] = []
            for p in filtered:
                if p.id not in seen:
                    seen.add(p.id)
                    out.append(p)
            return out

        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            return []
        
    @staticmethod
    async def fetch_sorted(subreddit: Subreddit, sort: str, time_filter: Optional[str] = None) -> List[Submission]:
        try:
            if sort == "top" and time_filter:
                return [post async for post in subreddit.top(time_filter=time_filter, limit=MediaConfig.POST_LIMIT)]
            return [post async for post in subreddit.hot(limit=MediaConfig.POST_LIMIT)]
        except Exception as e:
            logger.error(f"Error fetching sorted posts: {e}", exc_info=True)
            return []

    @staticmethod
    async def filter_duplicates(posts: List[Submission], seen_ids: Set[str]) -> List[Submission]:
        def _dedupe():
            unique = [p for p in posts if p.id not in seen_ids]
            seen_ids.update(p.id for p in unique)
            return unique

        result = await asyncio.to_thread(_dedupe)
        logger.debug(f"Filtered {len(posts) - len(result)} duplicates")
        return result


class RandomSearch:
    @staticmethod
    async def run(reddit, search_terms, sort, time_filter, update):
        try:
            if search_terms:
                subreddit = await reddit.subreddit("all")
                query = RedditPostFetcher._build_title_flair_and_query(search_terms)

                results = [
                    post async for post in subreddit.search(
                        query=query,
                        sort=sort,
                        time_filter=time_filter or "all",
                        limit=MediaConfig.POST_LIMIT,
                    )
                ]

                filtered = [p for p in results if RedditPostFetcher._matches_all_terms(p, search_terms)]
                return (filtered, subreddit) if filtered else ([], subreddit)

            # Fallback when no search terms
            subreddits = [sub async for sub in reddit.subreddits.popular(limit=100)]
            if not subreddits:
                logger.warning("No popular subreddits found.")
                await _safe_reply(update, Messages.NO_POPULAR_SUBREDDITS)
                return [], None

            subreddit = random.choice(subreddits)
            logger.info(f"Fallback: selected r/{subreddit.display_name}")
            return [], subreddit

        except Exception as e:
            logger.error(f"Random search failure: {e}", exc_info=True)
            await _safe_reply(update, Messages.RANDOM_FETCH_FAILED)
            return [], None


class FetchOrchestrator:
    @staticmethod
    async def get_posts(reddit, subreddit_name: str, search_terms, sort, time_filter, update) -> Tuple[List[Submission], Optional[str]]:
        if subreddit_name.lower() == "random":
            posts, subreddit = await RandomSearch.run(reddit, search_terms, sort, time_filter, update)
        else:
            subreddit = await SubredditFetcher.fetch_and_validate(subreddit_name, update)
            posts = []

        if subreddit and not posts:
            if search_terms:
                posts = await RedditPostFetcher.search(subreddit, search_terms, sort, time_filter)
            else:
                posts = await RedditPostFetcher.fetch_sorted(subreddit, sort, time_filter)

        display_name = getattr(subreddit, "display_name", None)
        return posts, display_name
