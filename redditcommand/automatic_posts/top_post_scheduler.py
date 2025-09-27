# redditcommand/automatic_posts/top_post_scheduler.py

import os
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from redditcommand.automatic_posts.top_post import TopPostManager
from redditcommand.config import TelegramConfig


class TopPostScheduler:
    TIMEZONE = TelegramConfig.LOCAL_TIMEZONE

    @classmethod
    async def run_command(cls, label: str, time_filter: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        subreddit = context.args[0].strip().lower() if context.args else None
        manager = TopPostManager(subreddit=subreddit, target=update)
        await manager.send_top_post(label, time_filter, update, archive=False)

    @classmethod
    async def run_job(cls, label: str, time_filter: str, context: ContextTypes.DEFAULT_TYPE):
        now = datetime.now(tz=cls.TIMEZONE)
        if time_filter == "month" and now.day != 1:
            return
        if time_filter == "year" and not (now.month == 1 and now.day == 1):
            return

        chat_id = int(os.getenv("TELEGRAM_CHAT_ID"))
        target = (context.bot, chat_id)

        manager = TopPostManager()
        await manager.send_top_post(label, time_filter, target, archive=True)

    @classmethod
    def generate_command(cls, label: str, time_filter: str):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await cls.run_command(label, time_filter, update, context)
        return handler

    @classmethod
    def generate_job(cls, label: str, time_filter: str):
        async def handler(context: ContextTypes.DEFAULT_TYPE):
            await cls.run_job(label, time_filter, context)
        return handler
