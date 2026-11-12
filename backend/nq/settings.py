# backend/nq/settings.py
"""
NQ connection settings, read from environment variables (loaded from .env).

In development NQ_DB_HOST / NQ_DB_LOCAL_PORT point at the Docker MySQL; in
production they point at the autossh tunnel on 127.0.0.1. The code never knows
or cares which one it is, and never opens SSH connections itself.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class NQSettings:
    host: str = "127.0.0.1"
    port: int = 3307
    database: str = ""
    user: str = ""
    password: str = ""
    wb_user: str = ""
    wb_password: str = ""
    connect_timeout: int = 5     # seconds
    query_timeout: int = 10      # seconds (read/write timeout on the socket)
    pool_size: int = 3
    cache_ttl: int = 60          # seconds

    @classmethod
    def from_env(cls) -> "NQSettings":
        return cls(
            host=os.getenv("NQ_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("NQ_DB_LOCAL_PORT", "3307")),
            database=os.getenv("NQ_DB_NAME", ""),
            user=os.getenv("NQ_DB_USER", ""),
            password=os.getenv("NQ_DB_PASS", ""),
            wb_user=os.getenv("NQ_WB_USER", ""),
            wb_password=os.getenv("NQ_WB_PASS", ""),
        )
