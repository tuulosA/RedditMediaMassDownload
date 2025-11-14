RedditMedia – Telegram bot + mass downloader
===========================================

Install (local dev)
-------------------
In the repo root:

```bash
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install .[telegram]    # or just `pip install .` if you only want CLI
```

Environment variables
---------------------
Create a `.env` next to `pyproject.toml` and drop in:

- `TELEGRAM_API_KEY=`
- `TELEGRAM_CHAT_ID=`
- `REDDIT_CLIENT_ID=`
- `REDDIT_CLIENT_SECRET=`
- `REDDIT_USER_AGENT=`
- `REDDIT_USERNAME=`
- `REDDIT_PASSWORD=`

Telegram bot
------------
- Make sure `.env` is filled in.
- Start the bot:

  ```bash
  redditmedia-bot
  ```

- Talk to the bot from the chat id you configured and use commands like:
  - `/r cats` – hot posts with media from r/cats
  - `/r year kpop sana 5 image` – up to 5 images from top of the year in r/kpop matching “sana”
  - `/rtopday` / `/rtopweek` / `/rtopmonth` / `/rtopyear` – scheduled “top post” jobs

Mass downloader CLI
-------------------
The CLI uses the same logic but writes files to `C:\Reddit`.

Basic usage (Telegram-style):

```bash
redditmedia-download /r year kpop sana 5 image
```

Or with flags:

```bash
redditmedia-download --subs kpop --time year --count 5 --type image sana
```

- `--subs` / `-s`: comma-separated subreddits (`kpop,twice`)
- `--time` / `-t`: `day`, `week`, `month`, `year`, `all`
- `--count` / `-n`: how many media items to grab
- `--type`: `image` or `video`
- remaining words are search terms
