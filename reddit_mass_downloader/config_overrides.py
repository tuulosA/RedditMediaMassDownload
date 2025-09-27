from pathlib import Path

OUTPUT_ROOT = Path(r"C:\Reddit").resolve()
FILENAME_TEMPLATE = "{created}_{id}_{slug}{ext}"
WRITE_SUBREDDIT_MANIFEST = True

# Where JSON run reports are saved
REPORT_DIR = (OUTPUT_ROOT / "_reports").resolve()

ENABLE_COMPRESSION = False
MAX_FILE_SIZE_MB = 5_000

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
