from pathlib import Path

# Root where everything is saved
OUTPUT_ROOT = Path(r"C:\Reddit").resolve()

# Filename pattern – available keys: id, created, subreddit, slug, ext
FILENAME_TEMPLATE = "{created}_{id}_{slug}{ext}"

# Append one CSV manifest per subreddit (append-only)
WRITE_SUBREDDIT_MANIFEST = True

# Compression is disabled here (pure downloader).
# If you later want it, wire your Compressor from redditcommand.utils.compressor.
ENABLE_COMPRESSION = False
MAX_FILE_SIZE_MB = 5_000  # only used if compression enabled

# Ensure root exists on import
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
