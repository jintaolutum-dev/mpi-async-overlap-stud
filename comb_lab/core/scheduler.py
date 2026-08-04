"""SLURM job submission and status monitoring."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


def sbatch(script_path: Path) -> str:
    """Submit a script via sbatch, return the job ID."""
    result = subprocess.run(
        ["sbatch", str(script_path)],
        capture_output=True,
        text=True,
        cwd=str(script_path.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed:\n{result.stderr}")
    # "Submitted batch job 12345"
    match = re.search(r"(\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job ID from: {result.stdout!r}")
    return match.group(1)


def squeue(job_ids: Optional[List[str]] = None, user: Optional[str] = None) -> List[Dict[str, str]]:
    """Query SLURM queue, return list of job dicts."""
    cmd = [
        "squeue",
        "--format=%i|%j|%T|%M|%R|%N",
        "--noheader",
    ]
    if job_ids:
        cmd += ["--jobs", ",".join(job_ids)]
    elif user:
        cmd += ["--user", user]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return []  # squeue not available (e.g. local dev)

    jobs = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 6:
            jobs.append(
                {
                    "job_id": parts[0].strip(),
                    "name":   parts[1].strip(),
                    "state":  parts[2].strip(),
                    "time":   parts[3].strip(),
                    "reason": parts[4].strip(),
                    "nodes":  parts[5].strip(),
                }
            )
    return jobs


def cancel(job_id: str) -> None:
    subprocess.run(["scancel", job_id], check=True)


def submit_all(scripts: List[Path]) -> Dict[str, str]:
    """Submit all scripts, return {script_path: job_id} mapping."""
    results = {}
    for script in scripts:
        try:
            job_id = sbatch(script)
            results[str(script)] = job_id
        except RuntimeError as e:
            results[str(script)] = f"ERROR: {e}"
    return results
