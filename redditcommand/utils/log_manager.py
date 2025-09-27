# redditcommand/utils/log_manager.py

import logging
import os
import sys
from redditcommand.config import LogConfig


class BaseLogger:
    @staticmethod
    def setup_stream_logger(level=None):
        # allow LOG_LEVEL=DEBUG/INFO/WARNING/ERROR
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        if level is None:
            level = getattr(logging, os.getenv("LOG_LEVEL", "DEBUG").upper(), logging.INFO)

        logger = logging.getLogger()
        logger.setLevel(level)

        if not logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setLevel(level)
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    @staticmethod
    def setup_error_file_logger(log_path: str):
        logger = logging.getLogger("error_logger")
        logger.setLevel(logging.WARNING)

        if not logger.handlers:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.propagate = False
        return logger


class FileLogger:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.logger = logging.getLogger(name)
        self._setup()

    def _setup(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        if os.path.exists(self.path):
            os.remove(self.path)

        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        handler = logging.FileHandler(self.path, mode="w", encoding="utf-8")
        formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
        handler.setFormatter(formatter)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)
        self.logger.propagate = False

    def get(self):
        return self.logger


class LogManager:
    _skip_logger = None
    _accepted_logger = None
    _error_logger = None

    @classmethod
    def setup_main_logger(cls):
        return BaseLogger.setup_stream_logger()

    @classmethod
    def get_skip_logger(cls):
        if cls._skip_logger is None:
            cls._skip_logger = FileLogger("skip_debug", LogConfig.SKIP_LOG_PATH).get()
        return cls._skip_logger

    @classmethod
    def get_accepted_logger(cls):
        if cls._accepted_logger is None:
            cls._accepted_logger = FileLogger("accepted_debug", LogConfig.ACCEPTED_LOG_PATH).get()
        return cls._accepted_logger

    @classmethod
    def setup_error_logging(cls, log_path="logs/error.log"):
        if cls._error_logger is None:
            cls._error_logger = BaseLogger.setup_error_file_logger(log_path)

        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            cls._error_logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

        sys.excepthook = handle_exception
        return cls._error_logger
