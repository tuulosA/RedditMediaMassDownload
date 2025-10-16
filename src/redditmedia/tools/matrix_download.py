# tools/matrix_download.py
import asyncio
import argparse
from time import perf_counter

from ..reddit_mass_downloader.downloader_pipeline import DownloaderPipeline
from ..redditcommand.utils.session import GlobalSession
from ..redditcommand.config import RedditClientManager

# ========================= BINARY MODE TOGGLES =========================
# True  = use idol search terms (DEFAULT_IDOLS) against HUB_SUB.
# False = ignore search terms entirely and fetch directly from subs list below.
USE_SEARCH_TERMS = False

# When USE_SEARCH_TERMS == False:
#   True  => use PERSONAL_GROUP_SUBS (group-oriented subs)
#   False => use PERSONAL_SUBS (idol-specific subs)
USE_GROUP_SUBS = True
# ======================================================================

# Idol search terms
DEFAULT_IDOLS = [
    # TWICE
    "mina", "momo", "sana", "tzuyu", "nayeon", "dahyun", "jihyo", "chaeyoung", "jeongyeon",
    # LE SSERAFIM
    "chaewon", "sakura", "yunjin", "kazuha", "eunchae",
    # ITZY
    "yeji", "lia", "ryujin", "chaeryeong", "yuna",
    # aespa
    "karina", "giselle", "winter", "ningning",
    # (G)I-DLE
    "miyeon", "minnie", "soyeon", "yuqi", "shuhua",
    # Red Velvet
    "irene", "seulgi", "wendy", "joy", "yeri",
    # BLACKPINK
    "lisa", "jennie", "rose", "jisoo",
    # Soloists
    "eunbi", "somi",
]

# Hub sub (use with idol search terms)
HUB_SUB = "kpopfap"

# Personal/group subs (used when not using idol terms)
PERSONAL_SUBS = [
    # TWICE
    "myouimina", "nayeon", "jeongyeon", "momo", "sana", "jihyo", "dahyun", "chaeyoung", "tzuyu",
    # LE SSERAFIM
    "chaewon", "chaewonkim", "sakura", "yunjinhuh", "kazuha", "kazuhanakamura", "hongeunchae", "eunchaehong",
    # ITZY
    "yeji", "lia", "ryujin", "ryujinitzy", "chaeryeong", "leechaeryeong", "yuna",
    # aespa
    "karina", "giselle", "winteraespa", "ningning",
    # (G)I-DLE
    "miyeon", "chomiyeon", "minniegidle", "soyeon", "yuqi", "shuhua",
    # Red Velvet
    "baeirene", "seulgi", "wendyredvelvet", "joy_redvelvet", "yeri",
    # BLACKPINK
    "lalisa", "jenniekim", "jennie", "rose", "jisoo",
    # Soloists
    "kwon_eunbi", "somi", "somi_nsfw",
]

# Personal/group subs (used when not using idol terms)
PERSONAL_GROUP_SUBS = [
    # TWICE
    "twicensfw", "twicexnice", "twice_hotties", "twicemedia",
    # LE SSERAFIM
    "LeSserafim_Hotties",
    # MISAMO
    "misamo", "mimosa",
    # ITZY
    "itzy_hotties",
    # aespa
    "aespa_hotties",
    # (G)I-DLE
    "GIDLE_Hotties",
    # Red Velvet
    "RedVelvet_Hotties",
    # BLACKPINK
    "Blackpink_Hotties",
]

# Time filters
#DEFAULT_TIMES = ["day"]
#DEFAULT_TIMES = ["week"]
#DEFAULT_TIMES = ["day", "week"]
#DEFAULT_TIMES = ["week", "month", "year"]
#DEFAULT_TIMES = ["week", "month", "year", "all"]
DEFAULT_TIMES = ["year", "all"]
#DEFAULT_TIMES = ["all"]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser("Matrix downloader for idols × subreddit × time (single-sub runs)")
    # NOTE: no CLI for picking idol vs group when no-terms; it's hard-coded above.

    p.add_argument("--subs", "-s", nargs="+", default=None,
                   help="Override default subs (optional).")
    p.add_argument("--idols", "-i", nargs="+", default=DEFAULT_IDOLS,
                   help="Search terms (used only if USE_SEARCH_TERMS=True)")
    p.add_argument("--times", "-t", nargs="+", default=DEFAULT_TIMES, help="Time filters")
    p.add_argument("--count", "-n", type=int, default=20, help="Number of media to fetch per combo")
    p.add_argument("--type", choices=["image", "video"], default=None, help="Media type filter")
    p.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between combos")
    p.add_argument("--sort", choices=["top", "hot"], default="top", help="Sort mode")
    p.add_argument("--strict-single", action="store_true",
                   help="Error if more than one subreddit is provided")
    ns = p.parse_args()

    # Choose defaults based on hard-coded booleans if --subs not provided
    if ns.subs is None:
        if USE_SEARCH_TERMS:
            ns.subs = [HUB_SUB]
        else:
            ns.subs = (PERSONAL_GROUP_SUBS if USE_GROUP_SUBS else PERSONAL_SUBS)

    return ns

async def run_matrix(ns: argparse.Namespace) -> None:
    if ns.strict_single and len(ns.subs) != 1:
        raise SystemExit("With --strict-single, provide exactly one subreddit via --subs.")

    grand_total = 0
    combos = 0
    t0 = perf_counter()

    if USE_SEARCH_TERMS:
        mode_str = "IDOL TERMS → HUB SUBS"
    else:
        scope = "GROUP SUBS" if USE_GROUP_SUBS else "IDOL-SPECIFIC SUBS"
        mode_str = f"NO TERMS → {scope}"
    print(f"\n=== MODE: {mode_str} ===")

    # Shared client
    reddit = await RedditClientManager.get_client()

    try:
        for sub in ns.subs:
            # Use idol terms list or a single None sentinel (no terms)
            term_list = (ns.idols if USE_SEARCH_TERMS else [None])

            for term in term_list:
                for tf in ns.times:
                    human_term = (term if term is not None else "(no terms)")
                    print(
                        f"\n=== Running combo: sub={sub} | term={human_term} | "
                        f"time={tf} | count={ns.count} | type={ns.type or 'any'} ==="
                    )

                    pipe = DownloaderPipeline(
                        subreddits=[sub],
                        search_terms=([term] if (USE_SEARCH_TERMS and term is not None) else []),
                        sort=ns.sort,                     
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
