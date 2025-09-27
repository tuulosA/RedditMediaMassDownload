# redditcommand/utils/compressor.py

import os
import asyncio
from typing import Optional

from redditcommand.utils.tempfile_utils import TempFileManager
from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()


class Compressor:
    @staticmethod
    async def validate_and_compress(file_path: str, max_size_mb: int) -> Optional[str]:
        """
        Validate size and compress if needed.

        Returns:
          final_path to a file that is <= max_size_mb, or None if it fails.
        The original file is not deleted here. Caller owns cleanup.
        """
        if not os.path.exists(file_path):
            logger.warning(f"Validation failed: File does not exist: {file_path}")
            return None

        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        if size_mb > 100:
            logger.warning(f"Skipping file: too large to process ({size_mb:.2f} MB > 100 MB): {file_path}")
            return None

        if size_mb <= max_size_mb:
            logger.debug(f"File size is valid: {size_mb:.2f} MB <= {max_size_mb} MB")
            return file_path

        logger.warning(f"File size exceeds limit: {size_mb:.2f} MB > {max_size_mb} MB")

        temp_dir = TempFileManager.create_temp_dir("compress_")
        base = os.path.splitext(os.path.basename(file_path))[0]
        output_path = os.path.join(temp_dir, f"{base}_compressed.mp4")

        final = await Compressor.compress(
            input_path=file_path,
            output_path=output_path,
            target_size_mb=max_size_mb
        )
        if final is None:
            TempFileManager.cleanup_file(output_path)
            TempFileManager.cleanup_dir(temp_dir)
            return None
        return final

    @staticmethod
    async def compress(
        input_path: str,
        output_path: str,
        target_size_mb: int = 50,
        max_attempts: int = 3,
        timeout_seconds: int = 600,
    ) -> Optional[str]:
        """
        Try up to max_attempts to produce a file at output_path that is <= target_size_mb.
        Returns output_path on success, or None on failure.
        """
        crf = 28
        max_bitrate = 2500  # kbps, for later attempts only

        for attempt in range(max_attempts):
            try:
                logger.info(
                    f"Compression attempt {attempt + 1} for {input_path} with CRF={crf}"
                    + (f", Max Bitrate={max_bitrate}kbps" if attempt > 0 else "")
                )

                cmd = [
                    "ffmpeg", "-y", "-i", input_path,
                    "-map", "0:v:0?", "-map", "0:a:0?",
                    "-vcodec", "libx264", "-crf", str(crf), "-preset", "fast",
                    "-vf", "scale='min(1280,iw)':-2",
                    "-pix_fmt", "yuv420p",
                    "-acodec", "aac", "-b:a", "96k",
                    "-movflags", "+faststart",
                ]

                if attempt > 0:
                    cmd += [
                        "-maxrate", f"{max_bitrate}k",
                        "-bufsize", f"{max_bitrate * 2}k",
                    ]

                cmd.append(output_path)

                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    logger.error("Compression timed out")
                    TempFileManager.cleanup_file(output_path)
                    continue

                if proc.returncode != 0:
                    logger.error(f"Compression failed: {stderr.decode()}")
                    TempFileManager.cleanup_file(output_path)
                    continue

                new_size = os.path.getsize(output_path) / (1024 * 1024)
                if new_size <= target_size_mb:
                    logger.info(f"Compression successful: {new_size:.2f} MB <= {target_size_mb} MB")
                    return output_path
                else:
                    logger.warning(f"Still too large: {new_size:.2f} MB > {target_size_mb} MB")
                    TempFileManager.cleanup_file(output_path)

            except Exception as e:
                logger.error(f"Compression error (attempt {attempt + 1}): {e}", exc_info=True)

            crf = min(crf + 1, 32)
            max_bitrate = max(max_bitrate - 300, 1500)

        logger.error(f"Failed to compress {input_path} below {target_size_mb} MB after {max_attempts} attempts.")
        return None
