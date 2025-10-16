# reddit_mass_downloader/downloader_pipeline.py
from typing import List, Optional, Dict, Any
from datetime import datetime

from asyncpraw import Reddit

from ..redditcommand.config import RedditClientManager
from ..redditcommand.utils.log_manager import LogManager
from ..redditcommand.fetch import MediaPostFetcher
from ..redditcommand.utils.session import GlobalSession

from .local_media_handler import LocalMediaSaver
from .config_overrides import REPORT_DIR, OUTPUT_ROOT, WRITE_RUN_REPORT_JSON
from .filename_utils import slugify_title

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
        close_on_exit: bool = True,             # keep False when looping
        external_reddit: Optional[Reddit] = None,  # NEW: inject shared client
    ):
        self.subreddits = subreddits
        self.search_terms = search_terms or []
        self.sort = sort
        self.time_filter = time_filter
        self.media_type = media_type
        self.media_count = media_count

        self.reddit: Optional[Reddit] = external_reddit
        self.fetcher: Optional[MediaPostFetcher] = None

        self._owns_reddit = external_reddit is None
        self.close_on_exit = close_on_exit

    async def run(self) -> int:
        saved_count = 0
        outcomes: List[Dict[str, Any]] = []

        try:
            # 1) Get or reuse Reddit client
            if self.reddit is None:
                self.reddit = await RedditClientManager.get_client()

            # 2) Build fetcher and bind injected reddit before init_client()
            self.fetcher = MediaPostFetcher()
            # Important: set .reddit so fetcher.init_client() won't call the manager again
            self.fetcher.reddit = self.reddit
            await self.fetcher.init_client()  # no-op if reddit already set

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
                sub_part = "+".join(self.subreddits) if len(self.subreddits) > 1 else self.subreddits[0]
                label_raw = f"{sub_part} {' '.join(self.search_terms)}".strip()
                collection_label = slugify_title(label_raw, max_len=120)

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
                    result = await saver.save_post(post)
                    if isinstance(result, list):
                        if result:
                            saved_count += len(result)
                            for p in result:
                                outcomes.append({**post_info, "status": "saved", "path": str(p)})
                        else:
                            outcomes.append({
                                **post_info,
                                "status": "failed",
                                "reason": "gallery had 0 valid items (no usable media_metadata)"
                            })
                    elif result:
                        saved_count += 1
                        outcomes.append({**post_info, "status": "saved", "path": str(result)})
                    else:
                        outcomes.append({
                            **post_info,
                            "status": "failed",
                            "reason": "no media resolved (not image/video or resolver declined)"
                        })

                except FileNotFoundError as e:
                    outcomes.append({**post_info, "status": "failed", "reason": str(e)})
                    logger.info(f"{post_info['id']}: {e}")

                except FileExistsError as e:
                    outcomes.append({**post_info, "status": "skipped", "reason": str(e)})
                    logger.info(f"Skipped existing: {post_info['id']}: {e}")

                except Exception as e:
                    outcomes.append({**post_info, "status": "failed", "reason": str(e)})
                    logger.error(f"Error saving post {post_info['id']}: {e}", exc_info=True)

            self._print_and_write_report(outcomes, fetched=len(posts))
            return saved_count

        finally:
            if self.close_on_exit:
                try:
                    await GlobalSession.close()
                except Exception:
                    pass
                # Only close reddit if we created it here
                if self._owns_reddit:
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

        # Optionally write a JSON run report (disabled by default)
        if WRITE_RUN_REPORT_JSON:
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