import os
from dotenv import load_dotenv
from telegram.ext import Application

from redditcommand.utils.log_manager import LogManager
from telegram_utils.regist import TelegramRegistrar

def main():
    load_dotenv()

    LogManager.setup_error_logging("logs/error.log")
    logger = LogManager.setup_main_logger()
    logger.info("Bot is starting...")

    telegram_api_key = os.getenv("TELEGRAM_API_KEY")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_api_key or not telegram_chat_id:
        logger.error("Missing TELEGRAM_API_KEY or TELEGRAM_CHAT_ID in environment.")
        return

    application = Application.builder().token(telegram_api_key).build()

    TelegramRegistrar.register_command_handlers(application)
    TelegramRegistrar.register_jobs(application, int(telegram_chat_id))

    logger.info("Bot is now polling...")
    application.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error starting the bot: {e}")