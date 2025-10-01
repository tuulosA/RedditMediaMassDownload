# tools/matrix_download.py
import asyncio
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reddit_mass_downloader.downloader_pipeline import DownloaderPipeline
from redditcommand.utils.session import GlobalSession
from redditcommand.config import RedditClientManager  # NEW

# ===== SIMPLE TOGGLE =====
USE_SEARCH_TERMS = True
# =========================

DEFAULT_IDOLS = ["mina", "momo", "sana", "tzuyu", "nayeon", "dahyun", "jihyo"]
DEFAULT_SUBS = ["kpopfap", "twicensfw"]
DEFAULT_TIMES = ["week", "month", "year", "all"]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser("Matrix downloader for idols × subreddits × time filters")
    p.add_argument("--idols", "-i", nargs="+", default=DEFAULT_IDOLS, help="Search terms")
    p.add_argument("--subs", "-s", nargs="+", default=DEFAULT_SUBS, help="Subreddits")
    p.add_argument("--times", "-t", nargs="+", default=DEFAULT_TIMES, help="Time filters")
    p.add_argument("--count", "-n", type=int, default=100, help="Number of media to fetch per combo")
    p.add_argument("--type", choices=["image", "video"], default="video", help="Media type filter")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between combos (avoid rate limits)")
    p.add_argument("--sort", choices=["top", "hot"], default="top", help="Sort mode (top recommended with time filters)")
    return p.parse_args()

async def run_matrix(ns: argparse.Namespace) -> None:
    grand_total = 0

    # Build ONE shared Reddit client up front (from your existing manager)
    reddit = await RedditClientManager.get_client()

    try:
        terms_iter = (ns.idols if USE_SEARCH_TERMS else [None])

        for term in terms_iter:
            for tf in ns.times:
                human_term = (term if term is not None else "(no terms)")
                print(
                    f"\n=== Running combo: subs={','.join(ns.subs)} | term={human_term} | "
                    f"time={tf} | count={ns.count} | type={ns.type or 'any'} ==="
                )

                pipe = DownloaderPipeline(
                    subreddits=ns.subs,
                    search_terms=([term] if (USE_SEARCH_TERMS and term is not None) else []),
                    sort=("top" if tf else ns.sort),
                    time_filter=tf,
                    media_type=ns.type,
                    media_count=ns.count,
                    close_on_exit=False,             # don't close between iterations
                    external_reddit=reddit,          # inject shared client so fetcher uses it
                )
                saved = await pipe.run()
                grand_total += saved
                print(f"[{tf} | {human_term}] saved {saved}")

                if ns.sleep > 0:
                    await asyncio.sleep(ns.sleep)
    finally:
        # OK to close your own download session
        try:
            await GlobalSession.close()
        except Exception:
            pass
        # If you want a clean shutdown, you can close the client here (optional)
        try:
            if hasattr(reddit, "close"):
                await reddit.close()
        except Exception:
            pass

    print(f"\nTOTAL saved across all combos: {grand_total}")

def main():
    ns = parse_args()
    asyncio.run(run_matrix(ns))

if __name__ == "__main__":
    main()
