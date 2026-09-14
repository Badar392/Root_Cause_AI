"""
incident_store.py

Lightweight SQLite persistence for Root Cause AI: one row per completed
analysis run ("incident"), a status workflow on each incident, and a
remediation action tracker tied to an incident.

No new dependency — uses Python's stdlib sqlite3. The database file lives
next to app.py. Note: on ephemeral hosting (e.g. Streamlit Community Cloud's
default filesystem), this file resets on redeploy/reboot — treat it as
session/short-term history, not a durable system of record, unless the app
is deployed with a persistent volume.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidents.db")

STATUS_WORKFLOW = [
    "Detected",
    "Investigating",
    "Root Cause Identified",
    "Remediation In Progress",
    "Resolved",
    "Monitoring",
]

ACTION_STATUSES = ["Open", "In Progress", "Done"]


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't already exist. Safe to call on every run."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                framework TEXT,
                severity TEXT,
                severity_reason TEXT,
                confidence REAL,
                revenue_impact REAL,
                primary_root_cause TEXT,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'Detected',
                source_files TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                action_text TEXT NOT NULL,
                priority TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (incident_id) REFERENCES incidents (id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER,
                event TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)


def _log(incident_id, event, detail=""):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (incident_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
            (incident_id, event, detail, datetime.now().isoformat(timespec="seconds")),
        )


def save_incident(framework: str, severity: str, severity_reason: str, confidence: float,
                   revenue_impact, primary_root_cause: str, summary: str,
                   source_files: list) -> int:
    """Persist a completed run as a new incident. Returns the new incident id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO incidents
               (created_at, framework, severity, severity_reason, confidence,
                revenue_impact, primary_root_cause, summary, status, source_files)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Detected', ?)""",
            (
                datetime.now().isoformat(timespec="seconds"), framework, severity, severity_reason,
                confidence, revenue_impact, primary_root_cause, summary,
                json.dumps(source_files or []),
            ),
        )
        incident_id = cur.lastrowid
    _log(incident_id, "incident_created", f"severity={severity}")
    return incident_id


def update_incident_status(incident_id: int, new_status: str) -> None:
    if new_status not in STATUS_WORKFLOW:
        raise ValueError(f"Unknown status: {new_status}")
    with _connect() as conn:
        conn.execute("UPDATE incidents SET status = ? WHERE id = ?", (new_status, incident_id))
    _log(incident_id, "status_changed", new_status)


def get_incident(incident_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return dict(row) if row else None


def list_incidents(limit: int = 50) -> list:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def find_similar_incidents(framework: str, primary_root_cause: str, exclude_id: int = None,
                            limit: int = 5) -> list:
    """Very lightweight similarity: same framework + fuzzy substring match on the
    primary root cause label. Not embeddings/ML — a transparent, explainable rule."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM incidents WHERE framework = ? ORDER BY id DESC LIMIT 200",
            (framework,),
        ).fetchall()
    root_key = (primary_root_cause or "").strip().lower()
    matches = []
    for r in rows:
        d = dict(r)
        if exclude_id is not None and d["id"] == exclude_id:
            continue
        other = (d.get("primary_root_cause") or "").strip().lower()
        if root_key and other and (root_key in other or other in root_key):
            matches.append(d)
    return matches[:limit]


def add_action(incident_id: int, action_text: str, priority: str = "Medium") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO actions (incident_id, action_text, priority, status, created_at) "
            "VALUES (?, ?, ?, 'Open', ?)",
            (incident_id, action_text, priority, datetime.now().isoformat(timespec="seconds")),
        )
        action_id = cur.lastrowid
    _log(incident_id, "action_added", action_text)
    return action_id


def update_action_status(action_id: int, new_status: str) -> None:
    if new_status not in ACTION_STATUSES:
        raise ValueError(f"Unknown action status: {new_status}")
    with _connect() as conn:
        conn.execute(
            "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, datetime.now().isoformat(timespec="seconds"), action_id),
        )
    with _connect() as conn:
        row = conn.execute("SELECT incident_id FROM actions WHERE id = ?", (action_id,)).fetchone()
    if row:
        _log(row["incident_id"], "action_status_changed", new_status)


def list_actions(incident_id: int = None) -> list:
    with _connect() as conn:
        if incident_id is not None:
            rows = conn.execute(
                "SELECT * FROM actions WHERE incident_id = ? ORDER BY id DESC", (incident_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM actions ORDER BY id DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]


def get_audit_log(incident_id: int = None, limit: int = 100) -> list:
    with _connect() as conn:
        if incident_id is not None:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE incident_id = ? ORDER BY id DESC LIMIT ?",
                (incident_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
