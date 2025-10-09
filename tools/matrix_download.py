# tools/matrix_download.py
import asyncio
import argparse
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reddit_mass_downloader.downloader_pipeline import DownloaderPipeline
from redditcommand.utils.session import GlobalSession
from redditcommand.config import RedditClientManager

# ===== SIMPLE TOGGLE =====
USE_SEARCH_TERMS = True
# =========================

DEFAULT_IDOLS = ["mina", "momo", "sana", "tzuyu", "nayeon", "dahyun", "jihyo"]
DEFAULT_SUBS = ["kpopfap", "twicensfw"]
DEFAULT_TIMES = ["week", "month", "year", "all"]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser("Matrix downloader for idols × subreddit × time (single-sub runs)")
    p.add_argument("--idols", "-i", nargs="+", default=DEFAULT_IDOLS, help="Search terms")
    p.add_argument("--subs", "-s", nargs="+", default=DEFAULT_SUBS, help="Subreddits (processed one-by-one)")
    p.add_argument("--times", "-t", nargs="+", default=DEFAULT_TIMES, help="Time filters")
    p.add_argument("--count", "-n", type=int, default=100, help="Number of media to fetch per combo")
    p.add_argument("--type", choices=["image", "video"], default="video", help="Media type filter")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between combos")
    p.add_argument("--sort", choices=["top", "hot"], default="top", help="Sort mode")
    p.add_argument("--strict-single", action="store_true",
                   help="Error if more than one subreddit is provided")
    return p.parse_args()

async def run_matrix(ns: argparse.Namespace) -> None:
    if ns.strict_single and len(ns.subs) != 1:
        raise SystemExit("With --strict-single, provide exactly one subreddit via --subs.")

    grand_total = 0
    combos = 0
    t0 = perf_counter()

    # Shared client
    reddit = await RedditClientManager.get_client()

    try:
        terms_iter = (ns.idols if USE_SEARCH_TERMS else [None])

        # >>> IMPORTANT: iterate each subreddit independently <<<
        for sub in ns.subs:
            for term in terms_iter:
                for tf in ns.times:
                    human_term = (term if term is not None else "(no terms)")
                    print(
                        f"\n=== Running combo: sub={sub} | term={human_term} | "
                        f"time={tf} | count={ns.count} | type={ns.type or 'any'} ==="
                    )

                    pipe = DownloaderPipeline(
                        subreddits=[sub],                                # SINGLE SUBREDDIT
                        search_terms=([term] if (USE_SEARCH_TERMS and term is not None) else []),
                        sort=("top" if tf else ns.sort),
                        time_filter=tf,
                        media_type=ns.type,
                        media_count=ns.count,
                        close_on_exit=False,
                        external_reddit=reddit,
                    )
                    saved = await pipe.run()
                    combos += 1
                    grand_total += saved
                    print(f"[{sub} | {tf} | {human_term}] saved {saved}")

                    if ns.sleep > 0:
                        await asyncio.sleep(ns.sleep)
    finally:
        try:
            await GlobalSession.close()
        except Exception:
            pass
        try:
            if hasattr(reddit, "close"):
                await reddit.close()
        except Exception:
            pass

    dt = perf_counter() - t0
    print(f"\nTOTAL saved across {combos} combos: {grand_total}  (elapsed {dt:.1f}s)")

def main():
    ns = parse_args()
    asyncio.run(run_matrix(ns))

if __name__ == "__main__":
    main()
