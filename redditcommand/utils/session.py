# redditcommand/utils/session.py

import aiohttp

class GlobalSession:
    _session = None

    @classmethod
    async def get(cls):
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
        return cls._session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()