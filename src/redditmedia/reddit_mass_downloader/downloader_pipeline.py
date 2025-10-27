# redditmedia/reddit_mass_downloader/downloader_pipeline.py
from __future__ import annotations

from dataclasses import dataclass
import os
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


@dataclass
class RunSummary:
    fetched: int
    saved: int
    skipped: int
    failed: int
    outcomes: List[Dict[str, Any]]


class DownloaderPipeline:
    """
    Pull posts via redditcommand, then save locally via LocalMediaSaver.
    """

    def __init__(
        self,
        subreddits: List[str],
        search_terms: Optional[List[str]] = None,
        sort: str = "hot",
        time_filter: Optional[str] = None,
        media_type: Optional[str] = None,
        media_count: int = 1,
        min_score: Optional[int] = None,
        pick_mode: str = "top",
        blacklist_terms: Optional[List[str]] = None,
        close_on_exit: bool = True,                  # keep False when looping
        external_reddit: Optional[Reddit] = None,    # inject shared client
        write_report: bool = True,                   # allow caller to suppress per-run JSON
        dry_run: bool = False,                       # NEW: metadata-only; do not download
    ):
        self.subreddits = subreddits
        self.search_terms = search_terms or []
        self.sort = sort
        self.time_filter = time_filter
        self.media_type = media_type
        self.media_count = media_count
        self.min_score = min_score
        self.pick_mode = (pick_mode or "top").lower()
        self.blacklist_terms = blacklist_terms or []

        self.reddit: Optional[Reddit] = external_reddit
        self.fetcher: Optional[MediaPostFetcher] = None

        self._owns_reddit = external_reddit is None
        self.close_on_exit = close_on_exit
        self.write_report = write_report
        # Allow env override so callers don't need to plumb the arg
        self.dry_run = bool(dry_run or (os.getenv("RMD_DRY_RUN", "").strip() == "1"))

        self._last_summary: Optional[RunSummary] = None

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
                min_score=self.min_score,
                pick_mode=self.pick_mode,
                blacklist_terms=self.blacklist_terms,
                update=None,
                invalid_subreddits=set(),
                processed_urls=set(),
            )

            if not posts:
                logger.info("No posts fetched by downloader pipeline.")
                summary = self._build_summary(outcomes, fetched=0)
                self._finalize_report(summary)
                return 0

            # Build collection folder from subreddit + search terms
            collection_label = None
            if self.search_terms:
                sub_part = "+".join(self.subreddits) if len(self.subreddits) > 1 else self.subreddits[0]
                label_raw = f"{sub_part} {' '.join(self.search_terms)}".strip()
                collection_label = slugify_title(label_raw, max_len=120)

            # If dry-run, skip creating saver and only collect metadata
            saver: Optional[LocalMediaSaver] = None
            if not self.dry_run:
                saver = LocalMediaSaver(self.reddit, collection_label=collection_label)
                await saver._ensure_ready()

            for post in posts:
                post_info = {
                    "id": getattr(post, "id", None),
                    "subreddit": getattr(getattr(post, "subreddit", None), "display_name", None),
                    "title": getattr(post, "title", None),
                    "url": getattr(post, "url", None),
                    "score": getattr(post, "score", None),          # <-- NEW: include score in report
                    # (optional extras if you want them, uncomment as needed)
                    "upvote_ratio": getattr(post, "upvote_ratio", None),
                    "num_comments": getattr(post, "num_comments", None),
                    "created_utc": getattr(post, "created_utc", None),
                }
                # Dry-run: record only metadata, mark status as 'listed'
                if self.dry_run:
                    outcomes.append({**post_info, "status": "listed"})
                    continue

                try:
                    result = await saver.save_post(post)  # type: ignore[union-attr]
                    if isinstance(result, list):
                        if result:
                            saved_count += len(result)
                            for p in result:
                                outcomes.append({**post_info, "status": "saved", "path": str(p)})
                        else:
                            outcomes.append({
                                **post_info,
                                "status": "failed",
                                "reason": "gallery had 0 valid items (no usable media_metadata)",
                            })
                    elif result:
                        saved_count += 1
                        outcomes.append({**post_info, "status": "saved", "path": str(result)})
                    else:
                        # Resolver returned no URL (e.g., transient Redgifs outage, unsupported host, etc.)
                        # Treat as SKIPPED so flaky upstreams don’t count as failures.
                        outcomes.append({
                            **post_info,
                            "status": "skipped",
                            "reason": "resolver returned no URL (transient/unavailable or declined)",
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

            summary = self._build_summary(outcomes, fetched=len(posts))
            self._finalize_report(summary)
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

    def last_summary(self) -> Optional[RunSummary]:
        return self._last_summary

    # ---- helpers -------------------------------------------------------------

    def _build_summary(self, outcomes: List[Dict[str, Any]], fetched: int) -> RunSummary:
        saved = sum(1 for o in outcomes if o["status"] == "saved")
        skipped = sum(1 for o in outcomes if o["status"] == "skipped")
        failed = sum(1 for o in outcomes if o["status"] == "failed")
        return RunSummary(fetched=fetched, saved=saved, skipped=skipped, failed=failed, outcomes=outcomes)

    def _print_summary(self, s: RunSummary) -> None:
        print()
        print("=== Download Report ===")
        print(f"Fetched posts: {s.fetched}")
        print(f"Saved: {s.saved}")
        print(f"Skipped (exists): {s.skipped}")
        print(f"Failed: {s.failed}")
        if s.failed:
            print("\nFailures (id → reason):")
            for o in (x for x in s.outcomes if x["status"] == "failed"):
                print(f" - {o.get('id')}: {o.get('reason')}")

    def _write_report(self, s: RunSummary) -> None:
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)  # ensure dir exists
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = REPORT_DIR / f"report_{ts}.json"
            import json  # local import to avoid import at module load time
            data = {
                "root": str(OUTPUT_ROOT),
                "fetched": s.fetched,
                "saved": s.saved,
                "skipped": s.skipped,
                "failed": s.failed,
                "outcomes": s.outcomes,
                "created_at": ts,
            }
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\nReport written to: {report_path}")
        except Exception as e:
            logger.warning(f"Could not write report JSON: {e}")

    def _finalize_report(self, summary: RunSummary) -> None:
        self._last_summary = summary
        self._print_summary(summary)
        if self.write_report and WRITE_RUN_REPORT_JSON:
            self._write_report(summary)
