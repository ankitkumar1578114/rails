from typing import Optional

import mysql.connector
from mysql.connector import pooling

_pool: Optional[pooling.MySQLConnectionPool] = None

DB_CONFIG = {
  # "host": "127.0.0.1",
  # "user": "root",
  # "password": "",
  # "database": "mydb",
  "host": "bwr2tjeeysysm7um7pfo-mysql.services.clever-cloud.com",
  "user": "ucg3v1n4o6kbgzk2",
  "password": "8CJNC9GDRkkpe5kPvzJw",
  "database": "bwr2tjeeysysm7um7pfo",
}


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="rails_api_pool",
            pool_size=3,
            pool_reset_session=True,
            **DB_CONFIG,
        )
    return _pool


def get_db_connection():
    return _get_pool().get_connection()
