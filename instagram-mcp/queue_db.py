"""Очередь отложенных публикаций (SQLite)."""
import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("IG_SESSION_DIR", Path.home() / ".instagram-mcp")) / "queue.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT NOT NULL,
            kind TEXT NOT NULL,
            paths TEXT NOT NULL,
            caption TEXT NOT NULL DEFAULT '',
            cover TEXT NOT NULL DEFAULT '',
            run_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT NOT NULL DEFAULT '',
            finished_at REAL
        )"""
    )
    return conn


def add(account: str, kind: str, paths: list[str], caption: str, cover: str, run_at: float) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO posts (account, kind, paths, caption, cover, run_at) VALUES (?,?,?,?,?,?)",
            (account, kind, json.dumps(paths), caption, cover, run_at),
        )
        return cur.lastrowid


def list_posts(status: str = "pending") -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM posts WHERE status=? ORDER BY run_at", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def cancel(post_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE posts SET status='cancelled' WHERE id=? AND status='pending'", (post_id,))
        return cur.rowcount == 1


def last_published_at(account: str) -> float:
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(finished_at) FROM posts WHERE account=? AND status='done'", (account,)
        ).fetchone()
    return row[0] or 0.0


def claim_due(min_gap: float) -> dict | None:
    """Атомарно забирает одну просроченную публикацию (не чаще min_gap секунд на аккаунт)."""
    now = time.time()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT * FROM posts WHERE status='pending' AND run_at<=? ORDER BY run_at", (now,)
        ).fetchall()
        for r in rows:
            last = c.execute(
                "SELECT MAX(finished_at) FROM posts WHERE account=? AND status='done'", (r["account"],)
            ).fetchone()[0] or 0.0
            if now - last < min_gap:
                continue
            c.execute("UPDATE posts SET status='running' WHERE id=?", (r["id"],))
            return dict(r)
    return None


def finish(post_id: int, ok: bool, result: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE posts SET status=?, result=?, finished_at=? WHERE id=?",
            ("done" if ok else "failed", result, time.time(), post_id),
        )
