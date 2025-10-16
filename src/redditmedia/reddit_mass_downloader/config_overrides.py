from pathlib import Path

OUTPUT_ROOT = Path(r"C:\Reddit").resolve()
FILENAME_TEMPLATE = "{subreddit}_{title_slug}_{id}{ext}"
WRITE_SUBREDDIT_MANIFEST = True
WRITE_JSON_SIDECARS = False          # NEW: disable .json sidecars next to media
WRITE_RUN_REPORT_JSON = False        # NEW: disable pipeline run report JSON

# Where JSON run reports are saved
REPORT_DIR = (OUTPUT_ROOT / "_reports").resolve()

ENABLE_COMPRESSION = False
MAX_FILE_SIZE_MB = 5_000
MAX_FILENAME_LEN = 200

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
