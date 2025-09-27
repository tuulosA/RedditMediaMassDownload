# downloader_pipeline.py
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from asyncpraw import Reddit

from redditcommand.config import RedditClientManager
from redditcommand.utils.log_manager import LogManager
from redditcommand.fetch import MediaPostFetcher
from redditcommand.utils.session import GlobalSession

from reddit_mass_downloader.local_media_handler import LocalMediaSaver
from reddit_mass_downloader.config_overrides import REPORT_DIR, OUTPUT_ROOT
from reddit_mass_downloader.filename_utils import slugify

logger = LogManager.setup_main_logger()


class DownloaderPipeline:
    """
    Pull posts via redditcommand (unchanged), then save locally via LocalMediaSaver.
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
        outcomes: List[Dict[str, Any]] = []

        try:
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
                update=None,
                invalid_subreddits=set(),
                processed_urls=set(),
            )

            if not posts:
                logger.info("No posts fetched by downloader pipeline.")
                self._print_and_write_report(outcomes, fetched=0)
                return 0

            # Build collection folder from subreddit + search terms
            collection_label = None
            if self.search_terms:
                # If multiple subs, join them with '+' so it stays compact: "kpopfap+another momo"
                sub_part = "+".join(self.subreddits) if len(self.subreddits) > 1 else self.subreddits[0]
                label_raw = f"{sub_part} {' '.join(self.search_terms)}".strip()
                collection_label = slugify(label_raw, max_len=120)  # -> "kpopfap_momo"

            saver = LocalMediaSaver(self.reddit, collection_label=collection_label)
            await saver._ensure_ready()

            for post in posts:
                post_info = {
                    "id": getattr(post, "id", None),
                    "subreddit": getattr(getattr(post, "subreddit", None), "display_name", None),
                    "title": getattr(post, "title", None),
                    "url": getattr(post, "url", None),
                }
                try:
                    path = await saver.save_post(post)
                    if path:
                        saved_count += 1
                        outcomes.append({**post_info, "status": "saved", "path": str(path)})
                    else:
                        outcomes.append({**post_info, "status": "failed", "reason": "unknown (save_post returned None)"})

                except FileNotFoundError as e:
                    # Expected permanent-missing case (e.g., redgifs 410/404, dead imgur, etc.)
                    outcomes.append({**post_info, "status": "failed", "reason": str(e)})
                    logger.info(f"{post_info['id']}: {e}")   # no traceback

                except FileExistsError as e:
                    outcomes.append({**post_info, "status": "skipped", "reason": str(e)})
                    logger.info(f"Skipped existing: {post_info['id']}: {e}")

                except Exception as e:
                    outcomes.append({**post_info, "status": "failed", "reason": str(e)})
                    logger.error(f"Error saving post {post_info['id']}: {e}", exc_info=True)

            self._print_and_write_report(outcomes, fetched=len(posts))
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

    def _print_and_write_report(self, outcomes: List[Dict[str, Any]], fetched: int) -> None:
        saved = sum(1 for o in outcomes if o["status"] == "saved")
        failed = [o for o in outcomes if o["status"] == "failed"]
        skipped = [o for o in outcomes if o["status"] == "skipped"]

        print()
        print("=== Download Report ===")
        print(f"Fetched posts: {fetched}")
        print(f"Saved: {saved}")
        print(f"Skipped (exists): {len(skipped)}")
        print(f"Failed: {len(failed)}")
        if failed:
            print("\nFailures (id → reason):")
            for o in failed:
                print(f" - {o.get('id')}: {o.get('reason')}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = (REPORT_DIR / f"report_{ts}.json")
        try:
            import json
            data = {
                "root": str(OUTPUT_ROOT),
                "fetched": fetched,
                "saved": saved,
                "skipped": len(skipped),
                "failed": len(failed),
                "outcomes": outcomes,
                "created_at": ts,
            }
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\nReport written to: {report_path}")
        except Exception as e:
            logger.warning(f"Could not write report JSON: {e}")
