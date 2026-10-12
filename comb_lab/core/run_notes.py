"""Shared per-run experiment notes used by script generation and analysis."""
from __future__ import annotations

from pathlib import Path

NOTE_FILENAME = "experiment_notes.md"


def _default_note_text(run_name: str, cycles: int) -> str:
    return (
        f"# Experiment notes: {run_name}\n"
        f"cycles={cycles}\n"
        "# Add concise notes below. Non-comment lines are shown on the overlap chart.\n"
        "# Add node allocation, transport, or rerun details below.\n\n"
    )


def note_path_for_run_dir(run_dir: Path) -> Path | None:
    """Return the shared note path for a midcomm/no_midcomm run directory."""
    if run_dir.parent.name not in {"midcomm", "no_midcomm"}:
        return None
    return run_dir.parent.parent / "analysis" / "notes" / run_dir.name / NOTE_FILENAME


def create_run_notes(jobs: list[dict]) -> list[Path]:
    """Create editable note files for generated runs without overwriting notes."""
    note_cycles: dict[Path, int] = {}
    for job in jobs:
        note_path = note_path_for_run_dir(Path(job["output_dir"]))
        if note_path is not None:
            cycles = int(job.get("grid", {}).get("cycles", 5))
            previous_cycles = note_cycles.setdefault(note_path, cycles)
            if previous_cycles != cycles:
                raise ValueError(f"Conflicting cycle counts for {note_path}")

    for note_path, cycles in note_cycles.items():
        note_path.parent.mkdir(parents=True, exist_ok=True)
        if not note_path.exists():
            note_path.write_text(_default_note_text(note_path.parent.name, cycles))
    return sorted(note_cycles)


def remove_orphaned_default_run_note(run_dir: Path) -> bool:
    """Remove an untouched note when neither compute mode retains run data."""
    note_path = note_path_for_run_dir(run_dir)
    if note_path is None or not note_path.is_file():
        return False

    payload_dir = run_dir.parent.parent
    for compute_mode in ("midcomm", "no_midcomm"):
        sibling_run = payload_dir / compute_mode / run_dir.name
        if sibling_run.is_dir() and any(sibling_run.iterdir()):
            return False

    lines = note_path.read_text().splitlines()
    meaningful = [
        line.strip()
        for line in lines
        if line.strip() and not line.startswith("#") and not line.startswith("cycles=")
    ]
    if meaningful:
        return False

    note_path.unlink()
    for compute_mode in ("midcomm", "no_midcomm"):
        compute_dir = payload_dir / compute_mode
        if compute_dir.is_dir() and not any(compute_dir.iterdir()):
            compute_dir.rmdir()
    parent = note_path.parent
    topology_dir = payload_dir.parent
    while parent != topology_dir and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return True