
Reddit Mass Downloader (CLI)
============================

Overview
--------
This is a Telegram‑free, local‑only media downloader built on top of your existing
`redditcommand/*` modules. It fetches Reddit posts that match your search criteria,
resolves their media (images/videos), and saves them to your Windows drive under:

    C:\Reddit\<subreddit>\

For every saved media file, a JSON sidecar with metadata is written, and a rolling
`manifest.csv` per subreddit is appended to for easy spreadsheet analysis.

Folder / Files
--------------
Add this package next to your existing `redditcommand/` package:

reddit_mass_downloader/
  ├─ __init__.py
  ├─ cli.py                     # CLI entry; parses Telegram-like strings or flags
  ├─ downloader_pipeline.py     # fetch → resolve → download → write metadata
  ├─ local_media_handler.py     # saves into C:\Reddit\<subreddit>\ + JSON sidecar + manifest.csv
  ├─ filename_utils.py          # safe filename slugs + unique-suffix helper
  └─ config_overrides.py        # output path, filename template, toggles

What it reuses from your project
--------------------------------
- `redditcommand.fetch.MediaPostFetcher` – orchestrates fetching from subreddits
- `redditcommand.utils.fetch_utils` – search, sort, dedupe, “random”, validation
- `redditcommand.handle_direct_link.MediaLinkResolver` – resolves v.redd.it, imgur, streamable,
  redgifs, twitter/x, youtube/twitch/kick via yt‑dlp, etc.
- `redditcommand.utils.media_utils.MediaDownloader` – HTTP downloading with timeouts
- `redditcommand.utils.media_utils.MediaUtils` – GIF→MP4 conversion, gallery resolution
- `redditcommand.utils.compressor.Compressor` – optional size control (disabled by default)

System requirements
-------------------
- Python 3.10+
- Packages from your existing `requirements.txt` (asyncpraw, aiohttp, Pillow, etc.)
- `ffmpeg` in PATH (for mux/convert and some resolvers)
- `yt-dlp` in PATH (for many external hosts, YouTube/Twitter/etc.)

Environment / Reddit API
------------------------
Your existing `redditcommand.config.RedditClientManager` must be configured (via your `.env`
or however your project is already set up) so the downloader can authenticate to Reddit.

Installation
------------
1) Keep your existing repository layout. Add `reddit_mass_downloader/` as shown above.
2) Ensure `ffmpeg` and `yt-dlp` are installed and on PATH.
3) Verify your Reddit credentials work with the existing code (`RedditClientManager`).

Running
-------
You can pass a Telegram‑style command or standard CLI flags.

Telegram‑style examples:
    python -m reddit_mass_downloader.cli /r year kpop sana 5 image
    python -m reddit_mass_downloader.cli /r month kpop,twice momo 10 video
    python -m reddit_mass_downloader.cli /r all random 20

Flag examples:
    python -m reddit_mass_downloader.cli --subs kpop --time year --count 5 --type image sana
    python -m reddit_mass_downloader.cli --subs kpop,twice --sort hot --count 10 momo

Parsing rules (Telegram‑style)
------------------------------
Format:  /r [time_filter?] <subreddits> [terms...] [count?] [type?]

- Leading token `/r` is optional (you can also write just `r` or `r/`)
- `time_filter` (optional): one of `all, year, month, week, day`
- `subreddits` (required): comma‑separated, e.g. `kpop,twice` (or `random`)
- `terms` (optional): any tokens not recognized as count/type are treated as search terms
- `count` (optional): any integer token becomes the requested number of media
- `type` (optional): `image` or `video`
- If a time_filter is provided, the downloader defaults to `sort=top` with that time window.
  Otherwise default sort is `hot`.

Output structure
----------------
- Root directory: `C:\Reddit`
- For each saved post, the downloader writes:
  - Media file in `C:\Reddit\<subreddit>\`
  - JSON sidecar (same basename + `.json`) containing metadata:
        id, title, author, subreddit, permalink, original url, resolved_url,
        created_utc, score, upvote_ratio, num_comments, flair, saved_path
  - `manifest.csv` per subreddit (append‑only), one row per saved file

Filenames
---------
Controlled by `reddit_mass_downloader/config_overrides.py`:

    FILENAME_TEMPLATE = "{created}_{id}_{slug}{ext}"

Where:
- `created`  : UTC timestamp (YYYYMMDD_HHMMSS)
- `id`       : Reddit post ID
- `slug`     : sanitized/shortened title (lowercase, underscores, alnum only)
- `ext`      : file extension resolved from the target (e.g. .jpg, .mp4)

If a filename already exists, a numeric suffix like `(2)` is appended.

Configuration
-------------
`reddit_mass_downloader/config_overrides.py` controls:
- `OUTPUT_ROOT`             : default `C:\Reddit`
- `FILENAME_TEMPLATE`       : filename pattern
- `WRITE_SUBREDDIT_MANIFEST`: write per‑subreddit `manifest.csv` (True/False)
- `ENABLE_COMPRESSION`      : optional size control using your Compressor
- `MAX_FILE_SIZE_MB`        : size target if compression is enabled

Compression is OFF by default for a pure downloader. If you enable it, the file may be
remuxed/compressed to meet the size threshold and the final path will be used for metadata.

Notes & Behavior
----------------
- The downloader does NOT upload anywhere and does NOT use Telegram APIs.
- If a post URL is a Reddit gallery, the first valid image is chosen (via your utility).
- v.redd.it videos are downloaded with best DASH video; if DASH audio exists it is merged
  (via `ffmpeg`), otherwise the video‑only track is saved.
- For many external hosts (YouTube/Twitter/Twitch/etc.), `yt-dlp` is used; ensure it is on PATH.
- The code swallows per‑post errors so a single failure doesn’t stop the entire batch.

Common issues & troubleshooting
-------------------------------
1) `ffmpeg` not found
   - Install ffmpeg and ensure it’s in PATH (`ffmpeg -version` should work).

2) `yt-dlp` not found
   - Install `yt-dlp` and ensure it’s in PATH (`yt-dlp --version` should work).

3) Reddit auth failures / rate-limits
   - Verify your `.env` / credentials consumed by `RedditClientManager`.
   - Reduce `count`, add search terms, or try different subreddits/time windows.
   - Respect Reddit API usage guidelines.

4) No media found
   - Add/adjust search terms, try `time_filter=all`, or try `sort=hot` vs `top`.

5) Windows path permissions
   - If the program cannot write to `C:\Reddit`, run the shell as Administrator
     or change `OUTPUT_ROOT` in `config_overrides.py` to a writable folder.

Command reference (flags)
-------------------------
    --subs / -s    Comma‑separated list of subreddits (e.g. kpop,twice)
    --time / -t    One of: all, year, month, week, day   (implies sort=top)
    --count / -n   Number of items to download (default 1)
    --type         image or video
    --sort         hot (default) or top
    terms...       Remaining tokens become search terms

Examples
--------
    # All‑time top, 5 images matching "sana" from r/kpop
    python -m reddit_mass_downloader.cli /r all kpop sana 5 image

    # Last month’s top 10 videos from kpop or twice, term "momo"
    python -m reddit_mass_downloader.cli /r month kpop,twice momo 10 video

    # Using flags; hot posts by default, 10 items, search term momo
    python -m reddit_mass_downloader.cli --subs kpop,twice --count 10 momo

Extending
---------
- Batch/YAML profiles: add a small loader that iterates profiles and instantiates
  `DownloaderPipeline` per profile.
- Progress bars: wrap per‑post download with a progress reporter (e.g., `tqdm`).
- Console script: add a `pyproject.toml` entry point to expose `reddit-dl` command.

License / Credits
-----------------
Reuses your project’s existing modules (`redditcommand/*`). Media downloading from third‑party
hosts requires you to follow those hosts’ terms of service. Use responsibly.
