# redditmedia/tools/matrix_download.py
import asyncio
import argparse
from datetime import datetime
from time import perf_counter
from typing import List, Optional, Dict, Any

from ..reddit_mass_downloader.downloader_pipeline import DownloaderPipeline
from ..reddit_mass_downloader.config_overrides import REPORT_DIR, OUTPUT_ROOT
from ..redditcommand.utils.session import GlobalSession
from ..redditcommand.config import RedditClientManager

r"""
Matrix downloader for idols × subreddit × time.

This module orchestrates a grid of download “combos” and writes a single
unified JSON report at the end. A combo is:
    (subreddit) × (search term or no term) × (time filter) × (media type) × (sort)

Runtime behavior is **entirely CLI-driven**:
  - Choose whether to use search terms with: --use-terms / --no-terms
  - When not using terms *and* you don't pass --subs, choose the default pool with:
      --group-subs (group-oriented subs) or --idol-subs (idol-specific subs)

Key runtime pieces:
  - DownloaderPipeline: executes each combo and tracks a summary.
  - GlobalSession / RedditClientManager: shared HTTP/Reddit clients.
  - REPORT_DIR and OUTPUT_ROOT (from config_overrides): control output paths.

Outputs:
  - Media is downloaded beneath OUTPUT_ROOT (pipeline/config decides exact layout).
  - A single unified report JSON is written to REPORT_DIR as:
      matrix_report_YYYYMMDD_HHMMSS.json
    containing total fetched/saved/skipped/failed and per-item outcomes,
    including the combo tags used to fetch them.

CLI:
    python -m redditmedia.tools.matrix_download [options]
    python redditmedia/tools/matrix_download.py [options]

Important options:
  --use-terms / --no-terms
      Whether to search with idol terms. (default: --use-terms)
  --group-subs / --idol-subs
      Only used when not using terms AND you didn't pass --subs.
      Picks between default group-oriented subs vs idol-specific ones.
      (default: --group-subs)
  --subs/-s
      One or more subreddits to target (overrides default pools).
  --idols/-i
      Idol search terms (used only with --use-terms).
  --times/-t
      One or more time filters: day, week, month, year, all. (default: week)
  --count/-n
      Number of media to fetch per combo. (default: 5)
  --type
      Media type filter: image | video (default: any).
  --sort
      top | hot (default: top).
  --min-score
      Skip posts with score (upvotes) below this number. (default: None)
  --pick
      Selection mode among filtered candidates: top | random (default: top).
      - top: highest scores first (tie-breakers: upvote_ratio, num_comments, created_utc)
      - random: uniform random pick among survivors
  --sleep
      Seconds to sleep between combos (default: 0).
  --strict-single
      Error if more than one subreddit is provided.

Examples:
  # Default settings with minimum score of 200
  python -m redditmedia.tools.matrix_download --min-score 200

  # all-subs with min score
  python -m redditmedia.tools.matrix_download --all-subs --min-score 2000

  # all-subs with min score for time filter year and all-time
  python -m redditmedia.tools.matrix_download --all-subs --min-score 2000 --times year all

  # kpopfap for today but only TWICE
  python -m redditmedia.tools.matrix_download --use-terms --subs kpopfap --idols mina momo sana tzuyu nayeon dahyun jihyo chaeyoung jeongyeon --times day

  # Use specific subs WITHOUT idol terms (keep default count=5)
  python -m redditmedia.tools.matrix_download --no-terms --subs tzuyu TzuyuTWICE

  # Use specific subs WITHOUT idol terms for day and week (keep default count=5)
  python -m redditmedia.tools.matrix_download --no-terms --subs tzuyu TzuyuTWICE --times day week

  # Use specific search terms for specific subs for day and week (keep default count=5)
  python -m redditmedia.tools.matrix_download --idols tzuyu --subs twicensfw twicexnice --times day week

  # No terms; let tool pick default GROUP subs
  python -m redditmedia.tools.matrix_download --no-terms --group-subs

  # No terms; pick idol-specific default subs
  python -m redditmedia.tools.matrix_download --no-terms --idol-subs

  # Video-only, week+month, 150 per combo, skip <200 upvotes, pick top
  python -m redditmedia.tools.matrix_download --type video --times week month --count 150 --min-score 200 --pick top

  # Random selection among survivors
  python -m redditmedia.tools.matrix_download --use-terms --times month --count 30 --pick random

  # Guarded single-sub run
  python -m redditmedia.tools.matrix_download --subs kpopfap --strict-single
"""

# ----------------------------- Defaults --------------------------------

# Hub sub (used when --use-terms and no --subs)
HUB_SUB = "kpopfap"

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

# Default pools used only when --no-terms AND no --subs were provided.
PERSONAL_SUBS = [
    # TWICE
    "myouimina", "nayeon", "jeongyeon", "momo", "sana", "jihyo", "dahyun", "chaeyoung", "tzuyu", "TzuyuTWICE",
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
DEFAULT_TIMES = ["week"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser("Matrix downloader for idols × subreddit × time")

    # Mode selection (all runtime-configurable)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--use-terms", dest="use_terms", action="store_true", default=True,
                       help="Search using idol terms (default).")
    group.add_argument("--no-terms", dest="use_terms", action="store_false",
                       help="Do NOT use search terms.")

    pool = p.add_mutually_exclusive_group()
    pool.add_argument(
        "--group-subs",
        dest="use_group_subs",
        action="store_true",
        default=None,  # <-- important: None means "not explicitly chosen"
        help="Use group-oriented subs (implies --no-terms if --subs not provided).",
    )
    pool.add_argument(
        "--idol-subs",
        dest="use_group_subs",
        action="store_false",
        help="Use idol-specific subs (implies --no-terms if --subs not provided).",
    )
    pool.add_argument(
        "--all-subs",
        dest="use_all_subs",
        action="store_true",
        help="Use BOTH group and idol-specific subs (implies --no-terms if --subs not provided).",
    )

    # Scope
    p.add_argument("--subs", "-s", nargs="+", default=None,
                   help="Target these subreddits (overrides default pools).")

    # Term/time/media controls
    p.add_argument("--idols", "-i", nargs="+", default=DEFAULT_IDOLS,
                   help="Search terms (used only with --use-terms).")
    p.add_argument("--times", "-t", nargs="+", default=DEFAULT_TIMES,
                   help="Time filters: day, week, month, year, all (default: day).")
    p.add_argument("--count", "-n", type=int, default=5,
                   help="Number of media to fetch per combo (default: 50).")
    p.add_argument("--type", choices=["image", "video"], default=None,
                   help="Media type filter (default: any).")
    p.add_argument("--sort", choices=["top", "hot"], default="top",
                   help="Sort mode (default: top).")
    p.add_argument("--min-score", type=int, default=None,
                   help="Skip posts with score (upvotes) below this number.")
    p.add_argument("--pick", choices=["top", "random"], default="top",
                   help="How to pick among filtered posts: highest scores first (top) or random (default: top).")
    p.add_argument("--blacklist", "-B", nargs="+", default=[
        "lovelyz", "fromis", "rose_queen", "rose queen", "gugudan", "AOA", "tripleS"
    ], help="Case-insensitive title keywords/phrases to exclude (space/underscore variants are treated the same).")
    p.add_argument("--sleep", type=float, default=0.0,
                   help="Sleep seconds between combos (default: 0).")

    # Safety
    p.add_argument("--strict-single", action="store_true",
                   help="Error if more than one subreddit is provided.")

    return p.parse_args()


async def run_matrix(ns: argparse.Namespace) -> None:
    # If a pool flag was chosen (or all-subs) and the user didn't pass explicit --subs,
    # force no-terms so we never search on non-hub subs.
    if ns.subs is None and (getattr(ns, "use_all_subs", False) or ns.use_group_subs is not None):
        ns.use_terms = False

    if ns.strict_single and len(ns.subs or []) != 1:
        raise SystemExit("With --strict-single, provide exactly one subreddit via --subs.")

    # Decide subreddits if not explicitly provided
    if not ns.subs:
        if ns.use_terms:
            # Using terms => hub (kpopfap)
            ns.subs = [HUB_SUB]
        else:
            # No terms => pools
            if getattr(ns, "use_all_subs", False):
                # Combine both pools; dedupe while preserving order
                ns.subs = list(dict.fromkeys(PERSONAL_GROUP_SUBS + PERSONAL_SUBS))
            else:
                # If user did not explicitly pick a pool, default to GROUP subs (old behavior)
                if ns.use_group_subs is None or ns.use_group_subs is True:
                    ns.subs = PERSONAL_GROUP_SUBS
                else:
                    ns.subs = PERSONAL_SUBS

    # Derive human-readable mode string
    if ns.use_terms:
        mode_str = "IDOL TERMS → HUB SUBS (or --subs if provided)"
    else:
        if getattr(ns, "use_all_subs", False):
            mode_str = "NO TERMS → ALL SUBS (group + idol) (or --subs if provided)"
        else:
            # If user didn’t explicitly choose, default label is GROUP SUBS
            pool_label = "GROUP SUBS" if (ns.use_group_subs is None or ns.use_group_subs is True) else "IDOL-SPECIFIC SUBS"
            mode_str = f"NO TERMS → {pool_label} (or --subs if provided)"

    print(f"\n=== MODE: {mode_str} ===")

    grand_total = 0
    combos = 0
    t0 = perf_counter()

    # Aggregation containers for unified report
    all_outcomes: List[Dict[str, Any]] = []
    grand_fetched = grand_saved = grand_skipped = grand_failed = 0

    # Shared client
    reddit = await RedditClientManager.get_client()

    try:
        for sub in ns.subs:
            # Search terms vs sentinel
            term_list: List[Optional[str]] = (ns.idols if ns.use_terms else [None])

            for term in term_list:
                for tf in ns.times:
                    human_term = (term if term is not None else "(no terms)")
                    print(
                        (
                            f"\n=== Running combo: sub={sub} | term={human_term} | "
                            f"time={tf} | sort={ns.sort} | count={ns.count} | type={ns.type or 'any'} ==="
                            f"{f' | min_score={ns.min_score}' if ns.min_score is not None else ''}"
                            f" | pick={ns.pick}"
                            f"{f' | blacklist={len(ns.blacklist)} terms' if getattr(ns, 'blacklist', None) else ''}"
                        )
                    )

                    pipe = DownloaderPipeline(
                        subreddits=[sub],
                        search_terms=([term] if (ns.use_terms and term is not None) else []),
                        sort=ns.sort,
                        time_filter=tf,
                        media_type=ns.type,
                        media_count=ns.count,
                        min_score=ns.min_score,
                        pick_mode=ns.pick,
                        blacklist_terms=ns.blacklist,
                        close_on_exit=False,
                        external_reddit=reddit,
                        write_report=False,  # we’ll write one unified report
                    )

                    saved = await pipe.run()
                    combos += 1
                    grand_total += saved
                    print(f"[{sub} | {tf} | {human_term}] saved {saved}")

                    # Aggregate this combo's summary
                    summary = pipe.last_summary()
                    if summary:
                        grand_fetched += summary.fetched
                        grand_saved += summary.saved
                        grand_skipped += summary.skipped
                        grand_failed += summary.failed
                        combo_tag = {
                            "subreddits": [sub],
                            "search_terms": ([term] if (ns.use_terms and term is not None) else []),
                            "time_filter": tf,
                            "media_type": ns.type,
                            "sort": ns.sort,
                        }
                        for o in summary.outcomes:
                            all_outcomes.append({**o, "combo": combo_tag})

                    if ns.sleep > 0:
                        await asyncio.sleep(ns.sleep)
    finally:
        # Close shared sessions/clients
        try:
            await GlobalSession.close()
        except Exception:
            pass
        try:
            if hasattr(reddit, "close"):
                await reddit.close()
        except Exception:
            pass

    # ONE unified report for the whole matrix
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"matrix_report_{ts}.json"

    import json
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "root": str(OUTPUT_ROOT),
            "combos": combos,
            "fetched": grand_fetched,
            "saved": grand_saved,
            "skipped": grand_skipped,
            "failed": grand_failed,
            "outcomes": all_outcomes,
            "created_at": ts,
            "mode": mode_str,
        }, f, ensure_ascii=False, indent=2)

    dt = perf_counter() - t0
    print(f"\nTOTAL saved across {combos} combos: {grand_total}  (elapsed {dt:.1f}s)")
    print(f"Unified report written to: {report_path}")


def main():
    ns = parse_args()
    asyncio.run(run_matrix(ns))


if __name__ == "__main__":
    main()
