"""SQLite-based run tracking."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"


def _conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def init_db(db_path: Path = DB_PATH) -> None:
    with _conn(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id      TEXT PRIMARY KEY,
                experiment  TEXT NOT NULL,
                params      TEXT NOT NULL,
                script_path TEXT,
                output_dir  TEXT,
                slurm_job_id TEXT,
                status      TEXT DEFAULT 'pending',
                submit_time TEXT,
                finish_time TEXT,
                notes       TEXT
            );
            CREATE TABLE IF NOT EXISTS results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                case_label  TEXT,
                phase       TEXT NOT NULL,
                metric      TEXT NOT NULL,
                value       REAL NOT NULL,
                unit        TEXT DEFAULT 's',
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS metadata (
                run_id  TEXT NOT NULL,
                key     TEXT NOT NULL,
                value   TEXT,
                PRIMARY KEY (run_id, key),
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            """
        )


def register_run(
    run_id: str,
    experiment: str,
    params: dict,
    script_path: str,
    output_dir: str,
    db_path: Path = DB_PATH,
) -> None:
    init_db(db_path)
    with _conn(db_path) as con:
        con.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, experiment, params, script_path, output_dir)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, experiment, json.dumps(params), script_path, output_dir),
        )


def update_status(
    run_id: str,
    status: str,
    slurm_job_id: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    now = datetime.utcnow().isoformat()
    with _conn(db_path) as con:
        if slurm_job_id:
            con.execute(
                "UPDATE runs SET status=?, slurm_job_id=?, submit_time=? WHERE run_id=?",
                (status, slurm_job_id, now, run_id),
            )
        else:
            field = "finish_time" if status in ("done", "failed") else "submit_time"
            con.execute(
                f"UPDATE runs SET status=?, {field}=? WHERE run_id=?",
                (status, now, run_id),
            )


def list_runs(experiment: Optional[str] = None, db_path: Path = DB_PATH) -> List[dict]:
    init_db(db_path)
    with _conn(db_path) as con:
        if experiment:
            rows = con.execute(
                "SELECT * FROM runs WHERE experiment=? ORDER BY submit_time DESC",
                (experiment,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM runs ORDER BY submit_time DESC"
            ).fetchall()
    return [dict(r) for r in rows]
