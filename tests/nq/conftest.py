"""
NQ tests use their OWN settings pointing at the Docker dev MySQL
(docker compose -f docker-compose.dev.yml up -d nq_mysql, port 3308). They never
read .env, so they can never touch the production tunnel or real NQ.
DB-backed tests are skipped when that container is not running.
"""
import os
import socket

import pytest

os.environ.setdefault("MONGO_CONNECTION_STRING", "mongodb://localhost:27018/")  # never connected in these tests

from backend.nq import cache, repository
from backend.nq.settings import NQSettings

DEV_PORT = int(os.getenv("NQ_DEV_MYSQL_PORT", "3308"))
TODAY_SEED = "2026-10-14"


def dev_settings(**kw) -> NQSettings:
    base = dict(host="127.0.0.1", port=DEV_PORT, database="jhsdb",
                user="nq_ro", password="dev_ro_pass",
                wb_user="nq_wb", wb_password="dev_wb_pass")
    base.update(kw)
    return NQSettings(**base)


def _dev_mysql_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", DEV_PORT), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture
def nq_db():
    if not _dev_mysql_up():
        pytest.skip("Docker dev MySQL not running (docker compose -f docker-compose.dev.yml up -d nq_mysql)")
    repository.configure(dev_settings())
    yield repository
    repository.configure(dev_settings())


@pytest.fixture
def nq_down():
    """Settings pointing at a port nothing listens on."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()
    repository.configure(dev_settings(port=free_port, connect_timeout=1))
    yield repository
    repository.configure(dev_settings())
    cache.clear()
