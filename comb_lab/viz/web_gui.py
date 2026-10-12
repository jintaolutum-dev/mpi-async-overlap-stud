from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import copy
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qs, quote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile
import json
import re

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from core.generator import generate_all, generate_bundle, generate_job, write_submit_all
from core.matrix import expand_matrix, load_config
from core.run_notes import create_run_notes, remove_orphaned_default_run_note
from core.scheduler import sbatch

CLUSTER_PROFILES = {
    "cm4_std": {
        "clusters": "cm4",
        "partition": "cm4_std",
        "qos": "cm4_std",
        "min_nodes": 2,
    },
    "cm4_inter": {
        "clusters": "inter",
        "partition": "cm4_inter",
        "qos": "normal",
    },
}

RUN_DIR = re.compile(r"^run_(\d+)(?:_(?:MPIonly|Mockonly))?$")
ANALYSIS_RUN_FILE = re.compile(r"^overlap_metrics_((?:run_\d+(?:_(?:MPIonly|Mockonly))?)|(?:average_run_\d+(?:_run_\d+)*))\.(?:csv|png)$")
OUTPUT_SCAN_CACHE_SECONDS = 30.0
_output_scan_cache: dict[Path, tuple[float, list[dict]]] = {}
_output_scan_lock = threading.Lock()


def _parse_positive_triplet(value: str, label: str) -> tuple[int, int, int]:
    parts = value.strip().replace("x", "_").replace(",", "_").split("_")
    if len(parts) != 3:
        raise ValueError(f"{label} must contain exactly three dimensions")
    try:
        dimensions = tuple(int(part.strip()) for part in parts)
    except ValueError as exc:
        raise ValueError(f"{label} must contain integers only") from exc
    if any(dimension <= 0 for dimension in dimensions):
        raise ValueError(f"{label} dimensions must be positive")
    return dimensions


def _next_run_number(jobs: list[dict]) -> int:
    existing_ids: list[int] = []
    for job in jobs:
        output_dir = Path(job["output_dir"])
        if not output_dir.exists():
            continue
        for child in output_dir.iterdir():
            if not child.is_dir():
                continue
            match = RUN_DIR.match(child.name)
            if match and any(child.iterdir()):
                existing_ids.append(int(match.group(1)))

    return max(existing_ids, default=0) + 1


def _apply_run_dir(jobs: list[dict], run_number: int, backend_mode: str) -> str:
    suffix = {"both": "", "mpi_only": "_MPIonly", "mock_only": "_Mockonly"}[backend_mode]
    run_dir = f"run_{run_number:03d}{suffix}"
    for job in jobs:
        job["output_dir"] = str(Path(job["output_dir"]) / run_dir)
    return run_dir


def _configs():
    cfg_dir = ROOT / "config"
    out = []
    if cfg_dir.exists():
        out += sorted(cfg_dir.glob("*.yaml"))
        out += sorted(cfg_dir.glob("*.yml"))
    return out


def _safe_script_path(abs_path: str) -> Path | None:
    candidate = Path(abs_path).resolve()
    base = (ROOT / "generated").resolve()
    try:
        candidate.relative_to(base)
    except Exception:
        return None
    if not candidate.exists():
        return None
    return candidate


def _safe_generated_dir_path(abs_path: str) -> Path | None:
    candidate = Path(abs_path).resolve()
    base = (ROOT / "generated").resolve()
    try:
        candidate.relative_to(base)
    except Exception:
        return None
    if not candidate.exists() or not candidate.is_dir():
        return None
    return candidate


def _safe_analysis_dir(abs_path: str) -> Path | None:
    candidate = _safe_generated_dir_path(abs_path)
    if candidate is None or "analysis" not in candidate.parts:
        return None
    if not (candidate / "overlap_metrics.png").is_file():
        return None
    return candidate


def _clear_output_dir(output_dir: Path) -> bool:
    """Remove result artifacts while preserving a colocated generated run script."""
    preserved_script = output_dir / "run.sh"
    for child in output_dir.iterdir():
        if child == preserved_script:
            continue
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    if not preserved_script.exists():
        output_dir.rmdir()
        return True
    return False


def _clear_analysis_run(analysis_dir: Path, run: str) -> list[Path]:
    if not (run == "run" or RUN_DIR.match(run) or re.fullmatch(r"average_run_\d+(?:_run_\d+)*", run)):
        raise ValueError(f"Invalid analysis label: {run}")

    removed: list[Path] = []
    chart_stem = "overlap_metrics" if run == "run" else f"overlap_metrics_{run}"
    for suffix in (".png", ".csv"):
        path = analysis_dir / f"{chart_stem}{suffix}"
        if path.is_file():
            path.unlink()
            removed.append(path)
    note_dir = analysis_dir / "notes" / run
    if note_dir.is_dir():
        shutil.rmtree(note_dir)
        removed.append(note_dir)
    return removed


def _analysis_chart_files(analysis_dir: Path) -> list[Path]:
    """Return overlap charts newest first, including timestamped results."""
    charts = [path for path in analysis_dir.glob("overlap_metrics*.png") if path.is_file()]
    return sorted(charts, key=lambda path: path.stat().st_mtime, reverse=True)


def _safe_chart_file(abs_path: str) -> Path | None:
    candidate = Path(abs_path).resolve()
    base = (ROOT / "generated").resolve()
    try:
        candidate.relative_to(base)
    except Exception:
        return None
    if "analysis" not in candidate.parts or not candidate.is_file() or not candidate.name.startswith("overlap_metrics"):
        return None
    if candidate.suffix != ".png":
        return None
    return candidate


def _chart_download_name(image_path: Path) -> str:
    """Name a chart download with its generated-run configuration."""
    meta = _output_meta(image_path.parent)
    run_match = ANALYSIS_RUN_FILE.match(image_path.name)
    run = run_match.group(1) if run_match else ""
    fields = (
        meta["cluster"],
        meta["mpi"],
        meta["topology"],
        meta["grid"],
        meta["compute"],
        run,
    )
    return "_".join(field for field in fields if field and field != "-") + image_path.suffix


def _resolve_vscode_ipc_hook() -> str | None:
    parents: list[Path] = []
    direct_hook: Path | None = None

    for env_name in ("VSCODE_IPC_HOOK_CLI", "VSCODE_GIT_IPC_HANDLE"):
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue

        path = Path(raw).expanduser()
        if env_name == "VSCODE_IPC_HOOK_CLI":
            direct_hook = path

        parent = path.parent
        if parent.exists() and parent not in parents:
            parents.append(parent)

    socket_candidates: list[Path] = []
    for parent in parents:
        for candidate in parent.glob("vscode-ipc-*.sock"):
            if candidate.exists():
                socket_candidates.append(candidate)

    if socket_candidates:
        socket_candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return str(socket_candidates[0])

    if direct_hook and direct_hook.exists():
        return str(direct_hook)

    return None


def _open_in_code(path: Path) -> None:
    env = os.environ.copy()
    hook = _resolve_vscode_ipc_hook()
    if hook:
        env["VSCODE_IPC_HOOK_CLI"] = hook
    else:
        env.pop("VSCODE_IPC_HOOK_CLI", None)

    command = ["code", str(path)]
    if path.is_file():
        command.insert(1, "--reuse-window")

    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"code exited with status {result.returncode}")


def _scan_scripts(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    scripts = []
    for path in base_dir.rglob("run.sh"):
        if not path.is_file():
            continue
        try:
            parts = path.relative_to(base_dir).parts
        except ValueError:
            parts = ()
        if len(parts) > 4 and parts[0] == "cm4_std":
            bundle = base_dir.joinpath(*parts[:3], "run.sh")
            if bundle.is_file():
                continue
        scripts.append(path)
    scripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return scripts


def _bundle_child_scripts(bundle_path: Path) -> list[Path]:
    """Return existing child scripts referenced by a generated std bundle."""
    if _cluster_for_script(bundle_path) != "cm4_std":
        return []

    try:
        lines = bundle_path.read_text(errors="ignore").splitlines()
    except OSError:
        return []

    children: list[Path] = []
    in_child_array = False
    for line in lines:
        stripped = line.strip()
        if stripped == "CHILD_SCRIPTS=(":
            in_child_array = True
            continue
        if in_child_array and stripped == ")":
            break
        if not in_child_array:
            continue
        match = re.fullmatch(r'["\'](.+?)["\']', stripped)
        if not match:
            continue
        child = _safe_script_path(str((bundle_path.parent / match.group(1)).resolve()))
        if child is not None and child != bundle_path:
            children.append(child)
    return children


def _bundle_detail_html(bundle_path: Path) -> str:
    rows = []
    for child in _bundle_child_scripts(bundle_path):
        meta = _script_meta(child)
        rows.append(
            f"<tr class='bundle-child-row' data-kind='child'"
            f" data-cluster='{escape(meta['cluster'], quote=True)}'"
            f" data-mpi='{escape(meta['mpi'], quote=True)}'"
            f" data-topology='{escape(meta['topology'], quote=True)}'"
            f" data-size='{escape(meta['size'], quote=True)}'"
            f" data-compute='{escape(meta['compute'], quote=True)}'"
            f" data-run='{escape(meta['run'], quote=True)}'"
            f" data-rel='{escape(meta['rel'], quote=True)}'>"
            f'<td><input type="checkbox" name="script" value="{escape(meta["abs"], quote=True)}"></td>'
            f"<td>{escape(meta['size'])}</td>"
            f"<td>{escape(meta['compute'])}</td>"
            f"<td>{escape(meta['run'])}</td>"
            f"<td class='col-result-dir'>{escape(meta['rel'])}</td>"
            f"<td style='white-space:nowrap'><button type='button' class='open-btn' "
            f"onclick=\"openInCode('{escape(meta['abs'], quote=True)}')\" title='Open child script'>&#128065;</button>&nbsp;"
            f"<button type='button' class='copy-btn' onclick=\"copyPath('{escape(meta['abs'], quote=True)}')\" "
            "title='Copy child script path'>&#128203;</button></td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='6'><em>No child scripts found</em></td></tr>"


def _is_output_file(path: Path) -> bool:
    name = path.name
    if name in {"run.sh", "submit_all.sh", "comb"}:
        return False
    if name.startswith("openmpi_hosts."):
        return False
    if "analysis" in path.parts and name.startswith("overlap_metrics") and path.suffix == ".png":
        return True
    if path.suffix in {".log", ".out", ".csv"}:
        return True
    if name.startswith("Comb_"):
        return True
    if "alloc_logs" in path.parts and path.is_file():
        return True
    return False


def _scan_outputs(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    outputs = [p for p in base_dir.rglob("*") if p.is_file() and _is_output_file(p)]
    outputs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return outputs


def _scan_output_dirs(base_dir: Path) -> list[dict]:
    if not base_dir.exists():
        return []

    cache_key = base_dir.resolve()
    now = time.monotonic()
    cached = _output_scan_cache.get(cache_key)
    if cached and now - cached[0] < OUTPUT_SCAN_CACHE_SECONDS:
        return cached[1]

    with _output_scan_lock:
        now = time.monotonic()
        cached = _output_scan_cache.get(cache_key)
        if cached and now - cached[0] < OUTPUT_SCAN_CACHE_SECONDS:
            return cached[1]

        rows = _scan_output_dirs_uncached(base_dir)
        _output_scan_cache[cache_key] = (time.monotonic(), rows)
        return rows


def _scan_output_dirs_uncached(base_dir: Path) -> list[dict]:
    grouped: dict[tuple[Path, str | None], dict] = {}
    for root, dirs, files in os.walk(base_dir):
        if "alloc_logs" in Path(root).parts:
            dirs[:] = []
            continue

        parent = Path(root)
        try:
            directory_mtime = parent.stat().st_mtime
        except OSError:
            directory_mtime = 0.0

        for name in files:
            path = parent / name
            if not _is_output_file(path):
                continue
            run_match = ANALYSIS_RUN_FILE.match(name) if parent.name == "analysis" else None
            run = run_match.group(1) if run_match else None
            entry = grouped.setdefault(
                (parent, run),
                {"dir": parent, "run": run, "count": 0, "latest_mtime": directory_mtime, "files": []},
            )
            entry["count"] += 1
            entry["files"].append(path)

    rows = list(grouped.values())
    for item in rows:
        item["files"].sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows.sort(key=lambda item: item["latest_mtime"], reverse=True)
    return rows


def _output_detail_html(output_dir: Path, run: str = "") -> str:
    files = [path for path in output_dir.iterdir() if path.is_file() and _is_output_file(path)]
    if output_dir.name == "analysis" and run:
        files = [
            path for path in files
            if (match := ANALYSIS_RUN_FILE.match(path.name)) and match.group(1) == run
        ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    rows = []
    for path in files:
        chart_button = (
            f'<button type="button" class="open-btn" onclick="openChart(\'{escape(str(path))}\')" '
            f'title="Open {escape(path.name)}">chart</button>&nbsp;'
            if output_dir.name == "analysis" and path.suffix == ".png" else ""
        )
        rows.append(
            "<tr>"
            f"<td style='padding-left:18px'>{escape(path.name)}</td>"
            f"<td style='white-space:nowrap'>{chart_button}<button type='button' class='open-btn' "
            f"onclick=\"openInCode('{escape(str(path))}')\" title='Open output file'>&#128065;</button>&nbsp;"
            f"<button type='button' class='copy-btn' onclick=\"copyPath('{escape(str(path))}')\" "
            "title='Copy output file path'>📋</button></td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='2'><em>No files</em></td></tr>"


def _cluster_for_script(path: Path) -> str:
    parts = set(path.parts)
    if "cm4_inter" in parts:
        return "cm4_inter"
    if "cm4_std" in parts:
        return "cm4_std"

    # Backward compatibility: older generated paths may not include cluster
    # segment. Infer it from SBATCH header fields in the script body.
    try:
        header = path.read_text(errors="ignore")[:4000]
    except Exception:
        return "unknown"

    if "--partition=cm4_inter" in header or "--qos=cm4_inter" in header:
        return "cm4_inter"
    if "--partition=cm4_std" in header or "--qos=cm4_std" in header:
        return "cm4_std"

    # Some templates use cluster keyword (`cm4` / `inter`) explicitly.
    if "--clusters=inter" in header:
        return "cm4_inter"
    if "--clusters=cm4" in header:
        return "cm4_std"

    return "unknown"


def _message_size_label(script_path: Path | None, fallback: str) -> str:
    if fallback.startswith("msg_"):
        payloads = dict(re.findall(r"(?:^|_)([xyz])([^_]+)", fallback[4:]))
        if all(axis in payloads for axis in "xyz"):
            return f"X {payloads['x']}, Y/Z {payloads['y']}/{payloads['z']}"

    if script_path is None or not script_path.is_file():
        return fallback

    try:
        settings = {}
        for line in script_path.read_text(errors="ignore").splitlines():
            for key in ("GRID_SIZE", "DIVIDE", "GHOST", "VARS"):
                prefix = f"{key}="
                if line.startswith(prefix):
                    settings[key] = line[len(prefix):].strip().strip('"')
    except OSError:
        return fallback

    try:
        grid = tuple(int(value) for value in settings["GRID_SIZE"].split("_"))
        divide = tuple(int(value) for value in settings["DIVIDE"].split("_"))
        ghost = tuple(int(value) for value in settings["GHOST"].split("_"))
        variables = int(settings["VARS"])
        if len(grid) != 3 or len(divide) != 3 or len(ghost) != 3:
            return fallback
    except (KeyError, ValueError):
        return fallback

    local = tuple(size // parts for size, parts in zip(grid, divide))
    face_bytes = (
        local[1] * local[2] * ghost[0] * 8 * variables,
        local[0] * local[2] * ghost[1] * 8 * variables,
        local[0] * local[1] * ghost[2] * 8 * variables,
    )

    def format_bytes(value: int) -> str:
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.2f} MiB"
        if value >= 1024:
            return f"{value / 1024:.0f} KiB"
        return f"{value} B"

    return f"X {format_bytes(face_bytes[0])}, Y/Z {format_bytes(face_bytes[1])}/{format_bytes(face_bytes[2])}"


def _message_size_dirname(script_path: Path | None, fallback: str) -> str:
    if script_path is None or not script_path.is_file():
        return fallback

    try:
        settings = {}
        for line in script_path.read_text(errors="ignore").splitlines():
            for key in ("GRID_SIZE", "DIVIDE", "GHOST", "VARS"):
                prefix = f"{key}="
                if line.startswith(prefix):
                    settings[key] = line[len(prefix):].strip().strip('"')
        grid = tuple(int(value) for value in settings["GRID_SIZE"].split("_"))
        divide = tuple(int(value) for value in settings["DIVIDE"].split("_"))
        ghost = tuple(int(value) for value in settings["GHOST"].split("_"))
        variables = int(settings["VARS"])
        if len(grid) != 3 or len(divide) != 3 or len(ghost) != 3:
            return fallback
    except (OSError, KeyError, ValueError):
        return fallback

    local = tuple(size // parts for size, parts in zip(grid, divide))
    face_bytes = (
        local[1] * local[2] * ghost[0] * 8 * variables,
        local[0] * local[2] * ghost[1] * 8 * variables,
        local[0] * local[1] * ghost[2] * 8 * variables,
    )

    def format_bytes(value: int) -> str:
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.2f}MiB"
        if value >= 1024:
            return f"{value // 1024}KiB"
        return f"{value}B"

    return "msg_" + "_".join(
        f"{axis}{format_bytes(value)}" for axis, value in zip("xyz", face_bytes)
    )


def _payload_label_sort_key(label: str) -> tuple[float, str]:
    match = re.match(r"^X\s+([0-9]+(?:\.[0-9]+)?)\s+(B|KiB|MiB)", label)
    if not match:
        return float("inf"), label
    scale = {"B": 1, "KiB": 1024, "MiB": 1024 * 1024}
    return float(match.group(1)) * scale[match.group(2)], label


def _script_payload_bytes(path: Path) -> float:
    """Return the exact largest halo-face payload represented by a script."""
    try:
        settings = {}
        for line in path.read_text(errors="ignore").splitlines():
            for key in ("GRID_SIZE", "DIVIDE", "GHOST", "VARS"):
                prefix = f"{key}="
                if line.startswith(prefix):
                    settings[key] = line[len(prefix):].strip().strip('"')
        grid = tuple(int(value) for value in settings["GRID_SIZE"].split("_"))
        divide = tuple(int(value) for value in settings["DIVIDE"].split("_"))
        ghost = tuple(int(value) for value in settings["GHOST"].split("_"))
        variables = int(settings["VARS"])
        if len(grid) != 3 or len(divide) != 3 or len(ghost) != 3:
            raise ValueError
    except (OSError, KeyError, ValueError):
        return float("inf")

    local = tuple(size // parts for size, parts in zip(grid, divide))
    face_bytes = (
        local[1] * local[2] * ghost[0] * 8 * variables,
        local[0] * local[2] * ghost[1] * 8 * variables,
        local[0] * local[1] * ghost[2] * 8 * variables,
    )
    return float(max(face_bytes))


def _analysis_dir_for_run(experiment_dir: Path, run_dir: Path) -> Path:
    """Keep legacy result inputs, but write new charts under payload-based paths."""
    if experiment_dir.name.startswith("msg_"):
        return experiment_dir / "analysis"
    message_dirname = _message_size_dirname(run_dir / "run.sh", experiment_dir.name)
    return experiment_dir.parent / message_dirname / "analysis"


def _script_meta(path: Path) -> dict:
    rel = path.relative_to(ROOT)
    cluster = _cluster_for_script(path)
    mpi = "-"
    topology = "-"
    grid = "-"
    compute = "-"
    run = "-"

    # Supported shapes:
    # generated/<cluster>/<mpi>/<topology>/<grid>[/<compute>]/run.sh
    # generated/<cluster>/<mpi>/<topology>/<grid>[/<compute>]/run_###/run.sh
    # generated/<mpi>/<topology>/<grid>[/<compute>]/run.sh
    try:
        sub = path.relative_to(ROOT / "generated")
        parts = list(sub.parts)
        if parts and parts[-1] == "run.sh":
            parts = parts[:-1]
        if parts:
            match = RUN_DIR.match(parts[-1])
            if match:
                run = parts[-1]
                parts = parts[:-1]

        if parts and parts[0] in CLUSTER_PROFILES:
            offset = 1
        else:
            offset = 0

        if len(parts) >= offset + 1:
            mpi = parts[offset]
        if len(parts) >= offset + 2:
            topology = parts[offset + 1]
        if len(parts) >= offset + 3:
            grid = parts[offset + 2]
        if len(parts) >= offset + 4:
            compute = parts[offset + 3]
    except Exception:
        pass

    is_bundle = cluster == "cm4_std" and len(parts) == offset + 2
    if is_bundle:
        grid = "bundle"
        compute = "bundle"
        size_label = "All payloads"
    else:
        size_label = _message_size_label(path, grid)

    return {
        "abs": str(path),
        "rel": str(rel),
        "cluster": cluster,
        "mpi": mpi,
        "topology": topology,
        "grid": grid,
        "size": size_label,
        "compute": compute,
        "run": run,
    }


def _output_meta(path: Path) -> dict:
    rel = path.relative_to(ROOT)
    cluster = "-"
    mpi = "-"
    topology = "-"
    grid = "-"
    compute = "-"

    try:
        sub = path.relative_to(ROOT / "generated")
        parts = list(sub.parts)
        if parts and parts[0] == "alloc_logs":
            cluster = "alloc_logs"
        else:
            if parts and parts[0] in CLUSTER_PROFILES:
                offset = 1
                cluster = parts[0]
            else:
                offset = 0

            if len(parts) >= offset + 1:
                mpi = parts[offset]
            if len(parts) >= offset + 2:
                topology = parts[offset + 1]
            if len(parts) >= offset + 3:
                grid = parts[offset + 2]
            if len(parts) >= offset + 4:
                compute = parts[offset + 3]
    except Exception:
        pass

    script_path = path / "run.sh"
    if compute == "analysis":
        midcomm_dir = path.parent / "midcomm"
        run_scripts = sorted(midcomm_dir.glob("run_*/run.sh"))
        if run_scripts:
            script_path = run_scripts[0]
        elif (midcomm_dir / "run.sh").is_file():
            script_path = midcomm_dir / "run.sh"
    size_label = _message_size_label(script_path, grid)

    return {
        "abs": str(path),
        "rel": str(rel),
        "cluster": cluster,
        "mpi": mpi,
        "topology": topology,
        "grid": grid,
        "size": size_label,
        "compute": compute,
        "name": path.name,
    }


def _output_sort_key(item: dict, meta: dict, grid_order: dict[str, int], mpi_order: dict[str, int]) -> tuple:
    run = item.get("run") or (item["dir"].name if RUN_DIR.match(item["dir"].name) else "")
    run_match = RUN_DIR.match(run)
    run_number = int(run_match.group(1)) if run_match else -1
    compute_order = {"analysis": 0, "midcomm": 1, "no_midcomm": 2}
    return (
        meta["cluster"],
        mpi_order.get(meta["mpi"], 99),
        meta["mpi"],
        meta["topology"],
        grid_order.get(meta["grid"], 99),
        meta["grid"],
        run_number,
        compute_order.get(meta["compute"], 3),
        run,
    )


def _script_sort_key(path: Path, mpi_order: dict[str, int]) -> tuple:
    meta = _script_meta(path)
    run_match = RUN_DIR.match(meta["run"])
    run_number = int(run_match.group(1)) if run_match else -1
    compute_order = {"midcomm": 0, "no_midcomm": 1}
    return (
        meta["cluster"],
        mpi_order.get(meta["mpi"], 99),
        meta["mpi"],
        meta["topology"],
        _script_payload_bytes(path),
        meta["size"],
        run_number,
        compute_order.get(meta["compute"], 2),
        meta["run"],
    )


def _render(cfg_path, cfg, msg="", items=None, selected_clusters=None, form_state=None):
    items = items or []
    selected_clusters = selected_clusters or []
    form_state = form_state or {}
    candidates = _configs()
    scripts = _scan_scripts(ROOT / "generated")[:300]
    output_dirs = _scan_output_dirs(ROOT / "generated")
    output_dir_count = len(output_dirs)
    limited_output_dirs = []
    output_counts_by_cluster: dict[str, int] = {}
    for item in output_dirs:
        parts = item["dir"].parts
        cluster = next((name for name in CLUSTER_PROFILES if name in parts), "legacy")
        if output_counts_by_cluster.get(cluster, 0) >= 300:
            continue
        limited_output_dirs.append(item)
        output_counts_by_cluster[cluster] = output_counts_by_cluster.get(cluster, 0) + 1
    output_dirs = limited_output_dirs
    grid_order = {"small_msg": 0, "small": 0, "medium": 1, "large": 2, "big": 3}
    mpi_order = {"openmpi": 0, "intelmpi": 1, "intelmpi_tcp": 2, "mpich": 3}
    scripts.sort(key=lambda path: _script_sort_key(path, mpi_order))
    output_meta = {item["dir"]: _output_meta(item["dir"]) for item in output_dirs}
    output_dirs.sort(key=lambda item: _output_sort_key(item, output_meta[item["dir"]], grid_order, mpi_order))
    output_dir_set = {item["dir"].resolve() for item in output_dirs}

    def ck(name):
        parts = []
        selected_values = set(form_state.get(name, selected_clusters if name == "cluster" else []))
        for x in name_map[name]:
            checked = "checked" if x in selected_values else ""
            parts.append(
                f'<label><input type="checkbox" name="{name}" value="{escape(x)}" {checked}> {escape(x)}</label><br>'
            )
        return "\n".join(parts) or "<em>None</em>"

    name_map = {
        "cluster": list(CLUSTER_PROFILES.keys()),
        "mpi": list(cfg.get("mpi_impl", {}).keys()),
        "topology": [x.get("name", "") for x in cfg.get("topology", []) if x.get("name")],
        "grid": list(cfg.get("grid", {}).keys()),
    }

    # Sort grid options from small to large by computed max-face message size
    def _grid_sort_key(grid_key):
        gcfg = cfg.get("grid", {}).get(grid_key, {})
        ref_topo = cfg.get("topology", [{}])[0] if cfg.get("topology") else {}
        try:
            divide = [int(x) for x in str(ref_topo.get("divide", "1_1_1")).split("_")]
            size = [int(x) for x in str(gcfg.get("size", "1_1_1")).split("_")]
            ghost = [int(x) for x in str(gcfg.get("ghost", "1_1_1")).split("_")]
            vars_ = int(gcfg.get("vars", 1))
            local = [size[i] // max(divide[i], 1) for i in range(3)]
            faces = [local[1]*local[2]*ghost[0], local[0]*local[2]*ghost[1], local[0]*local[1]*ghost[2]]
            return max(faces) * 8 * vars_
        except Exception:
            return 0

    sorted_grids = sorted(name_map["grid"], key=_grid_sort_key)

    _grid_json: dict = {}
    for _gk in sorted_grids:
        _gcfg = cfg.get("grid", {}).get(_gk, {})
        try:
            _grid_json[_gk] = {
                "label": str(_gcfg.get("label", _gk)),
                "size": [int(x) for x in str(_gcfg.get("size", "1_1_1")).split("_")],
                "ghost": [int(x) for x in str(_gcfg.get("ghost", "1_1_1")).split("_")],
                "vars": int(_gcfg.get("vars", 1)),
            }
        except Exception:
            pass

    _topo_json: dict = {}
    for _t in cfg.get("topology", []):
        _tname = _t.get("name", "")
        if not _tname:
            continue
        try:
            _topo_json[_tname] = {
                "divide": [int(x) for x in str(_t.get("divide", "1_1_1")).split("_")],
                "nodes": int(_t.get("nodes", 1)),
                "ntasks_per_node": int(_t.get("ntasks_per_node", 1)),
                "cpus_per_task": int(_t.get("cpus_per_task", 1)),
            }
            _topo_json[_tname]["ntasks"] = _topo_json[_tname]["nodes"] * _topo_json[_tname]["ntasks_per_node"]
        except Exception:
            pass

    grid_json = json.dumps(_grid_json)
    topo_json = json.dumps(_topo_json)

    case_rows = []
    for idx, case in enumerate(cfg.get("cases", [])):
        omp_threads = int(case.get("omp_threads", 1))
        wait_mode = str(case.get("wait_mode", "wait_all"))
        if int(case.get("async", 0)) == 1:
            async_threads = int(case.get("async_threads", cfg.get("mpi_impl", {}).get("intelmpi", {}).get("async_threads", 1)))
            profile = f"{omp_threads}+{async_threads}"
            mode = "async"
        else:
            profile = str(omp_threads)
            mode = "no_async"
        case_rows.append(
            f"<div style='padding:4px 0;border-bottom:1px dashed #e2e7f3'>"
            f"<strong>{idx:02d}</strong> "
            f"<span style='display:inline-block;min-width:48px'>{mode}</span> "
            f"<span style='display:inline-block;min-width:72px'>{escape(profile)}</span> "
            f"<span style='color:#555'>{escape(wait_mode)}</span>"
            f"</div>"
        )
    case_box_html = "".join(case_rows) or "<em>None</em>"

    def ck_grid():
        parts = []
        selected_grids = set(form_state.get("grid", []))
        for gkey in sorted_grids:
            grid_cfg = cfg.get("grid", {}).get(gkey, {})
            grid_size = str(grid_cfg.get("size", "?"))
            ghost = str(grid_cfg.get("ghost", "?"))
            variables = str(grid_cfg.get("vars", "?"))
            parts.append(
                f'<label>'
                f'<input type="checkbox" name="grid" value="{escape(gkey)}" {"checked" if gkey in selected_grids else ""}> '
                f' <span id="gsize_{escape(gkey)}" style="color:#555;font-size:11px"></span> '
                f'<span style="color:#555;font-size:11px">'
                f'(grid={escape(grid_size)}, ghost={escape(ghost)}, vars={escape(variables)})</span>'
                f'</label><br>'
            )
        return "\n".join(parts) or "<em>None</em>"

    msgsize_js = f"""const GRID_DATA = {grid_json};
const TOPO_DATA = {topo_json};
const SALLOC_DEFAULT_TIME = "00:30:00";

function fmtBytes(n) {{
    if (n >= 1048576) return (n / 1048576).toFixed(2) + ' MiB';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KiB';
    return n + ' B';
}}

function updateMsgSizeLabels() {{
    const checked = Array.from(document.querySelectorAll('input[name="topology"]:checked')).map(e => e.value);
    const key = checked.length ? checked[0] : Object.keys(TOPO_DATA)[0];
    const t = TOPO_DATA[key];
    if (!t) return;
    for (const [gk, g] of Object.entries(GRID_DATA)) {{
        const el = document.getElementById('gsize_' + gk);
        if (!el) continue;
        const loc = g.size.map((s, i) => Math.floor(s / t.divide[i]));
        const faceBytes = {{
            X: loc[1] * loc[2] * g.ghost[0] * 8 * g.vars,
            Y: loc[0] * loc[2] * g.ghost[1] * 8 * g.vars,
            Z: loc[0] * loc[1] * g.ghost[2] * 8 * g.vars,
        }};
        el.textContent = 'X ' + fmtBytes(faceBytes.X) + ', Y/Z ' + fmtBytes(faceBytes.Y) + '/' + fmtBytes(faceBytes.Z) + ' ';
    }}
}}

function parseCustomTriplet(id) {{
    const value = document.getElementById(id)?.value.trim().replaceAll('x', '_').replaceAll(',', '_');
    const parts = (value || '').split('_').map(Number);
    return parts.length === 3 && parts.every(n => Number.isInteger(n) && n > 0) ? parts : null;
}}

function updateCustomPayloadEstimate() {{
    const output = document.getElementById('custom_payload_estimate');
    if (!output) return;
    const size = parseCustomTriplet('custom_grid_size');
    const ghost = parseCustomTriplet('custom_ghost');
    const vars = Number(document.getElementById('custom_vars')?.value || 0);
    const topologyKey = getSelectedTopologyKeys()[0];
    const divide = TOPO_DATA[topologyKey]?.divide;
    if (!size || !divide || !ghost || !Number.isInteger(vars) || vars <= 0) {{
        output.textContent = 'Enter positive X_Y_Z integers.';
        return;
    }}
    if (size.some((dimension, index) => dimension % divide[index] !== 0)) {{
        output.textContent = 'Grid dimensions must be divisible by divide.';
        return;
    }}
    const loc = size.map((dimension, index) => dimension / divide[index]);
    const faceBytes = [
        loc[1] * loc[2] * ghost[0] * 8 * vars,
        loc[0] * loc[2] * ghost[1] * 8 * vars,
        loc[0] * loc[1] * ghost[2] * 8 * vars,
    ];
    output.textContent = topologyKey + ' divide ' + divide.join('x') + ' | Local ' + loc.join('x') + ' | X ' + fmtBytes(faceBytes[0]) +
        ', Y ' + fmtBytes(faceBytes[1]) + ', Z ' + fmtBytes(faceBytes[2]);
}}

function updateSallocTaskCount() {{
    const nodes = parseInt(document.getElementById('salloc_nodes')?.value || '0', 10);
    const ntpn = parseInt(document.getElementById('salloc_ntasks_per_node')?.value || '0', 10);
    const ntasksEl = document.getElementById('salloc_ntasks');
    if (!ntasksEl || !Number.isFinite(nodes) || !Number.isFinite(ntpn)) return;
    ntasksEl.value = String(Math.max(nodes, 0) * Math.max(ntpn, 0));
}}

function getSelectedTopologyKeys() {{
    const checked = Array.from(document.querySelectorAll('input[name="topology"]:checked')).map(e => e.value);
    return checked.length ? checked : Object.keys(TOPO_DATA);
}}

function updateGenerationMode(changedCluster) {{
    const clusterInputs = Array.from(document.querySelectorAll('input[name="cluster"]'));
    if (changedCluster?.checked) {{
        clusterInputs.forEach(input => {{
            if (input !== changedCluster) input.checked = false;
        }});
    }}
    const stdMode = clusterInputs.some(input => input.value === 'cm4_std' && input.checked);
    document.querySelectorAll('[data-std-disabled] input, [data-std-disabled] select').forEach(input => {{
        input.disabled = stdMode;
    }});
    document.querySelectorAll('[data-std-disabled]').forEach(container => {{
        container.classList.toggle('std-disabled', stdMode);
    }});
    document.querySelectorAll('input[name="topology"]').forEach(input => {{
        const invalidForStd = stdMode && Number(TOPO_DATA[input.value]?.nodes || 0) < 2;
        input.disabled = invalidForStd;
        if (invalidForStd) input.checked = false;
    }});
    const generateButton = document.querySelector('button[name="action"][value="generate"]');
    if (generateButton) generateButton.textContent = stdMode ? 'Generate std bundles' : 'Generate scripts';
}}

function refreshSallocTopologyChoices() {{
    const selectEl = document.getElementById('salloc_topology');
    if (!selectEl) return;
    const options = getSelectedTopologyKeys();
    const current = selectEl.value;
    selectEl.innerHTML = '';
    for (const key of options) {{
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = key;
        if (key === current) opt.selected = true;
        selectEl.appendChild(opt);
    }}
    if (!options.includes(current) && options.length) {{
        selectEl.value = options[0];
    }}
}}

function updateSallocDefaults() {{
    const selectEl = document.getElementById('salloc_topology');
    const key = selectEl?.value || getSelectedTopologyKeys()[0];
    const t = TOPO_DATA[key];
    if (!t) return;
    const nodesEl = document.getElementById('salloc_nodes');
    const ntpnEl = document.getElementById('salloc_ntasks_per_node');
    const cptEl = document.getElementById('salloc_cpus_per_task');
    const timeEl = document.getElementById('salloc_time');
    if (nodesEl) nodesEl.value = String(t.nodes || 1);
    if (ntpnEl) ntpnEl.value = String(t.ntasks_per_node || 1);
    if (cptEl) cptEl.value = String(t.cpus_per_task || 1);
    if (timeEl && !timeEl.value) timeEl.value = SALLOC_DEFAULT_TIME;
    updateSallocTaskCount();
}}

document.querySelectorAll('input[name="topology"]').forEach(cb => {{
    cb.addEventListener('change', updateMsgSizeLabels);
    cb.addEventListener('change', updateCustomPayloadEstimate);
    cb.addEventListener('change', () => {{
        refreshSallocTopologyChoices();
        updateSallocDefaults();
    }});
}});
document.querySelectorAll('input[name="cluster"]').forEach(cb => {{
    cb.addEventListener('change', () => updateGenerationMode(cb));
}});
document.getElementById('salloc_topology')?.addEventListener('change', updateSallocDefaults);
document.getElementById('salloc_nodes')?.addEventListener('input', updateSallocTaskCount);
document.getElementById('salloc_ntasks_per_node')?.addEventListener('input', updateSallocTaskCount);
['custom_grid_size', 'custom_ghost', 'custom_vars', 'custom_compute_target_us'].forEach(id => {{
    document.getElementById(id)?.addEventListener('input', () => {{
        const checkbox = document.getElementById('use_custom_payload');
        if (checkbox) checkbox.checked = true;
        updateCustomPayloadEstimate();
    }});
}});
updateMsgSizeLabels();
updateCustomPayloadEstimate();
updateGenerationMode();
refreshSallocTopologyChoices();
updateSallocDefaults();"""

    opts = []
    for p in candidates:
        sel = "selected" if p == cfg_path else ""
        opts.append(f'<option value="{escape(str(p))}" {sel}>{escape(str(p))}</option>')

    lis = "\n".join(f"<li>{escape(x)}</li>" for x in items)
    dry_run_checked = "checked" if form_state.get("dry_run") else ""
    custom_checked = "checked" if form_state.get("use_custom_payload") else ""
    output_override_value = escape(str(form_state.get("output", "")), quote=True)
    cycles_value = escape(str(form_state.get("cycles_override", "")), quote=True)
    run_count_value = escape(str(form_state.get("run_count", "3")), quote=True)
    custom_grid_size = escape(str(form_state.get("custom_grid_size", "32_32_32")), quote=True)
    custom_ghost = escape(str(form_state.get("custom_ghost", "1_1_1")), quote=True)
    custom_vars = escape(str(form_state.get("custom_vars", "1")), quote=True)
    custom_compute_target = escape(str(form_state.get("custom_compute_target_us", "20")), quote=True)
    backend_modes = set(form_state.get("backend_mode", ["mpi_only", "mock_only"]))
    backend_mode_checked = {
        mode: "checked" if mode in backend_modes else ""
        for mode in ("both", "mpi_only", "mock_only")
    }

    filter_script_paths = list(scripts)
    for script in scripts:
        meta = _script_meta(script)
        if meta["cluster"] == "cm4_std" and meta["grid"] == "bundle":
            filter_script_paths.extend(_bundle_child_scripts(script))
    filter_script_meta = [_script_meta(path) for path in filter_script_paths]
    script_filters = {
        "cluster": sorted({meta["cluster"] for meta in filter_script_meta}),
        "mpi": sorted({meta["mpi"] for meta in filter_script_meta}),
        "topology": sorted({meta["topology"] for meta in filter_script_meta}),
        "size": sorted({meta["size"] for meta in filter_script_meta}, key=_payload_label_sort_key),
        "compute": sorted({meta["compute"] for meta in filter_script_meta}),
        "run": sorted({meta["run"] for meta in filter_script_meta}, reverse=True),
    }

    def opt_list(values):
        return "".join([f'<option value="{escape(v)}">{escape(v)}</option>' for v in values if v])

    output_filter_rows = [
        {
            **output_meta[item["dir"]],
            "run": item.get("run") or (item["dir"].name if RUN_DIR.match(item["dir"].name) else "-"),
        }
        for item in output_dirs
    ]
    output_filters = {
        "cluster": sorted({row["cluster"] for row in output_filter_rows}),
        "mpi": sorted({row["mpi"] for row in output_filter_rows}),
        "topology": sorted({row["topology"] for row in output_filter_rows}),
        "size": sorted({row["size"] for row in output_filter_rows}, key=_payload_label_sort_key),
        "compute": sorted({row["compute"] for row in output_filter_rows}),
        "run": sorted({row["run"] for row in output_filter_rows}, reverse=True),
    }

    table_rows = []
    for idx, p in enumerate(scripts):
        meta = _script_meta(p)
        is_bundle = meta["cluster"] == "cm4_std" and meta["grid"] == "bundle"
        has_output = p.parent.resolve() in output_dir_set
        row_class = "script-row has-output" if has_output else "script-row"
        row_title = " title='Output detected for this script directory'" if has_output else ""
        submit_button = ""
        if meta["cluster"] == "cm4_std":
            submit_button = (
                f"&nbsp;<button type='button' class='copy-btn' "
                f"onclick=\"copyStdCmd('{escape(meta['abs'])}')\" "
                "title='Copy sbatch command for cm4_std'>std</button>"
            )
        elif meta["cluster"] == "cm4_inter":
            submit_button = (
                f"&nbsp;<button type='button' class='copy-btn' "
                f"onclick=\"copyInterCmd('{escape(meta['abs'])}')\" "
                "title='Copy interactive bash command for cm4_inter'>inter</button>"
            )
        expand_cell = "<td></td>"
        bundle_detail = ""
        if is_bundle:
            expand_cell = (
                f"<td><button type='button' class='copy-btn' onclick=\"toggleBundleRow('bundle_{idx}')\" "
                f"id='toggle_bundle_{idx}' title='Expand child scripts'>+</button></td>"
            )
            bundle_detail = (
                f"<tr class='bundle-detail-row row-hidden' id='detail_bundle_{idx}'>"
                "<td></td><td colspan='8' style='background:#fbfcff' "
                f"data-bundle-path='{escape(meta['abs'], quote=True)}'>"
                "<table class='bundle-child-table' style='width:100%;border-collapse:collapse'>"
                "<thead><tr><th style='width:36px'></th><th>Face Payload / Rank</th><th>Compute</th>"
                "<th>Run</th><th>Child script</th><th style='width:80px'></th></tr></thead>"
                "<tbody><tr><td colspan='6'><em>Expand to load child scripts</em></td></tr></tbody>"
                "</table></td></tr>"
            )
        table_rows.append(
            f"<tr class='{row_class}'{row_title}"
            f" data-cluster='{escape(meta['cluster'])}'"
            f" data-mpi='{escape(meta['mpi'])}'"
            f" data-topology='{escape(meta['topology'])}'"
            f" data-size='{escape(meta['size'])}'"
            f" data-compute='{escape(meta['compute'])}'"
            f" data-run='{escape(meta['run'])}'"
            f" data-rel='{escape(meta['rel'])}'>"
            f"{expand_cell}"
            f'<td><input type="checkbox" name="script" value="{escape(meta["abs"])}"></td>'
            f"<td>{escape(meta['cluster'])}</td>"
            f"<td>{escape(meta['mpi'])}</td>"
            f"<td>{escape(meta['topology'])}</td>"
            f"<td>{escape(meta['size'])}</td>"
            f"<td>{escape(meta['compute'])}</td>"
            f"<td>{escape(meta['run'])}</td>"
            f"<td style='white-space:nowrap'><button type='button' class='open-btn' onclick=\"openInCode('{escape(meta['abs'])}')\" title='Open script'>&#128065;</button>&nbsp;<button type='button' class='copy-btn' onclick=\"copyPath('{escape(meta['abs'])}')\" title='Copy script path'>📋</button>{submit_button}</td>"
            "</tr>"
            f"{bundle_detail}"
        )
    table_html = "\n".join(table_rows) or "<tr><td colspan='9'><em>No generated scripts yet.</em></td></tr>"

    output_rows = []
    for idx, item in enumerate(output_dirs):
        meta = output_meta[item["dir"]]
        display_run = item.get("run") or (item["dir"].name if RUN_DIR.match(item["dir"].name) else "-")
        output_row_class = "output-row analysis-output" if meta["compute"] == "analysis" else "output-row"
        chart_files = [path for path in item["files"] if path.suffix == ".png"] if meta["compute"] == "analysis" else []
        latest_chart_button = (
            f'<button type="button" class="open-btn" onclick="openChart(\'{escape(str(chart_files[0]))}\')" '
            f'title="Open latest overlap chart">chart</button>&nbsp;'
            if chart_files else ""
        )
        download_chart_button = (
            f'<a class="open-btn" href="/download-chart?path={quote(str(chart_files[0]))}" '
            f'title="Download latest overlap chart PNG" download>&#8681;</a>&nbsp;'
            if chart_files else ""
        )
        delete_chart_button = (
            f'<button type="submit" name="action" value="delete_chart" '
            f'onclick="setChartToDelete(\'{escape(meta["abs"])}\'); return confirm(\'Delete this chart, its CSV, and its note? Raw results will be kept.\')" '
            f'title="Delete chart, CSV, and note">&#128465;</button>&nbsp;'
            if meta["compute"] == "analysis" and (item["dir"] / "overlap_metrics.png").is_file() else ""
        )
        run_dir = item["dir"].name if RUN_DIR.match(item["dir"].name) else None
        if run_dir:
            experiment_dir = item["dir"].parent.parent
            midcomm_dir = experiment_dir / "midcomm" / run_dir
            no_midcomm_dir = experiment_dir / "no_midcomm" / run_dir
            analysis_dir = _analysis_dir_for_run(experiment_dir, midcomm_dir)
        else:
            experiment_dir = item["dir"].parent
            midcomm_dir = experiment_dir / "midcomm"
            no_midcomm_dir = experiment_dir / "no_midcomm"
            analysis_dir = _analysis_dir_for_run(experiment_dir, midcomm_dir)
        chart_name = f"overlap_metrics_{run_dir}.png" if run_dir else "overlap_metrics.png"
        chart_exists = (analysis_dir / chart_name).is_file()
        result_kind = item["dir"].parent.name if run_dir else item["dir"].name
        can_analyze = (
            result_kind in {"midcomm", "no_midcomm"}
            and midcomm_dir.is_dir()
            and no_midcomm_dir.is_dir()
            and any(midcomm_dir.glob("Comb_*_summary.csv"))
            and any(no_midcomm_dir.glob("Comb_*_summary.csv"))
        )
        chart_button_class = "copy-btn chart-ready" if chart_exists else "copy-btn"
        chart_button_title = "Copy command to regenerate chart" if chart_exists else "Copy paired MPI and mock analysis command"
        chart_button = (
            f'<button type="button" class="{chart_button_class}" '
            f'onclick="copyAnalyzeCommand(\'{escape(str(midcomm_dir))}\', \'{escape(str(no_midcomm_dir))}\', \'{escape(str(analysis_dir))}\')" '
            f'title="{chart_button_title}">chart</button>&nbsp;'
            if can_analyze else ""
        )
        output_count = f"{len(chart_files)} charts" if meta["compute"] == "analysis" else f"{item['count']} files"
        detail_heading = "Charts" if meta["compute"] == "analysis" else "Files"
        output_value = meta["abs"]
        if meta["compute"] == "analysis" and item.get("run"):
            output_value = f"analysis-run:{item['run']}:{meta['abs']}"
        output_rows.append(
            f"<tr class='{output_row_class}' data-output-id='out_{idx}'"
            f" data-cluster='{escape(meta['cluster'])}'"
            f" data-mpi='{escape(meta['mpi'])}'"
            f" data-topology='{escape(meta['topology'])}'"
            f" data-size='{escape(meta['size'])}'"
            f" data-compute='{escape(meta['compute'])}'"
            f" data-run='{escape(display_run)}'>"
            f"<td><button type='button' class='copy-btn' onclick=\"toggleOutputRow('out_{idx}')\" id='toggle_out_{idx}' title='Expand output files'>+</button></td>"
            f'<td><input type="checkbox" name="output_dir" value="{escape(output_value)}"></td>'
            f"<td>{escape(meta['cluster'])}</td>"
            f"<td>{escape(meta['mpi'])}</td>"
            f"<td>{escape(meta['topology'])}</td>"
            f"<td>{escape(meta['size'])}</td>"
            f"<td>{escape(meta['compute'])}</td>"
            f"<td>{escape(display_run)}</td>"
            f"<td class='col-result-dir'>{escape(meta['rel'])}</td>"
            f"<td>{output_count}</td>"
            f"<td style='white-space:nowrap'>{chart_button}{latest_chart_button}{delete_chart_button}{download_chart_button}<button type='button' class='copy-btn' onclick=\"copyPath('{escape(meta['abs'])}')\" title='Copy result directory'>📋</button></td>"
            "</tr>"
            f"<tr class='output-detail-row row-hidden' id='detail_out_{idx}'>"
            "<td></td>"
            f"<td colspan='10' style='background:#fbfcff' data-output-path='{escape(meta['abs'], quote=True)}' "
            f"data-output-run='{escape(item.get('run') or '', quote=True)}'>"
            "<table style='width:100%;border-collapse:collapse'>"
            f"<thead><tr><th style='text-align:left'>{detail_heading}</th><th style='width:132px'></th></tr></thead>"
            "<tbody><tr><td colspan='2'><em>Expand to load files</em></td></tr></tbody>"
            "</table>"
            "</td>"
            "</tr>"
        )
    output_table_html = "\n".join(output_rows) or "<tr><td colspan='11'><em>No output directories yet.</em></td></tr>"

    script_js = """
const scriptRows = Array.from(document.querySelectorAll('tr.script-row'));
const outputRows = Array.from(document.querySelectorAll('tr.output-row'));
const projectRoot = __PROJECT_ROOT_JSON__;
const scrollPositionKey = 'mpi_lab_scroll_position';
const scriptFilterStateKey = 'mpi_lab_script_filters';
const outputFilterStateKey = 'mpi_lab_output_filters';
const scriptFilterIds = ['f_cluster', 'f_mpi', 'f_topology', 'f_size', 'f_compute', 'f_run', 'f_keyword'];
const outputFilterIds = ['of_cluster', 'of_mpi', 'of_topology', 'of_size', 'of_compute', 'of_run'];
let dragSelecting = false;
let dragTargetState = false;
let lastClicked = null;

const savedScrollPosition = sessionStorage.getItem(scrollPositionKey);
if (savedScrollPosition !== null) {
    sessionStorage.removeItem(scrollPositionKey);
    requestAnimationFrame(() => window.scrollTo(0, Number(savedScrollPosition)));
}

document.getElementById('main_form')?.addEventListener('submit', () => {
    sessionStorage.setItem(scrollPositionKey, String(window.scrollY));
    saveFilterState(scriptFilterStateKey, scriptFilterIds);
    saveFilterState(outputFilterStateKey, outputFilterIds);
});

function saveFilterState(storageKey, ids) {
    const state = {};
    for (const id of ids) {
        const el = document.getElementById(id);
        if (el) state[id] = el.value;
    }
    sessionStorage.setItem(storageKey, JSON.stringify(state));
}

function restoreFilterState(storageKey, ids) {
    let state;
    try {
        state = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    } catch (_) {
        return;
    }
    for (const id of ids) {
        const value = state[id];
        const el = document.getElementById(id);
        if (el && typeof value === 'string') el.value = value;
    }
}

function isVisibleRow(row) {
    return !row.classList.contains('row-hidden');
}

function setVisibleCount() {
    const visible = scriptRows.filter(isVisibleRow).length;
    const total = scriptRows.length;
    const el = document.getElementById('visible_count');
    if (el) el.textContent = visible + ' visible / ' + total + ' total';
}

function scriptRowMatches(row, filters) {
    return (
        (!filters.cluster || row.dataset.cluster === filters.cluster) &&
        (!filters.mpi || row.dataset.mpi === filters.mpi) &&
        (!filters.topology || row.dataset.topology === filters.topology) &&
        (!filters.size || row.dataset.size === filters.size) &&
        (!filters.compute || row.dataset.compute === filters.compute) &&
        (!filters.run || row.dataset.run === filters.run) &&
        (!filters.keyword || (row.dataset.rel || '').toLowerCase().includes(filters.keyword))
    );
}

function applyFilters() {
    const filters = {
        cluster: document.getElementById('f_cluster')?.value || '',
        mpi: document.getElementById('f_mpi')?.value || '',
        topology: document.getElementById('f_topology')?.value || '',
        size: document.getElementById('f_size')?.value || '',
        compute: document.getElementById('f_compute')?.value || '',
        run: document.getElementById('f_run')?.value || '',
        keyword: (document.getElementById('f_keyword')?.value || '').trim().toLowerCase(),
    };

    for (const row of scriptRows) {
        const bundleId = row.querySelector('[id^="toggle_bundle_"]')?.id.replace('toggle_', '');
        const detail = bundleId ? document.getElementById('detail_' + bundleId) : null;
        const children = detail ? Array.from(detail.querySelectorAll('tr.bundle-child-row')) : [];
        let pass = scriptRowMatches(row, filters);
        if (bundleId) {
            if (children.length) {
                for (const child of children) {
                    const childPass = scriptRowMatches(child, filters);
                    child.classList.toggle('row-hidden', !childPass);
                    if (!childPass) {
                        const box = child.querySelector('input[name="script"]');
                        if (box) box.checked = false;
                    }
                }
                pass = children.some(child => !child.classList.contains('row-hidden'));
            } else {
                pass =
                    (!filters.cluster || row.dataset.cluster === filters.cluster) &&
                    (!filters.mpi || row.dataset.mpi === filters.mpi) &&
                    (!filters.topology || row.dataset.topology === filters.topology);
            }
        }
        row.classList.toggle('row-hidden', !pass);
        if (!pass && detail) {
            detail.classList.add('row-hidden');
            const toggle = document.getElementById('toggle_' + bundleId);
            if (toggle) toggle.textContent = '+';
        }
        if (!pass) {
            const box = row.querySelector('input[name="script"]');
            if (box) box.checked = false;
        }
    }
    setVisibleCount();
}

async function toggleBundleRow(rowId) {
    const row = document.getElementById('detail_' + rowId);
    const btn = document.getElementById('toggle_' + rowId);
    if (!row || !btn) return;
    const hidden = row.classList.toggle('row-hidden');
    btn.textContent = hidden ? '+' : '-';
    btn.title = hidden ? 'Expand child scripts' : 'Collapse child scripts';
    if (hidden || row.dataset.loaded === 'true') return;
    const cell = row.querySelector('td[data-bundle-path]');
    const body = cell?.querySelector('tbody');
    if (!cell || !body) return;
    body.innerHTML = "<tr><td colspan='6'><em>Loading...</em></td></tr>";
    const query = new URLSearchParams({path: cell.dataset.bundlePath});
    try {
        const response = await fetch('/bundle-scripts?' + query);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        body.innerHTML = await response.text();
        row.dataset.loaded = 'true';
        applyFilters();
    } catch (error) {
        body.innerHTML = "<tr><td colspan='6'><em>Failed to load child scripts</em></td></tr>";
    }
}

function resetFilters() {
    scriptFilterIds.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = '';
    });
    saveFilterState(scriptFilterStateKey, scriptFilterIds);
    applyFilters();
}

function selectVisible(state) {
    const rows = Array.from(document.querySelectorAll('tr.script-row, tr.bundle-child-row'));
    for (const row of rows) {
        if (!isVisibleRow(row)) continue;
        const detail = row.closest('tr.bundle-detail-row');
        if (detail?.classList.contains('row-hidden')) continue;
        const box = row.querySelector('input[name="script"]');
        if (box) box.checked = state;
    }
}

for (const id of ['f_cluster', 'f_mpi', 'f_topology', 'f_size', 'f_compute', 'f_run']) {
    document.getElementById(id)?.addEventListener('change', () => {
        saveFilterState(scriptFilterStateKey, scriptFilterIds);
        applyFilters();
    });
}
document.getElementById('f_keyword')?.addEventListener('input', () => {
    saveFilterState(scriptFilterStateKey, scriptFilterIds);
    applyFilters();
});

for (const row of scriptRows) {
    const box = row.querySelector('input[name="script"]');
    if (!box) continue;

    box.addEventListener('click', (e) => {
        if (e.shiftKey && lastClicked) {
            const all = scriptRows.map((r) => r.querySelector('input[name="script"]')).filter(Boolean);
            const i1 = all.indexOf(lastClicked);
            const i2 = all.indexOf(box);
            if (i1 >= 0 && i2 >= 0) {
                const start = Math.min(i1, i2);
                const end = Math.max(i1, i2);
                for (let i = start; i <= end; i++) all[i].checked = box.checked;
            }
        }
        lastClicked = box;
    });

    box.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragSelecting = true;
        dragTargetState = null;
    });

    box.addEventListener('change', () => {
        if (dragSelecting && dragTargetState === null) {
            dragTargetState = box.checked;
        }
    });

    box.addEventListener('mouseenter', (e) => {
        if (!dragSelecting) return;
        if (!(e.buttons & 1)) return;
        if (dragTargetState === null) return;
        box.checked = dragTargetState;
    });
}

document.addEventListener('mouseup', () => {
    dragSelecting = false;
});

function selectAllOutputs(state) {
    for (const row of outputRows) {
        if (row.classList.contains('row-hidden')) continue;
        const box = row.querySelector('input[name="output_dir"]');
        if (box) box.checked = state;
    }
}

function applyOutputFilters() {
    const fc = document.getElementById('of_cluster')?.value || '';
    const fm = document.getElementById('of_mpi')?.value || '';
    const ft = document.getElementById('of_topology')?.value || '';
    const fs = document.getElementById('of_size')?.value || '';
    const fcp = document.getElementById('of_compute')?.value || '';
    const fr = document.getElementById('of_run')?.value || '';
    for (const row of outputRows) {
        const show =
            (!fc || row.dataset.cluster === fc) &&
            (!fm || row.dataset.mpi === fm) &&
            (!ft || row.dataset.topology === ft) &&
            (!fs || row.dataset.size === fs) &&
            (!fcp || row.dataset.compute === fcp) &&
            (!fr || row.dataset.run === fr);
        row.classList.toggle('row-hidden', !show);
        if (!show) {
            const box = row.querySelector('input[name="output_dir"]');
            if (box) box.checked = false;
        }
        const detail = document.getElementById('detail_' + row.dataset.outputId);
        if (detail) detail.classList.add('row-hidden');
        const toggle = document.getElementById('toggle_' + row.dataset.outputId);
        if (toggle) toggle.textContent = '+';
    }
}

function resetOutputFilters() {
    outputFilterIds.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    saveFilterState(outputFilterStateKey, outputFilterIds);
    applyOutputFilters();
}

for (const id of outputFilterIds) {
    document.getElementById(id)?.addEventListener('change', () => {
        saveFilterState(outputFilterStateKey, outputFilterIds);
        applyOutputFilters();
    });
}

async function toggleOutputRow(rowId) {
    const row = document.getElementById('detail_' + rowId);
    const btn = document.getElementById('toggle_' + rowId);
    if (!row || !btn) return;
    const hidden = row.classList.toggle('row-hidden');
    btn.textContent = hidden ? '+' : '-';
    btn.title = hidden ? 'Expand output files' : 'Collapse output files';
    const cell = row.querySelector('td[data-output-path]');
    if (hidden || !cell || cell.dataset.loaded === 'true') return;
    const body = cell.querySelector('tbody');
    body.innerHTML = "<tr><td colspan='2'><em>Loading...</em></td></tr>";
    const query = new URLSearchParams({path: cell.dataset.outputPath, run: cell.dataset.outputRun});
    try {
        const response = await fetch('/output-files?' + query);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        body.innerHTML = await response.text();
        cell.dataset.loaded = 'true';
    } catch (error) {
        body.innerHTML = "<tr><td colspan='2'><em>Failed to load files</em></td></tr>";
    }
}

restoreFilterState(scriptFilterStateKey, scriptFilterIds);
restoreFilterState(outputFilterStateKey, outputFilterIds);
applyFilters();
applyOutputFilters();

function openInCode(path) {
    fetch('/open?path=' + encodeURIComponent(path))
        .then(r => r.json())
        .then(d => { if (!d.ok) alert('Failed to open: ' + (d.error || 'unknown error')); })
        .catch(() => alert('Request failed'));
}

function openChart(path) {
    const chartWindow = window.open('/chart?path=' + encodeURIComponent(path), '_blank');
    if (chartWindow) {
        chartWindow.opener = null;
        const keepGuiFocused = () => {
            chartWindow.blur();
            window.focus();
        };
        chartWindow.addEventListener('load', keepGuiFocused, { once: true });
        window.setTimeout(keepGuiFocused, 100);
    }
}

function setChartToDelete(path) {
    const field = document.getElementById('analysis_dir_to_delete');
    if (field) field.value = path;
}

function copyAnalyzeCommand(midcommDir, noMidcommDir, outputDir) {
    const quote = (value) => "'" + String(value).replace(/'/g, "'\\''") + "'";
    {
        const portableCommand = quote(projectRoot + '/venv/bin/python') + ' ' + quote(projectRoot + '/analyze_overlap.py') +
            ' --midcomm-dir ' + quote(midcommDir) +
            ' --no-midcomm-dir ' + quote(noMidcommDir) +
            ' --output-dir ' + quote(outputDir);
        copyText(portableCommand, 'Analysis command copied to clipboard.');
        return;
    }
    const command = './venv/bin/python analyze_overlap.py \\\n+  --midcomm-dir ' + quote(parent + '/midcomm') + ' \\\n+  --no-midcomm-dir ' + quote(parent + '/no_midcomm') + ' \\\n+  --output-dir ' + quote(parent + '/analysis');
    navigator.clipboard.writeText(command).then(() => {
        alert('Analysis command copied to clipboard.');
    }).catch(() => {
        prompt('Copy and run this command:', command);
    });
}

function copySelectedChartCommands() {
    const prefix = 'analysis-run:';
    const seen = new Set();
    const commands = [];

    for (const row of outputRows) {
        const box = row.querySelector('input[name="output_dir"]');
        if (!box?.checked) continue;

        let run = '';
        let analysisDir = '';
        let experimentDir = '';
        if (box.value.startsWith(prefix)) {
            const separator = box.value.indexOf(':', prefix.length);
            if (separator < 0) continue;
            run = box.value.slice(prefix.length, separator);
            analysisDir = box.value.slice(separator + 1);
            experimentDir = analysisDir.replace(/\/analysis$/, '');
        } else {
            const sourceMatch = box.value.match(/^(.*)\/(?:midcomm|no_midcomm)\/(run_\d+)$/);
            if (!sourceMatch) continue;
            experimentDir = sourceMatch[1];
            run = sourceMatch[2];
            analysisDir = experimentDir + '/analysis';
        }
        if (!/^run_\d+$/.test(run)) continue;
        if (!run || !experimentDir || seen.has(analysisDir + ':' + run)) continue;
        seen.add(analysisDir + ':' + run);

        commands.push(
            shellQuote(projectRoot + '/venv/bin/python') + ' ' + shellQuote(projectRoot + '/analyze_overlap.py') +
            ' --midcomm-dir ' + shellQuote(experimentDir + '/midcomm/' + run) +
            ' --no-midcomm-dir ' + shellQuote(experimentDir + '/no_midcomm/' + run) +
            ' --output-dir ' + shellQuote(analysisDir)
        );
    }

    if (!commands.length) {
        alert('Select one or more run result rows.');
        return;
    }

    const command = commands.join(' && ');
    copyText(command, 'Copied ' + commands.length + ' chart command(s).');
}

function copyAverageChartCommand() {
    const prefix = 'analysis-run:';
    const selections = [];
    const seen = new Set();

    for (const row of outputRows) {
        const box = row.querySelector('input[name="output_dir"]');
        if (!box?.checked || !box.value.startsWith(prefix)) continue;
        const separator = box.value.indexOf(':', prefix.length);
        if (separator < 0) continue;
        const run = box.value.slice(prefix.length, separator);
        const analysisDir = box.value.slice(separator + 1);
        const experimentDir = analysisDir.replace(/\/analysis$/, '');
        if (!/^run_\d+$/.test(run)) continue;
        const midcommDir = experimentDir + '/midcomm/' + run;
        if (!run || seen.has(midcommDir)) continue;
        seen.add(midcommDir);
        selections.push({ midcommDir, analysisDir });
    }

    if (selections.length < 2) {
        alert('Select at least two analysis run rows from the same experiment.');
        return;
    }
    const outputDirs = new Set(selections.map(selection => selection.analysisDir));
    if (outputDirs.size !== 1) {
        alert('Select analysis runs from one experiment only.');
        return;
    }
    const command = shellQuote(projectRoot + '/venv/bin/python') + ' ' + shellQuote(projectRoot + '/analyze_overlap.py') +
        selections.map(selection => ' --average-midcomm-dir ' + shellQuote(selection.midcommDir)).join('') +
        ' --output-dir ' + shellQuote(selections[0].analysisDir);
    copyText(command, 'Average chart command copied. It will reject inconsistent experiment configurations.');
}

function downloadSelectedCharts() {
    const prefix = 'analysis-run:';
    const seen = new Set();
    const charts = [];

    for (const row of outputRows) {
        const box = row.querySelector('input[name="output_dir"]');
        if (!box?.checked || !box.value.startsWith(prefix)) continue;

        const separator = box.value.indexOf(':', prefix.length);
        if (separator < 0) continue;
        const run = box.value.slice(prefix.length, separator);
        const analysisDir = box.value.slice(separator + 1);
        const chartPath = analysisDir + '/overlap_metrics_' + run + '.png';
        if (!run || seen.has(chartPath)) continue;
        seen.add(chartPath);
        charts.push(chartPath);
    }

    if (!charts.length) {
        alert('Select one or more analysis rows.');
        return;
    }

    const query = charts.map(chartPath => 'path=' + encodeURIComponent(chartPath)).join('&');
    const link = document.createElement('a');
    link.href = '/download-charts?' + query;
    link.download = 'comb_overlap_charts.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
}

function copyText(text, successMessage) {
    try {
        if (!navigator.clipboard?.writeText) {
            prompt('Copy and run this command:', text);
            return;
        }
        navigator.clipboard.writeText(text)
            .then(() => alert(successMessage))
            .catch(() => prompt('Copy and run this command:', text));
    } catch (_) {
        prompt('Copy and run this command:', text);
    }
}

function copySallocCmd(profile) {
    const nodes = document.getElementById('salloc_nodes')?.value || '1';
    const ntasks = document.getElementById('salloc_ntasks')?.value || '1';
    const ntpn = document.getElementById('salloc_ntasks_per_node')?.value || '1';
    const cpt = document.getElementById('salloc_cpus_per_task')?.value || '1';
    const time = document.getElementById('salloc_time')?.value || SALLOC_DEFAULT_TIME;
    const machine = profile === 'cm4_inter' ? 'inter' : 'cm4';
    const partition = profile === 'cm4_inter' ? 'cm4_inter' : 'cm4_std';
    const cmd = 'salloc -M ' + machine + ' -p ' + partition +
        ' -N ' + nodes + ' -n ' + ntasks +
        ' --ntasks-per-node=' + ntpn + ' -c ' + cpt +
        ' -t ' + time;
    navigator.clipboard.writeText(cmd).then(() => {
        alert('Copied: ' + cmd);
    }).catch(() => {
        alert('Failed to copy');
    });
}

function copyStdCmd(path) {
    const cmd = 'sbatch ' + shellQuote(path);
    navigator.clipboard.writeText(cmd).then(() => {
        alert('Copied: ' + cmd);
    }).catch(() => {
        alert('Failed to copy');
    });
}

function copyInterCmd(path) {
    const slash = path.lastIndexOf('/');
    const dir = slash >= 0 ? path.slice(0, slash) : '.';
    const file = slash >= 0 ? path.slice(slash + 1) : path;
    const cmd = 'cd ' + shellQuote(dir) + ' && bash ' + shellQuote(file);
    navigator.clipboard.writeText(cmd).then(() => {
        alert('Copied: ' + cmd);
    }).catch(() => {
        alert('Failed to copy');
    });
}

function copySelectedRunCommands() {
    const selected = Array.from(document.querySelectorAll('input[name="script"]:checked'))
        .map((box) => ({ row: box.closest('tr'), box }))
        .filter(({ box }) => box?.checked);
    if (!selected.length) {
        alert('Select at least one script.');
        return;
    }

    const commands = selected.map(({ row, box }) => {
        const path = box.value;
        if (row.dataset.cluster === 'cm4_std' && row.dataset.kind !== 'child') {
            return 'sbatch ' + shellQuote(path);
        }
        const slash = path.lastIndexOf('/');
        const dir = slash >= 0 ? path.slice(0, slash) : '.';
        const file = slash >= 0 ? path.slice(slash + 1) : path;
        return 'cd ' + shellQuote(dir) + ' && bash ' + shellQuote(file);
    });
    const command = commands.join(' && \\\n');
    navigator.clipboard.writeText(command).then(() => {
        alert('Copied ' + selected.length + ' sequential run command(s).');
    }).catch(() => {
        prompt('Copy and run this command:', command);
    });
}

function copyPath(path) {
    navigator.clipboard.writeText(path).then(() => {
        alert('Copied: ' + path);
    }).catch(() => {
        alert('Failed to copy');
    });
}
""".replace("__PROJECT_ROOT_JSON__", json.dumps(str(ROOT)))

    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><title>mpi_lab web gui</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f6fb;margin:0}} .w{{max-width:1320px;margin:20px auto;background:#fff;padding:14px;border-radius:12px}}
.g{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;align-items:start}} .c{{border:1px solid #c7d2e6;border-radius:8px;padding:6px;box-shadow:0 2px 8px rgba(24,39,75,0.06);background:#fff}}
.panel{{border:1px solid #b7c5df;border-radius:12px;padding:12px;background:linear-gradient(180deg,#ffffff 0%,#f8fbff 100%);box-shadow:0 10px 28px rgba(24,39,75,0.10), inset 0 1px 0 rgba(255,255,255,0.9)}}
.g .c h4{{margin:0 0 6px 0;font-size:14px}}
.g .c label{{font-size:13px;line-height:1.35;margin-bottom:2px}}
button{{padding:8px 12px;border-radius:8px;border:0;background:#8ea9dd;color:#fff;cursor:pointer;transition:all 0.15s ease}}
button:hover{{filter:brightness(1.08);transform:translateY(-1px);box-shadow:0 4px 10px rgba(24,39,75,0.14)}}
button.danger{{background:#e4a0a4}}
button.danger:hover{{background:#d98c93;filter:brightness(1.08);transform:translateY(-1px);box-shadow:0 4px 10px rgba(24,39,75,0.14)}}
button.open-btn{{padding:3px 6px;background:#f0f0f0;color:#333;border:1px solid #ccc;border-radius:6px;font-size:14px}}
button.open-btn:hover{{background:#d0eaff}}
button.copy-btn{{padding:3px 6px;background:#f0f0f0;color:#333;border:1px solid #ccc;border-radius:6px;font-size:14px}}
button.copy-btn:hover{{background:#fff4d0}}
button.copy-btn.chart-ready{{background:#d8dde4;color:#6b7280;border-color:#c4cad2}}
button.copy-btn.chart-ready:hover{{background:#cbd1da;color:#374151}}
.msg{{margin:10px 0;padding:8px;background:#e8f6ea;border:1px solid #9bcf9f;border-radius:8px}}
.toolbar button{{margin-right:8px}} table{{width:100%;border-collapse:collapse}} th,td{{border:1px solid #d9dfee;padding:6px 8px;text-align:left;vertical-align:top}}
th.col-mini,td.col-mini{{white-space:nowrap}}
th.col-result-dir,td.col-result-dir{{overflow-wrap:anywhere;word-break:break-word;min-width:180px}}
.filters{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:8px;margin:10px 0}}
.filters .c{{padding:6px}}
.filters label{{display:block;font-size:12px;color:#444;margin-bottom:4px}}
.filters select,.filters input{{width:100%;box-sizing:border-box}}
.script-row.has-output{{opacity:0.42;transition:opacity .15s ease}}
.script-row.has-output:hover{{opacity:0.76}}
.bundle-child-table td{{background:#fbfcff}}
.bundle-child-table tbody tr:hover td{{background:#eef4ff}}
.output-row.analysis-output td{{background:#e8f6ea}}
.output-row.analysis-output:hover td{{background:#d9f0dd}}
.row-hidden{{display:none}}
.std-disabled{{opacity:.42;pointer-events:none}}
@media(max-width:980px){{.w{{max-width:100%}} .g{{grid-template-columns:1fr 1fr}}}} @media(max-width:560px){{.g{{grid-template-columns:1fr}}}}
</style></head>
<body><div class="w">
<h2>mpi_lab script generator + manager (web)</h2>
<div class="quickguide" style="background:#eef4ff;border:1px solid #b8cdf8;border-radius:10px;padding:12px 16px;margin-bottom:16px">
<h3 style="margin:0 0 8px 0">Quick Guide</h3>
<ul style="margin:0;padding-left:18px;line-height:1.9">
<li><strong>MPI</strong>: Select one or more MPI implementations to include.</li>
<li><strong>Topology</strong>: Choose node/rank layout. Halo payload labels update dynamically based on your selection.</li>
<li><strong>Halo Payload</strong>: Three grid tiers sorted small &#8594; medium &#8594; large. Labels show one X/Y/Z halo-face payload, not a complete MPI buffer.</li>
<li><strong>Compute mode</strong>: Scripts are automatically generated for <em>both</em> compute modes (<code>midcomm</code> and <code>no_midcomm</code>) &mdash; no manual selection needed.</li>
<li><strong>Backend runs</strong>: MPI-only and Mock-only are selected by default and generated as separate, paired run directories.</li>
<li><strong>Cluster</strong>: Choose one or both target partitions for script generation.</li>
</ul>
<table style="width:100%;border-collapse:collapse;margin-top:12px;font-size:13px">
<thead>
<tr>
<th style="border:1px solid #b8cdf8;padding:6px 8px;text-align:left">MPI</th>
<th style="border:1px solid #b8cdf8;padding:6px 8px;text-align:left">Reference threshold</th>
<th style="border:1px solid #b8cdf8;padding:6px 8px;text-align:left">Env vars</th>
<th style="border:1px solid #b8cdf8;padding:6px 8px;text-align:left">Note</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border:1px solid #b8cdf8;padding:6px 8px">Intel MPI</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">4,194,304</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">I_MPI_EAGER_THRESHOLD / I_MPI_SHM_EAGER_THRESHOLD</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">Reference only; scripts do not set it</td>
</tr>
<tr>
<td style="border:1px solid #b8cdf8;padding:6px 8px">Open MPI</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">vader=4,096; tcp=65,536</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">OMPI_MCA_btl_vader_eager_limit / OMPI_MCA_btl_tcp_eager_limit</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">Reference only; scripts do not set it</td>
</tr>
<tr>
<td style="border:1px solid #b8cdf8;padding:6px 8px">MPICH</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">262,144</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">MPIR_CVAR_CH4_OFI_EAGER_MAX_MSG_SIZE</td>
<td style="border:1px solid #b8cdf8;padding:6px 8px">Reference only; scripts do not set it</td>
</tr>
</tbody>
</table>
<div style="margin-top:8px;color:#555;font-size:12px">This table is reference-only. The generated scripts do not set these MPI thresholds.</div>
</div>
<form id="main_form" method="post">
<div class="c panel" style="margin-top:12px">
<h4 style="margin:0 0 10px 0">Config</h4>
<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center">
<label>Config <select name="config">{''.join(opts)}</select></label>
<label data-std-disabled><input type="checkbox" name="dry_run" value="1" {dry_run_checked}> Dry run</label>
<label data-std-disabled style="flex:1 1 360px">Output override <input type="text" name="output" value="{output_override_value}" style="width:100%;box-sizing:border-box;margin-top:4px"></label>
</div>
<div class="g" style="margin-top:10px">
<div class="c"><h4>Cluster</h4>{ck('cluster')}</div>
<div class="c"><h4>MPI</h4>{ck('mpi')}</div>
<div class="c"><h4>Topology</h4>{ck('topology')}</div>
<div class="c"><h4>Backend runs</h4>
<label><input type="checkbox" name="backend_mode" value="both" {backend_mode_checked['both']}> MPI + Mock (same process)</label><br>
<label><input type="checkbox" name="backend_mode" value="mpi_only" {backend_mode_checked['mpi_only']}> MPI only</label><br>
<label><input type="checkbox" name="backend_mode" value="mock_only" {backend_mode_checked['mock_only']}> Mock only</label>
<div style="margin-top:5px;color:#555;font-size:11px">Independent modes generate paired run_###_MPIonly and run_###_Mockonly directories; same-process mode uses run_###.</div>
</div>
<div class="c" data-std-disabled><h4>Cycles</h4><input type="number" name="cycles_override" min="1" step="1" value="{cycles_value}" placeholder="Use grid default" style="width:100%;box-sizing:border-box"><div style="margin-top:5px;color:#555;font-size:11px">Optional. Overrides cycles for every selected grid in this generation.</div></div>
<div class="c" data-std-disabled><h4>Face Payload Estimate / Rank</h4>{ck_grid()}
<div style="border-top:1px solid #d8dfec;margin-top:7px;padding-top:7px">
<label><input id="use_custom_payload" type="checkbox" name="use_custom_payload" value="1" {custom_checked}> Custom grid</label>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;margin-top:6px">
<label>Grid X_Y_Z<input id="custom_grid_size" name="custom_grid_size" type="text" value="{custom_grid_size}" style="width:100%;box-sizing:border-box"></label>
<label>Ghost X_Y_Z<input id="custom_ghost" name="custom_ghost" type="text" value="{custom_ghost}" style="width:100%;box-sizing:border-box"></label>
<label>Vars<input id="custom_vars" name="custom_vars" type="number" min="1" value="{custom_vars}" style="width:100%;box-sizing:border-box"></label>
<label>Compute target (us)<input id="custom_compute_target_us" name="custom_compute_target_us" type="number" min="0" step="any" value="{custom_compute_target}" style="width:100%;box-sizing:border-box"></label>
</div>
<div id="custom_payload_estimate" style="margin-top:5px;font-size:11px;font-weight:600;color:#234b8f"></div>
</div>
<div style="margin-top:5px;color:#555;font-size:11px">X/Y/Z are single halo-face payload estimates. Divide is taken from each selected topology. Custom values affect generated scripts but do not modify the YAML. Comb can combine face, edge, and corner boxes into a larger MPI_Isend.</div></div>
<div class="c" style="grid-column:1/-1"><h4>Test Cases</h4><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0 14px">{case_box_html}</div></div>
</div>
<div class="toolbar" style="margin-top:12px;display:flex;align-items:center;gap:8px">
<label data-std-disabled style="font-size:13px">Runs <input type="number" name="run_count" min="1" step="1" value="{run_count_value}" title="Number of sequential run_### directories to generate" style="width:64px;box-sizing:border-box;margin-left:4px"></label>
<button type="submit" name="action" value="generate">Generate scripts</button>
</div>
</div>

<div class="c panel" style="margin-top:12px">
<h4 style="margin:0 0 10px 0">Salloc Helper</h4>
<div class="filters" style="grid-template-columns:repeat(6,minmax(120px,1fr))">
<div class="c"><label>Helper Topology</label><select id="salloc_topology"></select></div>
<div class="c"><label>Nodes</label><input type="number" id="salloc_nodes" min="1" value="1"></div>
<div class="c"><label>Ranks</label><input type="number" id="salloc_ntasks" min="1" value="1" readonly style="background:#f6f8fc;color:#4b5567"></div>
<div class="c"><label>Ranks / node</label><input type="number" id="salloc_ntasks_per_node" min="1" value="1"></div>
<div class="c"><label>CPUs / rank</label><input type="number" id="salloc_cpus_per_task" min="1" value="1"></div>
<div class="c"><label>Time</label><input type="text" id="salloc_time" value="00:30:00"></div>
</div>
<div class="toolbar" style="margin-top:10px">
<button type="button" onclick="copySallocCmd('cm4_inter')">Copy salloc inter</button>
</div>
<div style="margin-top:6px;color:#555;font-size:12px">The helper uses the topology selected in this panel. If you checked multiple topologies above, choose one here; nodes, ranks/node, total ranks, and CPUs/rank are then auto-filled, and time defaults to 30 minutes.</div>
</div>

<div class="c panel" style="margin-top:12px">
<h4 style="margin:0 0 10px 0">Generated Scripts</h4>
<div class="toolbar" style="margin-top:8px">
<button type="submit" name="action" value="refresh">Refresh script list</button>
</div>
<div class="filters" style="grid-template-columns:repeat(7,minmax(110px,1fr))">
<div class="c"><label>Cluster</label><select id="f_cluster"><option value="">All</option>{opt_list(script_filters['cluster'])}</select></div>
<div class="c"><label>MPI</label><select id="f_mpi"><option value="">All</option>{opt_list(script_filters['mpi'])}</select></div>
<div class="c"><label>Topology</label><select id="f_topology"><option value="">All</option>{opt_list(script_filters['topology'])}</select></div>
<div class="c"><label>Face Payload / Rank</label><select id="f_size"><option value="">All</option>{opt_list(script_filters['size'])}</select></div>
<div class="c"><label>Compute</label><select id="f_compute"><option value="">All</option>{opt_list(script_filters['compute'])}</select></div>
<div class="c"><label>Run</label><select id="f_run"><option value="">All</option>{opt_list(script_filters['run'])}</select></div>
<div class="c"><label>Path contains</label><input id="f_keyword" type="text" placeholder="intelmpi / cm4_inter / ..."></div>
</div>
<div class="toolbar" style="margin-bottom:8px">
<button type="button" onclick="applyFilters()">Apply filter</button>
<button type="button" onclick="resetFilters()">Reset filter</button>
<button type="button" onclick="selectVisible(true)">Select visible</button>
<button type="button" onclick="selectVisible(false)">Clear visible</button>
<button type="button" onclick="copySelectedRunCommands()">Copy selected run commands</button>
<button type="submit" name="action" value="submit_selected">Submit selected (sbatch)</button>
<button type="submit" name="action" value="run_selected">Run selected (bash)</button>
<button type="submit" name="action" value="delete_selected" class="danger" onclick="return confirm('Delete selected scripts and empty parent directories?')">Delete selected</button>
</div>
<div style="margin:4px 0 8px 0;color:#444"><small id="visible_count">0 visible / 0 total</small></div>
<table>
<thead>
<tr>
<th style="width:40px"></th>
<th style="width:40px"></th>
<th class="col-mini">Cluster</th>
<th class="col-mini">MPI</th>
<th class="col-mini">Topology</th>
<th class="col-mini" title="Single halo-face payload estimate from grid and topology divide. Actual MPI_Isend messages are combined by partner rank and can include face, edge, and corner boxes.">Face Payload / Rank</th>
<th class="col-mini">Compute</th>
<th class="col-mini">Run</th>
<th style="width:160px"></th>
</tr>
</thead>
<tbody>
{table_html}
</tbody>
</table>
</div>

<div class="c panel" style="margin-top:12px">
<h4 style="margin:0 0 10px 0">Output</h4>
<input type="hidden" id="analysis_dir_to_delete" name="analysis_dir" value="">
<div class="toolbar" style="margin-top:8px">
<button type="submit" name="action" value="refresh_outputs">Refresh output list</button>
</div>
<div style="margin:4px 0 8px 0;color:#444"><small>Showing {len(output_dirs)} of {output_dir_count} result directories</small></div>
<div class="filters" style="grid-template-columns:repeat(6,minmax(110px,1fr))">
<div class="c"><label>Cluster</label><select id="of_cluster"><option value="">All</option>{opt_list(output_filters['cluster'])}</select></div>
<div class="c"><label>MPI</label><select id="of_mpi"><option value="">All</option>{opt_list(output_filters['mpi'])}</select></div>
<div class="c"><label>Topology</label><select id="of_topology"><option value="">All</option>{opt_list(output_filters['topology'])}</select></div>
<div class="c"><label>Face Payload / Rank</label><select id="of_size"><option value="">All</option>{opt_list(output_filters['size'])}</select></div>
<div class="c"><label>Compute</label><select id="of_compute"><option value="">All</option>{opt_list(output_filters['compute'])}</select></div>
<div class="c"><label>Run</label><select id="of_run"><option value="">All</option>{opt_list(output_filters['run'])}</select></div>
</div>
<div class="toolbar" style="margin-bottom:8px">
<button type="button" onclick="applyOutputFilters()">Apply filter</button>
<button type="button" onclick="resetOutputFilters()">Reset filter</button>
<button type="button" onclick="selectAllOutputs(true)">Select all</button>
<button type="button" onclick="selectAllOutputs(false)">Clear all</button>
<button type="button" onclick="copySelectedChartCommands()">Copy selected chart commands</button>
<button type="button" onclick="copyAverageChartCommand()">Copy average chart command</button>
<button type="button" onclick="downloadSelectedCharts()">Download selected charts</button>
<button type="submit" name="action" value="delete_selected_outputs" class="danger" onclick="return confirm('Clear selected output files? Generated run.sh scripts will be kept.')">Clear selected outputs</button>
</div>
<table>
<thead>
<tr>
<th style="width:36px"></th>
<th style="width:36px"></th>
<th class="col-mini">Cluster</th>
<th class="col-mini">MPI</th>
<th class="col-mini">Topology</th>
<th class="col-mini" title="Single halo-face payload estimate from grid and topology divide. Actual MPI_Isend messages are combined by partner rank and can include face, edge, and corner boxes.">Face Payload / Rank</th>
<th class="col-mini">Compute</th>
<th class="col-mini">Run</th>
<th>Result Dir</th>
<th class="col-mini">Output</th>
<th style="width:60px"></th>
</tr>
</thead>
<tbody>
{output_table_html}
</tbody>
</table>
</div>
</form>
{f'<div class="msg">{escape(msg)}</div>' if msg else ''}
<ul>{lis}</ul>
</div>
<script>{msgsize_js}</script>
<script>{script_js}</script>
</div></body></html>"""


def _with_cluster_profile(cfg: dict, profile: str, output_root: str | None) -> dict:
    out = dict(cfg)
    slurm = dict(cfg.get("slurm", {}))
    slurm.update(CLUSTER_PROFILES[profile])
    out["slurm"] = slurm

    if output_root:
        out["output_base"] = str(Path(output_root) / profile)
    else:
        out_base = Path(cfg.get("output_base", str(ROOT / "generated")))
        out["output_base"] = str(out_base / profile)
    return out


def _profile_topology_error(cfg: dict, profile: str) -> str | None:
    minimum_nodes = int(CLUSTER_PROFILES[profile].get("min_nodes", 1))
    invalid = [
        str(topology.get("name", "unknown"))
        for topology in cfg.get("topology", [])
        if int(topology.get("nodes", 0)) < minimum_nodes
    ]
    if not invalid:
        return None
    return (
        f"{profile} requires at least {minimum_nodes} nodes; "
        f"invalid topology selection: {', '.join(invalid)}"
    )


def run(host="127.0.0.1", port=8765, config_path=None):
    configs = _configs()
    if not configs and not config_path:
        raise RuntimeError("No config files found in config/*.yaml")

    default_cfg = Path(config_path).resolve() if config_path else configs[0]

    class Handler(BaseHTTPRequestHandler):
        def _send(self, text, code=200):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/bundle-scripts":
                raw = parse_qs(parsed.query).get("path", [""])[0]
                bundle_path = _safe_script_path(raw)
                if bundle_path is None or _script_meta(bundle_path)["grid"] != "bundle":
                    self._send("<tr><td colspan='6'><em>Bundle not found</em></td></tr>", 404)
                    return
                self._send(_bundle_detail_html(bundle_path))
                return
            if parsed.path == "/output-files":
                params = parse_qs(parsed.query)
                output_dir = _safe_generated_dir_path(params.get("path", [""])[0])
                if output_dir is None:
                    self._send("<tr><td colspan='2'><em>Output directory not found</em></td></tr>", 404)
                    return
                run = params.get("run", [""])[0]
                if run and not (RUN_DIR.fullmatch(run) or re.fullmatch(r"average_run_\d+(?:_run_\d+)*", run)):
                    self._send("<tr><td colspan='2'><em>Invalid run</em></td></tr>", 400)
                    return
                self._send(_output_detail_html(output_dir, run))
                return
            if parsed.path == "/download-charts":
                raw_paths = parse_qs(parsed.query).get("path", [])
                chart_paths: list[Path] = []
                seen: set[Path] = set()
                for raw in raw_paths:
                    image_path = _safe_chart_file(raw)
                    if image_path is not None and image_path not in seen:
                        seen.add(image_path)
                        chart_paths.append(image_path)
                if not chart_paths:
                    self._send("<h1>No charts found</h1>", 404)
                    return
                try:
                    buffer = BytesIO()
                    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
                        for image_path in chart_paths:
                            archive.writestr(_chart_download_name(image_path), image_path.read_bytes())
                    body = buffer.getvalue()
                except Exception as exc:
                    self._send(f"<h1>Download failed</h1><pre>{escape(str(exc))}</pre>", 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="comb_overlap_charts.zip"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/download-chart":
                raw = parse_qs(parsed.query).get("path", [""])[0]
                image_path = _safe_chart_file(raw)
                if image_path is None:
                    self._send("<h1>Chart not found</h1>", 404)
                    return
                try:
                    body = image_path.read_bytes()
                except Exception as exc:
                    self._send(f"<h1>Download failed</h1><pre>{escape(str(exc))}</pre>", 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Disposition", f'attachment; filename="{_chart_download_name(image_path)}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path in {"/chart", "/chart-image"}:
                raw = parse_qs(parsed.query).get("path", [""])[0]
                image_path = _safe_chart_file(raw)
                if image_path is None:
                    self._send("<h1>Chart not found</h1>", 404)
                    return
                if parsed.path == "/chart-image":
                    body = image_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                image_url = "/chart-image?path=" + quote(str(image_path))
                self._send(
                    "<!doctype html><title>Comb overlap analysis</title>"
                    "<style>body{margin:0;background:#f4f6fb;font-family:system-ui,sans-serif}"
                    "#toolbar{position:fixed;top:12px;right:12px;z-index:1;display:flex;gap:6px;padding:6px;background:#fff;border:1px solid #c7d2e6;border-radius:6px}"
                    "button{width:34px;height:30px;border:1px solid #b7c5df;border-radius:4px;background:#fff;cursor:pointer;font-size:18px}"
                    "#zoom-level{width:58px;font-size:16px}"
                    "#viewport{width:100vw;min-height:100vh;overflow:auto}#stage{min-width:100%}"
                    "#chart{display:block;width:100%;height:auto;margin:0 auto}</style>"
                    "<div id=\"toolbar\"><button type=\"button\" onclick=\"zoomBy(-0.2)\" title=\"Zoom out\">−</button>"
                    "<button id=\"zoom-level\" type=\"button\" onclick=\"resetZoom()\" title=\"Reset zoom\">40%</button>"
                    "<button type=\"button\" onclick=\"zoomBy(0.2)\" title=\"Zoom in\">+</button></div>"
                    f"<div id=\"viewport\"><div id=\"stage\"><img id=\"chart\" src=\"{escape(image_url, quote=True)}\" alt=\"MPI and mock overlap analysis\"></div></div>"
                    "<script>let zoom=.4;const chart=document.getElementById('chart'),viewport=document.getElementById('viewport'),zoomLevel=document.getElementById('zoom-level');function applyZoom(){chart.style.width=(zoom*100)+'%';zoomLevel.textContent=Math.round(zoom*100)+'%';requestAnimationFrame(()=>{viewport.scrollLeft=Math.max(0,(chart.offsetWidth-viewport.clientWidth)/2);});}"
                    "function zoomBy(delta){zoom=Math.min(3,Math.max(.4,zoom+delta));applyZoom();}function resetZoom(){zoom=.4;applyZoom();}"
                    "window.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();zoomBy(event.deltaY<0?.2:-.2);},{passive:false});applyZoom();</script>"
                )
                return
            if parsed.path == "/open":
                from urllib.parse import parse_qs as _pqs
                params = _pqs(parsed.query)
                raw = params.get("path", [""])[0]
                sp = _safe_script_path(raw)
                if sp is None:
                    body = b'{"ok":false,"error":"invalid path"}'
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                try:
                    _open_in_code(sp)
                    body = b'{"ok":true}'
                    self.send_response(200)
                except Exception as exc:
                    body = json.dumps({"ok": False, "error": str(exc)}).encode()
                    self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            cfg = load_config(default_cfg)
            self._send(_render(default_cfg, cfg))

        def do_POST(self):  # noqa: N802
            try:
                n = int(self.headers.get("Content-Length", "0"))
                data = self.rfile.read(n).decode("utf-8")
                form = parse_qs(data)
                cfg_path = Path(form.get("config", [str(default_cfg)])[0]).resolve()
                cfg = load_config(cfg_path)
                action = form.get("action", ["generate"])[0]

                selected = {
                    "mpi": set(form.get("mpi", [])),
                    "topology": set(form.get("topology", [])),
                    "grid": set(form.get("grid", [])),
                }
                selected_clusters = form.get("cluster", [])
                std_mode = action == "generate" and selected_clusters == ["cm4_std"]
                form_state = {
                    "cluster": selected_clusters,
                    "mpi": form.get("mpi", []),
                    "topology": form.get("topology", []),
                    "grid": form.get("grid", []),
                    "dry_run": "dry_run" in form,
                    "use_custom_payload": "use_custom_payload" in form,
                    "output": form.get("output", [""])[0],
                    "cycles_override": form.get("cycles_override", [""])[0],
                    "run_count": form.get("run_count", ["3"])[0],
                    "custom_grid_size": form.get("custom_grid_size", ["32_32_32"])[0],
                    "custom_ghost": form.get("custom_ghost", ["1_1_1"])[0],
                    "custom_vars": form.get("custom_vars", ["1"])[0],
                    "custom_compute_target_us": form.get("custom_compute_target_us", ["20"])[0],
                    "backend_mode": form.get("backend_mode", []),
                }

                filtered = dict(cfg)
                filtered["mpi_impl"] = {k: dict(v) for k, v in cfg.get("mpi_impl", {}).items() if k in selected["mpi"]}
                filtered["topology"] = [t for t in cfg.get("topology", []) if t.get("name") in selected["topology"]]
                if std_mode:
                    default_std_grid = cfg.get("cm4_std_grid", cfg.get("grid", {}))
                    std_grids_by_topology = cfg.get("cm4_std_grid_by_topology", {})
                    filtered["grid"] = {}
                    filtered["grid_by_topology"] = {
                        topology_name: {
                            key: dict(value)
                            for key, value in std_grids_by_topology.get(
                                topology_name, default_std_grid
                            ).items()
                        }
                        for topology_name in selected["topology"]
                    }
                else:
                    filtered["grid"] = {
                        k: dict(v)
                        for k, v in cfg.get("grid", {}).items()
                        if k in selected["grid"]
                    }
                if "use_custom_payload" in form and not std_mode:
                    custom_size = _parse_positive_triplet(form.get("custom_grid_size", [""])[0], "Grid")
                    custom_ghost = _parse_positive_triplet(form.get("custom_ghost", [""])[0], "Ghost")
                    custom_vars = int(form.get("custom_vars", ["0"])[0])
                    custom_compute_target_us = float(form.get("custom_compute_target_us", ["-1"])[0])
                    if custom_vars <= 0:
                        raise ValueError("Vars must be positive")
                    if custom_compute_target_us < 0:
                        raise ValueError("Compute target must be non-negative")
                    for topology in filtered["topology"]:
                        topology_divide = _parse_positive_triplet(str(topology.get("divide", "")), f"Topology {topology.get('name', '')} divide")
                        if any(size % parts for size, parts in zip(custom_size, topology_divide)):
                            raise ValueError(f"Grid dimensions must be divisible by topology {topology.get('name', '')} divide")
                    filtered["grid"] = {
                        "custom": {
                            "label": "Custom payload",
                            "size": "_".join(str(value) for value in custom_size),
                            "ghost": "_".join(str(value) for value in custom_ghost),
                            "vars": custom_vars,
                            "compute_target_us": custom_compute_target_us,
                        }
                    }
                if action == "generate" and "cm4_std" in selected_clusters and not std_mode:
                    self._send(_render(
                        cfg_path,
                        cfg,
                        msg="Select cm4_std or cm4_inter, not both in one generation.",
                        selected_clusters=selected_clusters,
                        form_state=form_state,
                    ))
                    return
                if action == "generate" and not (
                    filtered["grid"] or filtered.get("grid_by_topology")
                ):
                    self._send(_render(
                        cfg_path,
                        cfg,
                        msg="Select a preset payload or edit the Custom grid fields.",
                        selected_clusters=selected_clusters,
                        form_state=form_state,
                    ))
                    return
                cycles_override_text = "" if std_mode else form.get("cycles_override", [""])[0].strip()
                if cycles_override_text:
                    cycles_override = int(cycles_override_text)
                    if cycles_override <= 0:
                        raise ValueError("Cycles override must be a positive integer")
                    for grid_config in filtered["grid"].values():
                        grid_config["cycles"] = cycles_override
                run_count = 3 if std_mode else int(form.get("run_count", ["3"])[0])
                if run_count <= 0:
                    raise ValueError("Runs to generate must be a positive integer")
                # Always keep all compute modes to generate paired overlap cases.
                if cfg.get("compute_mode") is not None:
                    backend_modes = form.get("backend_mode", [])
                    if not backend_modes:
                        raise ValueError("Select at least one backend run")
                    if any(mode not in {"both", "mpi_only", "mock_only"} for mode in backend_modes):
                        raise ValueError("Invalid communication backend mode")
                    filtered["compute_mode"] = dict(cfg.get("compute_mode", {}))

                out = "" if std_mode else form.get("output", [""])[0].strip()
                if out:
                    filtered["output_base"] = out

                dry_run = "dry_run" in form
                if action == "refresh":
                    self._send(_render(cfg_path, cfg, msg="Script list refreshed.", selected_clusters=selected_clusters))
                    return

                if action == "refresh_outputs":
                    self._send(_render(cfg_path, cfg, msg="Output list refreshed.", selected_clusters=selected_clusters))
                    return

                if action == "delete_chart":
                    analysis_dir = _safe_analysis_dir(form.get("analysis_dir", [""])[0])
                    if analysis_dir is None:
                        self._send(_render(cfg_path, cfg, msg="Chart was not found or is not eligible for deletion.", selected_clusters=selected_clusters))
                        return
                    try:
                        _clear_analysis_run(analysis_dir, "run")
                    except Exception as exc:
                        self._send(_render(cfg_path, cfg, msg=f"Failed to delete chart: {exc}", selected_clusters=selected_clusters))
                        return
                    self._send(_render(cfg_path, cfg, msg="Deleted chart, CSV, and note; raw results were kept.", selected_clusters=selected_clusters))
                    return

                if action == "delete_selected_outputs":
                    selected_dirs = form.get("output_dir", [])
                    if not selected_dirs:
                        self._send(_render(cfg_path, cfg, msg="No output directories selected.", selected_clusters=selected_clusters))
                        return
                    lines = []
                    ok = 0
                    base = (ROOT / "generated").resolve()
                    for p in selected_dirs:
                        if p.startswith("analysis-run:"):
                            _, run, raw_dir = p.split(":", 2)
                            analysis_dir = _safe_generated_dir_path(raw_dir)
                            if analysis_dir is None or analysis_dir.name != "analysis":
                                lines.append(f"refused {run}: invalid analysis directory")
                                continue
                            try:
                                removed = _clear_analysis_run(analysis_dir, run)
                                if not removed:
                                    lines.append(f"no files found for {run}")
                                    continue
                                lines.append(f"cleared {run}: {', '.join(path.name for path in removed)}")
                                ok += 1
                            except Exception as exc:
                                lines.append(f"failed {run}: {exc}")
                            continue
                        out_dir = _safe_generated_dir_path(p)
                        if out_dir is None:
                            lines.append(f"refused {Path(p).name}: invalid output directory")
                            continue
                        try:
                            parent = out_dir.parent
                            removed_dir = _clear_output_dir(out_dir)
                            if removed_dir:
                                while parent != base and parent.exists() and not any(parent.iterdir()):
                                    parent.rmdir()
                                    parent = parent.parent
                            lines.append(f"cleared {out_dir.name}; run.sh kept" if not removed_dir else f"cleared {out_dir.name}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {Path(p).name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Cleared {ok}/{len(selected_dirs)} output directories; generated scripts were kept.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "submit_selected":
                    selected_scripts = form.get("script", [])
                    if not selected_scripts:
                        self._send(_render(cfg_path, cfg, msg="No scripts selected.", selected_clusters=selected_clusters))
                        return
                    lines = []
                    ok = 0
                    for p in selected_scripts:
                        sp = _safe_script_path(p)
                        if sp is None:
                            lines.append(f"refused {Path(p).name}: outside generated/")
                            continue
                        if not any(line.startswith("#SBATCH") for line in sp.read_text(errors="ignore").splitlines()):
                            lines.append(f"refused {sp.name}: bundle child scripts require an existing allocation")
                            continue
                        try:
                            job_id = sbatch(sp)
                            lines.append(f"submitted {sp.name} -> job {job_id}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {sp.name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Submitted {ok}/{len(selected_scripts)} scripts.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "run_selected":
                    selected_scripts = form.get("script", [])
                    if not selected_scripts:
                        self._send(_render(cfg_path, cfg, msg="No scripts selected.", selected_clusters=selected_clusters))
                        return
                    lines = []
                    ok = 0
                    for p in selected_scripts:
                        sp = _safe_script_path(p)
                        if sp is None:
                            lines.append(f"refused {Path(p).name}: outside generated/")
                            continue
                        try:
                            proc = subprocess.Popen(["bash", sp.name], cwd=str(sp.parent))
                            lines.append(f"started {sp.name} pid={proc.pid}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {sp.name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Started {ok}/{len(selected_scripts)} scripts.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "delete_selected":
                    selected_scripts = form.get("script", [])
                    if not selected_scripts:
                        self._send(_render(cfg_path, cfg, msg="No scripts selected.", selected_clusters=selected_clusters))
                        return
                    lines = []
                    ok = 0
                    base = (ROOT / "generated").resolve()
                    for p in selected_scripts:
                        sp = _safe_script_path(p)
                        if sp is None:
                            lines.append(f"refused {Path(p).name}: outside generated/")
                            continue
                        try:
                            parent = sp.parent
                            run_dir = parent
                            sp.unlink()
                            while parent != base and parent.exists() and not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent
                            remove_orphaned_default_run_note(run_dir)
                            lines.append(f"deleted {sp.name}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {Path(p).name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Deleted {ok}/{len(selected_scripts)} scripts.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "generate":
                    if not selected_clusters:
                        self._send(_render(cfg_path, cfg, msg="Select at least one cluster profile.", selected_clusters=[], form_state=form_state))
                        return

                    all_scripts = []
                    lines = []
                    for profile in selected_clusters:
                        if profile not in CLUSTER_PROFILES:
                            continue
                        cluster_cfg = _with_cluster_profile(filtered, profile, out or None)
                        topology_error = _profile_topology_error(cluster_cfg, profile)
                        if topology_error:
                            lines.append(topology_error)
                            continue
                        if profile == "cm4_std":
                            bundle_jobs = []
                            child_scripts = []
                            profile_bundles = []
                            seed_jobs = expand_matrix(cluster_cfg)
                            if not seed_jobs:
                                lines.append(f"{profile}: no jobs")
                                continue
                            first_run_number = _next_run_number(seed_jobs)
                            for repetition in range(run_count):
                                run_number = first_run_number + repetition
                                for backend_mode in backend_modes:
                                    backend_cfg = copy.deepcopy(cluster_cfg)
                                    backend_cfg["compute_mode"] = {
                                        name: {**mode, "backend_mode": backend_mode}
                                        for name, mode in cluster_cfg.get("compute_mode", {}).items()
                                    }
                                    jobs = expand_matrix(backend_cfg)
                                    run_dir = _apply_run_dir(jobs, run_number, backend_mode)
                                    scripts = [
                                        generate_job(
                                            job,
                                            dry_run=dry_run,
                                            include_slurm_directives=False,
                                        )
                                        for job in jobs
                                    ]
                                    note_paths = create_run_notes(jobs) if not dry_run else []
                                    bundle_jobs.extend(jobs)
                                    child_scripts.extend(scripts)
                                    lines.append(f"{profile}: prepared {len(scripts)} bundled experiments in {run_dir}")
                                    lines.extend(f"notes: {path}" for path in note_paths)

                            grouped: dict[tuple[str, str], tuple[list[dict], list[Path]]] = {}
                            for job, script in zip(bundle_jobs, child_scripts):
                                key = (job["mpi"]["name"], job["topology"]["name"])
                                group_jobs, group_scripts = grouped.setdefault(key, ([], []))
                                group_jobs.append(job)
                                group_scripts.append(script)
                            for key, (group_jobs, group_scripts) in grouped.items():
                                bundle = generate_bundle(group_jobs, group_scripts, dry_run=dry_run)
                                all_scripts.append(bundle)
                                profile_bundles.append(bundle)
                                lines.append(f"{profile}: generated bundle {key[0]}/{key[1]} with {len(group_scripts)} experiments")
                            if not dry_run:
                                write_submit_all(profile_bundles)
                            continue
                        profile_scripts = []
                        seed_jobs = expand_matrix(cluster_cfg)
                        if not seed_jobs:
                            lines.append(f"{profile}: no jobs")
                            continue
                        first_run_number = _next_run_number(seed_jobs)
                        for repetition in range(run_count):
                            run_number = first_run_number + repetition
                            for backend_mode in backend_modes:
                                backend_cfg = copy.deepcopy(cluster_cfg)
                                backend_cfg["compute_mode"] = {
                                    name: {**mode, "backend_mode": backend_mode}
                                    for name, mode in cluster_cfg.get("compute_mode", {}).items()
                                }
                                jobs = expand_matrix(backend_cfg)
                                run_dir = _apply_run_dir(jobs, run_number, backend_mode)
                                scripts = generate_all(jobs, dry_run=dry_run)
                                note_paths = create_run_notes(jobs) if not dry_run else []
                                all_scripts.extend(scripts)
                                profile_scripts.extend(scripts)
                                lines.append(f"{profile}: generated {len(scripts)} scripts in {run_dir}")
                                lines.extend(f"notes: {path}" for path in note_paths)
                        if not dry_run:
                            write_submit_all(profile_scripts)

                    if not all_scripts:
                        self._send(_render(cfg_path, cfg, msg="No jobs to generate. Please adjust selections.", items=lines, selected_clusters=selected_clusters, form_state=form_state))
                        return

                    msg = f"Generated {len(all_scripts)} scripts across {run_count} run(s) ({'dry-run' if dry_run else 'written'}) for {', '.join(selected_clusters)}."
                    details = lines + [str(x) for x in all_scripts[:40]]
                    if len(all_scripts) > 40:
                        details.append(f"... and {len(all_scripts) - 40} more")
                    self._send(_render(cfg_path, cfg, msg=msg, items=details, selected_clusters=selected_clusters, form_state=form_state))
                    return

                self._send(_render(cfg_path, cfg, msg=f"Unknown action: {action}", selected_clusters=selected_clusters))
            except Exception as exc:
                self._send(f"<h1>Error</h1><pre>{escape(str(exc))}</pre>", 500)

        def log_message(self, fmt, *args):
            return

    print(f"[mpi_lab web gui] Open http://{host}:{int(port)}")
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()
