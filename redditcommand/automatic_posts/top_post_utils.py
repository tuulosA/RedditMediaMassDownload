# redditcommand/utils/top_post_utils.py

import os
import re
from shutil import copy2
from datetime import datetime
from telegram import Update, Bot
from typing import Union
from asyncpraw.models import Submission

from redditcommand.utils.log_manager import LogManager

logger = LogManager.setup_main_logger()

SubredditTarget = Union[Update, tuple[Bot, int]]


class TopPostUtils:
    @staticmethod
    def build_caption(post: Submission, label: str) -> str:
        title = post.metadata.get("title", "No title")
        author = post.metadata.get("author", "[deleted]")
        raw_flair = post.metadata.get("link_flair_text")
        upvotes = post.metadata.get("upvotes", 0)
        top_comment = post.metadata.get("top_comment")

        if isinstance(raw_flair, str):
            cleaned_flair = re.sub(r":[^:\s]+:", "", raw_flair).strip()
        else:
            cleaned_flair = ""

        flair_text = f" [{cleaned_flair}]" if cleaned_flair and cleaned_flair.lower() != "none" else ""
        caption = f"{label} ({upvotes} upvotes)\n\n{title}{flair_text} by u/{author}"

        if top_comment:
            if isinstance(top_comment, str):
                caption += f"\n\n💬 Top comment:\n{top_comment[:500]}"
            else:
                comment_author = post.metadata.get("top_comment_author", "[deleted]")
                caption += f"\n\n💬 Top comment by u/{comment_author}:\n{top_comment.body[:500]}"
        return caption

    @staticmethod
    def archive_post(post: Submission, file_path: str, time_filter: str, timezone, base_dir: str):
        now = datetime.now(tz=timezone)
        subfolder = {
            "day": "daily",
            "week": "weekly",
            "month": "monthly",
            "year": "yearly"
        }.get(time_filter, "misc")

        suffix = now.strftime({
            "day": "_%Y-%m-%d",
            "week": "_week_%W_%Y",
            "month": "_month_%m_%Y",
            "year": "_year_%Y"
        }.get(time_filter, ""))

        save_dir = os.path.join(base_dir, subfolder)
        os.makedirs(save_dir, exist_ok=True)

        name_root, ext = os.path.splitext(os.path.basename(file_path))
        new_name = f"{name_root}{suffix}{ext}"
        dest_path = os.path.join(save_dir, new_name)
        metadata_path = os.path.join(save_dir, f"{name_root}{suffix}.txt")

        copy2(file_path, dest_path)
        logger.info(f"Saved media copy to {dest_path}")

        with open(metadata_path, "w", encoding="utf-8") as f:
            f.write(f"Title: {post.metadata.get('title', 'N/A')}\n")
            f.write(f"Author: {post.metadata.get('author', '[deleted]')}\n")
            f.write(f"Upvotes: {post.metadata.get('upvotes', 0)}\n")
            if post.metadata.get("link_flair_text"):
                f.write(f"Flair: {post.metadata['link_flair_text']}\n")
            top_comment = post.metadata.get("top_comment")
            author = post.metadata.get("top_comment_author", "[deleted]")
            if top_comment:
                if isinstance(top_comment, str):
                    f.write("\nTop comment:\n" + top_comment.strip()[:1000] + "\n")
                else:
                    f.write(f"\nTop comment by u/{author}:\n{top_comment.body.strip()[:1000]}\n")
            f.write(f"\nReddit URL: https://reddit.com/comments/{post.id}\n")
        logger.info(f"Saved metadata to {metadata_path}")

    @staticmethod
    async def send_failure_message(target: SubredditTarget, message: str):
        if isinstance(target, Update):
            await target.message.reply_text(message)
        else:
            bot, chat_id = target
            await bot.send_message(chat_id=chat_id, text=message)
