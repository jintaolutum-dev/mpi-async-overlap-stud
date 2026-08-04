#!/usr/bin/env python3
"""mpi_lab – MPI experiment lifecycle manager.

Usage:
  python mpi_lab.py preview  --config config/comb_cm4.yaml
  python mpi_lab.py gen      --config config/comb_cm4.yaml [--dry-run]
  python mpi_lab.py submit   --config config/comb_cm4.yaml [--dry-run]
  python mpi_lab.py status   [--experiment NAME]
  python mpi_lab.py jobs     [--user USER]
    python mpi_lab.py gui      [--web] [--host 127.0.0.1] [--port 8765]
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.matrix import load_config, expand_matrix
from core.generator import generate_all, generate_job
from core.scheduler import submit_all, squeue
from core.db import register_run, update_status, list_runs, init_db

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
@click.group()
def cli():
    """mpi_lab: MPI experiment lifecycle manager."""


# ── preview ──────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True),
              help="Path to experiment YAML config.")
def preview(config: str):
    """Show the full job matrix without generating anything."""
    cfg = load_config(config)
    jobs = expand_matrix(cfg)

    table = Table(title=f"Experiment: {cfg.get('name', '?')}  ({len(jobs)} jobs)",
                  box=box.ROUNDED)
    table.add_column("#",           style="dim", width=4)
    table.add_column("MPI",         style="cyan")
    table.add_column("Topology",    style="green")
    table.add_column("Grid",        style="yellow")
    table.add_column("Compute",     style="magenta")
    table.add_column("Cases",       style="white")
    table.add_column("Output dir",  style="dim")

    for i, job in enumerate(jobs):
        table.add_row(
            str(i),
            job["mpi"]["name"],
            job["topology"]["name"],
            job["grid"]["name"],
            job.get("compute_mode", {}).get("name", "–"),
            str(len(job.get("cases", []))),
            str(Path(job["output_dir"]).relative_to(ROOT) if ROOT in Path(job["output_dir"]).parents else job["output_dir"]),
        )

    console.print(table)
    console.print(f"\n[bold]Total:[/bold] {len(jobs)} SLURM jobs × "
                  f"{len(jobs[0].get('cases', [])) if jobs else 0} cases each")


# ── gen ───────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, default=False,
              help="Render templates but do not write files.")
@click.option("--output", "-o", default=None, type=click.Path(),
              help="Override output_base directory.")
def gen(config: str, dry_run: bool, output: str | None):
    """Generate SLURM scripts from the experiment config."""
    cfg = load_config(config)
    if output:
        cfg["output_base"] = output

    jobs = expand_matrix(cfg)
    if not jobs:
        console.print("[red]No jobs to generate (all excluded?).[/red]")
        return

    console.print(f"[bold]Generating {len(jobs)} scripts[/bold]"
                  + (" [yellow](dry-run)[/yellow]" if dry_run else "") + "…")

    scripts = generate_all(jobs, dry_run=dry_run)

    # Register in DB
    if not dry_run:
        init_db()
        for job, script in zip(jobs, scripts):
            out = Path(job['output_dir'])
            run_id = f"{cfg['name']}__{out.parts[-4]}_{out.parts[-3]}_{out.parts[-2]}_{out.parts[-1]}"
            register_run(
                run_id=run_id,
                experiment=cfg["name"],
                params={
                    "mpi":      job["mpi"]["name"],
                    "topology": job["topology"]["name"],
                    "grid":     job["grid"]["name"],
                    "compute":  job.get("compute_mode", {}).get("name", ""),
                },
                script_path=str(script),
                output_dir=job["output_dir"],
            )

    table = Table(box=box.SIMPLE)
    table.add_column("Script", style="cyan")
    table.add_column("Status", style="green")
    for script in scripts:
        table.add_row(
            str(script),
            "dry-run" if dry_run else "[green]written[/green]",
        )
    console.print(table)

    if not dry_run:
        first_out = Path(jobs[0]["output_dir"])
        submit_sh = first_out.parent.parent / "submit_all.sh"
        console.print(f"\n[bold]submit_all.sh[/bold] → {submit_sh}")
        console.print("Run [cyan]python mpi_lab.py submit --config ...[/cyan] "
                      "to submit, or call sbatch manually.")


# ── submit ────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--output", "-o", default=None, type=click.Path())
def submit(config: str, dry_run: bool, output: str | None):
    """Generate (if needed) and submit all jobs via sbatch."""
    cfg = load_config(config)
    if output:
        cfg["output_base"] = output

    jobs = expand_matrix(cfg)
    scripts = generate_all(jobs, dry_run=False)

    if dry_run:
        console.print("[yellow]Dry-run: would submit:[/yellow]")
        for s in scripts:
            console.print(f"  sbatch {s}")
        return

    console.print(f"[bold]Submitting {len(scripts)} jobs…[/bold]")
    results = submit_all(scripts)

    table = Table(box=box.SIMPLE)
    table.add_column("Script",  style="cyan")
    table.add_column("Job ID",  style="green")

    for script_str, job_id in results.items():
        error = job_id.startswith("ERROR")
        style = "red" if error else "green"
        table.add_row(Path(script_str).name, f"[{style}]{job_id}[/{style}]")
        if not error:
            # Update DB
            run_id = f"{cfg['name']}_{Path(script_str).parent.name}"
            update_status(run_id, "submitted", slurm_job_id=job_id)

    console.print(table)


# ── status ────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--experiment", "-e", default=None)
def status(experiment: str | None):
    """Show run status from the local database."""
    runs = list_runs(experiment=experiment)
    if not runs:
        console.print("[yellow]No runs recorded yet.[/yellow]")
        return

    table = Table(title="Run status", box=box.ROUNDED)
    table.add_column("Run ID",      style="dim")
    table.add_column("Experiment",  style="cyan")
    table.add_column("MPI",         style="green")
    table.add_column("Job ID",      style="yellow")
    table.add_column("Status",      style="white")
    table.add_column("Submitted",   style="dim")

    STATUS_STYLE = {
        "pending":   "dim",
        "submitted": "yellow",
        "running":   "cyan",
        "done":      "green",
        "failed":    "red",
    }

    import json
    for run in runs:
        params = json.loads(run.get("params", "{}"))
        st = run.get("status", "?")
        style = STATUS_STYLE.get(st, "white")
        table.add_row(
            run["run_id"][:12],
            run["experiment"],
            params.get("mpi", "?"),
            run.get("slurm_job_id") or "–",
            f"[{style}]{st}[/{style}]",
            (run.get("submit_time") or "–")[:16],
        )

    console.print(table)


# ── jobs ──────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--user", "-u", default=None,
              help="SLURM user (default: current user).")
def jobs(user: str | None):
    """Show live SLURM queue status (calls squeue)."""
    user = user or getpass.getuser()
    queue = squeue(user=user)

    if not queue:
        console.print(f"[yellow]No jobs in queue for user '{user}'.[/yellow]")
        return

    table = Table(title=f"SLURM queue for {user}", box=box.ROUNDED)
    table.add_column("Job ID",  style="yellow")
    table.add_column("Name",    style="cyan")
    table.add_column("State",   style="white")
    table.add_column("Time",    style="dim")
    table.add_column("Nodes",   style="green")
    table.add_column("Reason",  style="dim")

    STATE_STYLE = {
        "RUNNING":  "green",
        "PENDING":  "yellow",
        "FAILED":   "red",
        "COMPLETED":"dim",
        "CANCELLED":"red",
    }

    for j in queue:
        st = j["state"]
        style = STATE_STYLE.get(st, "white")
        table.add_row(
            j["job_id"],
            j["name"],
            f"[{style}]{st}[/{style}]",
            j["time"],
            j["nodes"],
            j["reason"],
        )

    console.print(table)


# ── gui ───────────────────────────────────────────────────────────────────────
@cli.command()
@click.option("--web", is_flag=True, default=False,
              help="Use browser-based GUI instead of tkinter window.")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Host for web GUI mode.")
@click.option("--port", default=8765, show_default=True, type=int,
              help="Port for web GUI mode.")
@click.option("--config", default=None, type=click.Path(exists=True),
              help="Optional initial config file for web GUI mode.")
def gui(web: bool, host: str, port: int, config: str | None):
    """Open a local GUI for selecting config axes and generating scripts."""
    if web:
        from viz.web_gui import run as run_web_gui
        run_web_gui(host=host, port=port, config_path=config)
        return

    try:
        from viz.gui import run as run_gui
        run_gui()
        return
    except Exception as exc:
        console.print(f"[yellow]Tk GUI unavailable:[/yellow] {exc}")
        console.print("[yellow]Falling back to web GUI.[/yellow]")

    from viz.web_gui import run as run_web_gui
    run_web_gui(host=host, port=port, config_path=config)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cli()
