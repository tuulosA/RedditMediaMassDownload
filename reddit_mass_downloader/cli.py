import argparse
import asyncio
from typing import List, Tuple, Optional

from reddit_mass_downloader.downloader_pipeline import DownloaderPipeline
from redditcommand.utils.session import GlobalSession

VALID_TIMES = {"all", "year", "month", "week", "day"}
VALID_TYPES = {"image", "video"}


def parse_telegramish(args: List[str]) -> Tuple[Optional[str], List[str], List[str], int, Optional[str], str]:
    """Return (time_filter, subreddits, search_terms, count, type, sort)"""
    tokens = [t for t in args if t and t not in ("/r", "r", "r/")]

    time_filter = tokens[0].lower() if tokens and tokens[0].lower() in VALID_TIMES else None
    tokens = tokens[1:] if time_filter else tokens

    if not tokens:
        raise SystemExit("No subreddits provided. Example: /r year kpop sana 5 image")

    subreddits = [s.strip().lstrip("r/") for s in tokens[0].split(",") if s.strip()]
    tokens = tokens[1:]

    media_count = 1
    media_type = None
    search_terms: List[str] = []
    sort = "top" if time_filter else "hot"

    for t in tokens:
        low = t.lower()
        if low.isdigit():
            media_count = int(low)
        elif low in VALID_TYPES:
            media_type = low
        else:
            search_terms.append(t)

    return time_filter, subreddits, search_terms, media_count, media_type, sort


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reddit Mass Downloader (CLI)")
    p.add_argument("cmd", nargs="*", help="Telegram-like command tokens, e.g. /r year kpop sana 5 image")
    p.add_argument("--subs", "-s", help="Comma-separated subreddits (fallback if not using telegram-like)")
    p.add_argument("--time", "-t", choices=sorted(VALID_TIMES), help="time_filter for top/search")
    p.add_argument("--count", "-n", type=int, default=1, help="number of media to download")
    p.add_argument("--type", choices=sorted(VALID_TYPES), help="media type filter")
    p.add_argument("--sort", choices=["hot", "top"], default="hot", help="sort mode")
    p.add_argument("terms", nargs=argparse.REMAINDER, help="search terms (space-separated)")
    return p


async def main_async():
    ap = build_argparser()
    ns = ap.parse_args()

    if ns.cmd:
        time_filter, subs, terms, count, mtype, sort = parse_telegramish(ns.cmd)
    else:
        subs = [s.strip().lstrip("r/") for s in (ns.subs or "").split(",") if s.strip()]
        if not subs:
            raise SystemExit("Provide subreddits via telegram-like tokens or --subs.")
        time_filter = ns.time
        terms = ns.terms or []
        count = ns.count
        mtype = ns.type
        sort = ("top" if time_filter else ns.sort)

    pipe = DownloaderPipeline(
        subreddits=subs,
        search_terms=terms,
        sort=sort,
        time_filter=time_filter,
        media_type=mtype,
        media_count=count,
    )

    saved = 0
    try:
        saved = await pipe.run()
    finally:
        # Extra guard in case pipeline exits early
        try:
            await GlobalSession.close()
        except Exception:
            pass

    print("Saved", saved, "file(s) to C:\\Reddit")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
