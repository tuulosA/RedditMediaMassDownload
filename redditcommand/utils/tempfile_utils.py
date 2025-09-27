# redditcommand/utils/tempfile_utils.py

import tempfile
import os
import shutil
import re

from typing import Optional
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()

class TempFileManager:
    @staticmethod
    def create_temp_dir(prefix: str) -> str:
        """
        Creates a temporary directory with the given prefix.
        """
        try:
            temp_dir = tempfile.mkdtemp(prefix=prefix)
            return temp_dir
        except Exception as e:
            logger.error(f"Error creating temporary directory with prefix '{prefix}': {e}", exc_info=True)
            raise

    @staticmethod
    def cleanup_file(path: str) -> None:
        """
        Deletes a file or directory and its parent if empty.
        """
        if not path:
            return
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.debug(f"Deleted file: {path}")
            elif os.path.isdir(path):
                # Recursively delete the temp directory
                shutil.rmtree(path)
                logger.debug(f"Deleted directory: {path}")
        except Exception as e:
            logger.error(f"Cleanup failed for {path}: {e}", exc_info=True)

    @staticmethod
    def extract_post_id_from_url(url: str) -> Optional[str]:
        match = re.search(r"comments/([a-z0-9]+)", url) or re.search(r"reddit_(\w+)", url)
        return match.group(1) if match else None
