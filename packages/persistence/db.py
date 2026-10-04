from __future__ import annotations
 
import os
from collections.abc import Iterator,Generator
from contextlib import contextmanager
from pathlib import Path
 
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL","")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to .env, e.g.\n"
        "  DATABASE_URL=postgresql://comply:comply@localhost:5432/comply"
    )


MIN_SIZE = int(os.getenv("DB_POOL_MIN", "1"))
MAX_SIZE = int(os.getenv("DB_POOL_MAX", "5"))

OPEN_TIMEOUT = float(os.getenv("DB_OPEN_TIMEOUT", "10"))


POOL = ConnectionPool(conninfo=DATABASE_URL,min_size=MIN_SIZE,max_size=MAX_SIZE,open=False,kwargs={"row_factory": dict_row})

def start_database(wait:bool = True) -> None:
    POOL.open(wait=wait,timeout=OPEN_TIMEOUT)


def stop_database()-> None:
    POOL.close()


def _ensure_open() -> None:
    if POOL.closed:
        try:
            POOL.open(wait=True,timeout=OPEN_TIMEOUT)
        except psycopg.pool.PoolTimeout as e:
            raise RuntimeError(
                "The connection pool was closed and cannot be reopened. "
                "This usually means stop_database() ran while work was still "
                "in flight."
            ) from e


@contextmanager
def get_conn() -> Generator[psycopg.Connection]:
    _ensure_open()
    with POOL.connection() as conn:
        yield conn


def init_db() -> None:

    sql = (Path(__file__).parent/ "schema_sql").read_text(encoding="utf_8")
    with get_conn as conn:
        conn.execute(sql)


def healthy() -> bool:
    try:
        with get_conn() as conn, conn.cursor as cur:
            cur.execute("SELECT 1 as ok")
            row = cur.fetchone()
            return bool(row and row["ok"] == 1)
    except Exception:
        return False

if __name__ == "__main__":
    print("connecting to", DATABASE_URL.split("@")[-1])  # never print credentials
    start_database()
    print("healthy:", healthy())
 
    init_db()
    print("schema applied")
 
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        print("tables:", [r["table_name"] for r in cur.fetchall()])
 
    stop_database()




