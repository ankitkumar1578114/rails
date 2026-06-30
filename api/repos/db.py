import os
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

import mysql.connector
from mysql.connector import pooling

_pool: Optional[pooling.MySQLConnectionPool] = None


def get_db_config() -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "mydb"),
    }
    port = os.environ.get("DB_PORT")
    if port:
        config["port"] = int(port)
    return config


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        pool_size = int(os.environ.get("DB_POOL_SIZE", "1"))
        _pool = pooling.MySQLConnectionPool(
            pool_name="rails_api_pool",
            pool_size=pool_size,
            pool_reset_session=True,
            **get_db_config(),
        )
    return _pool


def get_db_connection() -> mysql.connector.MySQLConnection:
    return _get_pool().get_connection()


@contextmanager
def db_connection() -> Generator[mysql.connector.MySQLConnection, None, None]:
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()
