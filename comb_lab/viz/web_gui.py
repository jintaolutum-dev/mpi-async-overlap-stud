from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import parse_qs, quote, urlparse
import json

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from core.generator import generate_all
from core.matrix import expand_matrix, load_config
from core.scheduler import sbatch

CLUSTER_PROFILES = {
    "cm4_std": {
        "clusters": "cm4",
        "partition": "cm4_std",
        "qos": "cm4_std",
    },
    "cm4_inter": {
        "clusters": "inter",
        "partition": "cm4_inter",
        "qos": "cm4_inter",
    },
}


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
    if candidate is None or candidate.name != "analysis":
        return None
    if not (candidate / "overlap_metrics.png").is_file():
        return None
    return candidate


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
    scripts = [p for p in base_dir.rglob("run.sh") if p.is_file()]
    scripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return scripts


def _is_output_file(path: Path) -> bool:
    name = path.name
    if name in {"run.sh", "submit_all.sh", "comb"}:
        return False
    if name.startswith("openmpi_hosts."):
        return False
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

    grouped: dict[Path, dict] = {}
    for path in base_dir.rglob("*"):
        if not path.is_file() or not _is_output_file(path):
            continue
        if "alloc_logs" in path.parts:
            continue

        parent = path.parent
        entry = grouped.setdefault(parent, {"dir": parent, "count": 0, "latest_mtime": 0.0, "files": []})
        entry["count"] += 1
        entry["files"].append(path)
        try:
            entry["latest_mtime"] = max(entry["latest_mtime"], path.stat().st_mtime)
        except Exception:
            pass

    rows = list(grouped.values())
    for item in rows:
        item["files"].sort(key=lambda p: p.stat().st_mtime, reverse=True)
    rows.sort(key=lambda item: item["latest_mtime"], reverse=True)
    return rows


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
    if script_path is None or not script_path.is_file():
        return fallback

    try:
        settings = {}
        for line in script_path.read_text(errors="ignore").splitlines():
            for key in ("GRID_SIZE", "GHOST", "VARS"):
                prefix = f"{key}="
                if line.startswith(prefix):
                    settings[key] = line[len(prefix):].strip().strip('"')
    except OSError:
        return fallback

    size = settings.get("GRID_SIZE")
    ghost = settings.get("GHOST")
    variables = settings.get("VARS")
    labels = {
        ("32_32_32", "1_1_1", "1"): "small",
        ("128_128_128", "4_4_4", "3"): "medium",
        ("256_256_256", "4_4_4", "3"): "large",
        ("512_512_512", "8_8_8", "3"): "big (legacy)",
    }
    label = labels.get((size, ghost, variables), fallback)
    if not all((size, ghost, variables)):
        return label
    return f"{label} ({size}, ghost={ghost}, vars={variables})"


def _script_meta(path: Path) -> dict:
    rel = path.relative_to(ROOT)
    cluster = _cluster_for_script(path)
    mpi = "-"
    topology = "-"
    grid = "-"
    compute = "-"

    # Supported shapes:
    # generated/<cluster>/<mpi>/<topology>/<grid>[/<compute>]/run.sh
    # generated/<mpi>/<topology>/<grid>[/<compute>]/run.sh
    try:
        sub = path.relative_to(ROOT / "generated")
        parts = list(sub.parts)
        if parts and parts[-1] == "run.sh":
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

    size_label = _message_size_label(path / "run.sh", grid)

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


def _render(cfg_path, cfg, msg="", items=None, selected_clusters=None):
    items = items or []
    selected_clusters = selected_clusters or []
    candidates = _configs()
    scripts = _scan_scripts(ROOT / "generated")[:300]
    output_dirs = _scan_output_dirs(ROOT / "generated")[:300]
    grid_order = {"small_msg": 0, "small": 0, "medium": 1, "large": 2, "big": 3}
    mpi_order = {"openmpi": 0, "intelmpi": 1, "mpich": 2}
    output_order = {"analysis": 0, "midcomm": 1, "no_midcomm": 2}
    output_dirs.sort(
        key=lambda item: (
            _output_meta(item["dir"])["cluster"],
            mpi_order.get(_output_meta(item["dir"])["mpi"], 99),
            _output_meta(item["dir"])["mpi"],
            _output_meta(item["dir"])["topology"],
            grid_order.get(_output_meta(item["dir"])["grid"], 99),
            _output_meta(item["dir"])["grid"],
            output_order.get(item["dir"].name, 3),
            item["dir"].name,
        )
    )
    output_dir_set = {item["dir"].resolve() for item in output_dirs}

    def ck(name):
        parts = []
        for x in name_map[name]:
            checked = ""
            if name == "cluster":
                checked = "checked" if x in selected_clusters else ""
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
        for gkey in sorted_grids:
            grid_cfg = cfg.get("grid", {}).get(gkey, {})
            grid_size = str(grid_cfg.get("size", "?"))
            ghost = str(grid_cfg.get("ghost", "?"))
            variables = str(grid_cfg.get("vars", "?"))
            parts.append(
                f'<label>'
                f'<input type="checkbox" name="grid" value="{escape(gkey)}"> '
                f'<span>{escape(str(grid_cfg.get("label", gkey)))}</span>'
                f' <span style="color:#555;font-size:11px">'
                f'(grid={escape(grid_size)}, ghost={escape(ghost)}, vars={escape(variables)}; '
                f'<span id="gsize_{escape(gkey)}"></span>)</span>'
                f'</label><br>'
            )
        return "\n".join(parts) or "<em>None</em>"

    msgsize_js = f"""const GRID_DATA = {grid_json};
const TOPO_DATA = {topo_json};
const SALLOC_DEFAULT_TIME = "00:30:00";

function fmtBytes(n) {{
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
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
        el.textContent = '(X=' + fmtBytes(faceBytes.X) + ', Y=' + fmtBytes(faceBytes.Y) + ', Z=' + fmtBytes(faceBytes.Z) + ')';
    }}
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
    cb.addEventListener('change', () => {{
        refreshSallocTopologyChoices();
        updateSallocDefaults();
    }});
}});
document.getElementById('salloc_topology')?.addEventListener('change', updateSallocDefaults);
document.getElementById('salloc_nodes')?.addEventListener('input', updateSallocTaskCount);
document.getElementById('salloc_ntasks_per_node')?.addEventListener('input', updateSallocTaskCount);
updateMsgSizeLabels();
refreshSallocTopologyChoices();
updateSallocDefaults();"""

    opts = []
    for p in candidates:
        sel = "selected" if p == cfg_path else ""
        opts.append(f'<option value="{escape(str(p))}" {sel}>{escape(str(p))}</option>')

    lis = "\n".join(f"<li>{escape(x)}</li>" for x in items)

    script_filters = {
        "cluster": sorted({m["cluster"] for m in (_script_meta(p) for p in scripts)}),
        "mpi": sorted({m["mpi"] for m in (_script_meta(p) for p in scripts)}),
        "topology": sorted({m["topology"] for m in (_script_meta(p) for p in scripts)}),
        "size": sorted({m["size"] for m in (_script_meta(p) for p in scripts)}),
        "compute": sorted({m["compute"] for m in (_script_meta(p) for p in scripts)}),
    }

    def opt_list(values):
        return "".join([f'<option value="{escape(v)}">{escape(v)}</option>' for v in values if v])

    table_rows = []
    for p in scripts:
        meta = _script_meta(p)
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
        table_rows.append(
            f"<tr class='{row_class}'{row_title}"
            f" data-cluster='{escape(meta['cluster'])}'"
            f" data-mpi='{escape(meta['mpi'])}'"
            f" data-topology='{escape(meta['topology'])}'"
            f" data-size='{escape(meta['size'])}'"
            f" data-compute='{escape(meta['compute'])}'"
            f" data-rel='{escape(meta['rel'])}'>"
            "<td></td>"
            f'<td><input type="checkbox" name="script" value="{escape(meta["abs"])}"></td>'
            f"<td>{escape(meta['cluster'])}</td>"
            f"<td>{escape(meta['mpi'])}</td>"
            f"<td>{escape(meta['topology'])}</td>"
            f"<td>{escape(meta['size'])}</td>"
            f"<td>{escape(meta['compute'])}</td>"
            f"<td style='white-space:nowrap'><button type='button' class='open-btn' onclick=\"openInCode('{escape(meta['abs'])}')\" title='Open in VS Code'>&#128065;</button>&nbsp;<button type='button' class='copy-btn' onclick=\"copyPath('{escape(meta['abs'])}')\" title='Copy script path'>📋</button>{submit_button}</td>"
            "</tr>"
        )
    table_html = "\n".join(table_rows) or "<tr><td colspan='8'><em>No generated scripts yet.</em></td></tr>"

    output_rows = []
    for idx, item in enumerate(output_dirs):
        meta = _output_meta(item["dir"])
        output_row_class = "output-row analysis-output" if meta["compute"] == "analysis" else "output-row"
        view_chart_button = (
            f'<button type="button" class="open-btn" onclick="openChart(\'{escape(meta["abs"])}\')" '
            f'title="Open overlap chart in a new tab">chart</button>&nbsp;'
            if meta["compute"] == "analysis" and (item["dir"] / "overlap_metrics.png").is_file() else ""
        )
        delete_chart_button = (
            f'<button type="submit" name="action" value="delete_chart" '
            f'onclick="setChartToDelete(\'{escape(meta["abs"])}\'); return confirm(\'Delete only overlap_metrics.png? Results and CSV will be kept.\')" '
            f'title="Delete chart PNG only">&#128465;</button>&nbsp;'
            if meta["compute"] == "analysis" and (item["dir"] / "overlap_metrics.png").is_file() else ""
        )
        analysis_parent = item["dir"].parent
        midcomm_dir = analysis_parent / "midcomm"
        no_midcomm_dir = analysis_parent / "no_midcomm"
        chart_exists = (analysis_parent / "analysis" / "overlap_metrics.png").is_file()
        can_analyze = (
            item["dir"].name in {"midcomm", "no_midcomm"}
            and midcomm_dir.is_dir()
            and no_midcomm_dir.is_dir()
            and any(midcomm_dir.glob("Comb_*_summary.csv"))
            and any(no_midcomm_dir.glob("Comb_*_summary.csv"))
        )
        chart_button_class = "copy-btn chart-ready" if chart_exists else "copy-btn"
        chart_button_title = "Copy command to regenerate chart" if chart_exists else "Copy paired MPI and mock analysis command"
        chart_button = (
            f'<button type="button" class="{chart_button_class}" '
            f'onclick="copyAnalyzeCommand(\'{escape(str(analysis_parent))}\')" '
            f'title="{chart_button_title}">chart</button>&nbsp;'
            if can_analyze else ""
        )
        detail_rows = []
        for child in item["files"]:
            child_rel = child.relative_to(ROOT)
            detail_rows.append(
                "<tr>"
                f"<td style='padding-left:18px'>{escape(child.name)}</td>"
                f"<td style='white-space:nowrap'><button type='button' class='open-btn' onclick=\"openInCode('{escape(str(child))}')\" title='Open output file'>&#128065;</button>&nbsp;<button type='button' class='copy-btn' onclick=\"copyPath('{escape(str(child))}')\" title='Copy output file path'>📋</button></td>"
                "</tr>"
            )
        detail_table_html = "".join(detail_rows) or "<tr><td colspan='2'><em>No files</em></td></tr>"
        output_rows.append(
            f"<tr class='{output_row_class}' data-output-id='out_{idx}' data-compute='{escape(meta['compute'])}'>"
            f"<td><button type='button' class='copy-btn' onclick=\"toggleOutputRow('out_{idx}')\" id='toggle_out_{idx}' title='Expand output files'>+</button></td>"
            f'<td><input type="checkbox" name="output_dir" value="{escape(meta["abs"])}"></td>'
            f"<td>{escape(meta['cluster'])}</td>"
            f"<td>{escape(meta['mpi'])}</td>"
            f"<td>{escape(meta['topology'])}</td>"
            f"<td>{escape(meta['size'])}</td>"
            f"<td>{escape(meta['compute'])}</td>"
            f"<td>{escape(meta['rel'])}</td>"
            f"<td>{item['count']} files</td>"
            f"<td style='white-space:nowrap'>{chart_button}{view_chart_button}{delete_chart_button}<button type='button' class='open-btn' onclick=\"openInCode('{escape(meta['abs'])}')\" title='Open result directory'>&#128065;</button>&nbsp;<button type='button' class='copy-btn' onclick=\"copyPath('{escape(meta['abs'])}')\" title='Copy result directory'>📋</button></td>"
            "</tr>"
            f"<tr class='output-detail-row row-hidden' id='detail_out_{idx}'>"
            "<td></td>"
            "<td colspan='9' style='background:#fbfcff'>"
            "<table style='width:100%;border-collapse:collapse'>"
            "<thead><tr><th style='text-align:left'>Files</th><th style='width:88px'></th></tr></thead>"
            f"<tbody>{detail_table_html}</tbody>"
            "</table>"
            "</td>"
            "</tr>"
        )
    output_table_html = "\n".join(output_rows) or "<tr><td colspan='10'><em>No output directories yet.</em></td></tr>"

    script_js = """
const scriptRows = Array.from(document.querySelectorAll('tr.script-row'));
const outputRows = Array.from(document.querySelectorAll('tr.output-row'));
const scrollPositionKey = 'mpi_lab_scroll_position';
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
});

function isVisibleRow(row) {
    return !row.classList.contains('row-hidden');
}

function setVisibleCount() {
    const visible = scriptRows.filter(isVisibleRow).length;
    const total = scriptRows.length;
    const el = document.getElementById('visible_count');
    if (el) el.textContent = visible + ' visible / ' + total + ' total';
}

function applyFilters() {
    const fc = document.getElementById('f_cluster')?.value || '';
    const fm = document.getElementById('f_mpi')?.value || '';
    const ft = document.getElementById('f_topology')?.value || '';
    const fs = document.getElementById('f_size')?.value || '';
    const fcp = document.getElementById('f_compute')?.value || '';
    const fk = (document.getElementById('f_keyword')?.value || '').trim().toLowerCase();

    for (const row of scriptRows) {
        const pass =
            (!fc || row.dataset.cluster === fc) &&
            (!fm || row.dataset.mpi === fm) &&
            (!ft || row.dataset.topology === ft) &&
            (!fs || row.dataset.size === fs) &&
            (!fcp || row.dataset.compute === fcp) &&
            (!fk || (row.dataset.rel || '').toLowerCase().includes(fk));
        row.classList.toggle('row-hidden', !pass);
    }
    setVisibleCount();
}

function resetFilters() {
    ['f_cluster', 'f_mpi', 'f_topology', 'f_size', 'f_compute', 'f_keyword'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = '';
    });
    applyFilters();
}

function selectVisible(state) {
    for (const row of scriptRows) {
        if (!isVisibleRow(row)) continue;
        const box = row.querySelector('input[name="script"]');
        if (box) box.checked = state;
    }
}

document.getElementById('select_all_box')?.addEventListener('change', (e) => {
    const state = !!e.target.checked;
    for (const row of scriptRows) {
        const box = row.querySelector('input[name="script"]');
        if (box) box.checked = state;
    }
});

for (const id of ['f_cluster', 'f_mpi', 'f_topology', 'f_size', 'f_compute']) {
    document.getElementById(id)?.addEventListener('change', applyFilters);
}
document.getElementById('f_keyword')?.addEventListener('input', applyFilters);

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
        const box = row.querySelector('input[name="output_dir"]');
        if (box) box.checked = state;
    }
}

function filterOutputs(compute) {
    for (const row of outputRows) {
        const show = !compute || row.dataset.compute === compute;
        row.classList.toggle('row-hidden', !show);
        const detail = document.getElementById('detail_' + row.dataset.outputId);
        if (detail) detail.classList.add('row-hidden');
        const toggle = document.getElementById('toggle_' + row.dataset.outputId);
        if (toggle) toggle.textContent = '+';
    }
}

function toggleOutputRow(rowId) {
    const row = document.getElementById('detail_' + rowId);
    const btn = document.getElementById('toggle_' + rowId);
    if (!row || !btn) return;
    const hidden = row.classList.toggle('row-hidden');
    btn.textContent = hidden ? '+' : '-';
    btn.title = hidden ? 'Expand output files' : 'Collapse output files';
}

document.getElementById('select_all_outputs_box')?.addEventListener('change', (e) => {
    selectAllOutputs(!!e.target.checked);
});

applyFilters();

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

function copyAnalyzeCommand(parent) {
    const quote = (value) => "'" + String(value).replace(/'/g, "'\\''") + "'";
    {
        const root = '/dss/dsshome1/08/ge63neh2/comb_lab';
        const portableCommand = quote(root + '/venv/bin/python') + ' ' + quote(root + '/analyze_overlap.py') +
            ' --midcomm-dir ' + quote(parent + '/midcomm') +
            ' --no-midcomm-dir ' + quote(parent + '/no_midcomm') +
            ' --output-dir ' + quote(parent + '/analysis');
        navigator.clipboard.writeText(portableCommand).then(() => {
            alert('Analysis command copied to clipboard.');
        }).catch(() => {
            prompt('Copy and run this command:', portableCommand);
        });
        return;
    }
    const command = './venv/bin/python analyze_overlap.py \\\n+  --midcomm-dir ' + quote(parent + '/midcomm') + ' \\\n+  --no-midcomm-dir ' + quote(parent + '/no_midcomm') + ' \\\n+  --output-dir ' + quote(parent + '/analysis');
    navigator.clipboard.writeText(command).then(() => {
        alert('Analysis command copied to clipboard.');
    }).catch(() => {
        prompt('Copy and run this command:', command);
    });
}

function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
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

function copyPath(path) {
    navigator.clipboard.writeText(path).then(() => {
        alert('Copied: ' + path);
    }).catch(() => {
        alert('Failed to copy');
    });
}
"""

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
.filters{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:8px;margin:10px 0}}
.filters .c{{padding:6px}}
.filters label{{display:block;font-size:12px;color:#444;margin-bottom:4px}}
.filters select,.filters input{{width:100%;box-sizing:border-box}}
.script-row.has-output{{opacity:0.42;transition:opacity .15s ease}}
.script-row.has-output:hover{{opacity:0.76}}
.output-row.analysis-output td{{background:#e8f6ea}}
.output-row.analysis-output:hover td{{background:#d9f0dd}}
.row-hidden{{display:none}}
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
<label><input type="checkbox" name="dry_run" value="1"> Dry run</label>
<label style="flex:1 1 360px">Output override <input type="text" name="output" style="width:100%;box-sizing:border-box;margin-top:4px"></label>
</div>
<div class="g" style="margin-top:10px">
<div class="c"><h4>Cluster</h4>{ck('cluster')}</div>
<div class="c"><h4>MPI</h4>{ck('mpi')}</div>
<div class="c"><h4>Topology</h4>{ck('topology')}</div>
<div class="c"><h4>Msg Size</h4>{ck_grid()}</div>
<div class="c" style="grid-column:1/-1"><h4>Test Cases</h4><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0 14px">{case_box_html}</div></div>
</div>
<div class="toolbar" style="margin-top:12px">
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
<div class="filters">
<div class="c"><label>Cluster</label><select id="f_cluster"><option value="">All</option>{opt_list(script_filters['cluster'])}</select></div>
<div class="c"><label>MPI</label><select id="f_mpi"><option value="">All</option>{opt_list(script_filters['mpi'])}</select></div>
<div class="c"><label>Topology</label><select id="f_topology"><option value="">All</option>{opt_list(script_filters['topology'])}</select></div>
<div class="c"><label>Msg Size</label><select id="f_size"><option value="">All</option>{opt_list(script_filters['size'])}</select></div>
<div class="c"><label>Compute</label><select id="f_compute"><option value="">All</option>{opt_list(script_filters['compute'])}</select></div>
<div class="c"><label>Path contains</label><input id="f_keyword" type="text" placeholder="intelmpi / cm4_inter / ..."></div>
</div>
<div class="toolbar" style="margin-bottom:8px">
<button type="button" onclick="applyFilters()">Apply filter</button>
<button type="button" onclick="resetFilters()">Reset filter</button>
<button type="button" onclick="selectVisible(true)">Select visible</button>
<button type="button" onclick="selectVisible(false)">Clear visible</button>
<label style="margin-left:8px"><input type="checkbox" id="select_all_box"> Select all rows</label>
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
<th class="col-mini">Msg Size</th>
<th class="col-mini">Compute</th>
<th style="width:160px"></th>
</tr>
</thead>
<tbody>
{table_html}
</tbody>
</table>
<div class="toolbar" style="margin-top:10px">
<button type="submit" name="action" value="submit_selected">Submit selected (sbatch)</button>
<button type="submit" name="action" value="run_selected">Run selected (bash)</button>
</div>
</div>

<div class="c panel" style="margin-top:12px">
<h4 style="margin:0 0 10px 0">Output</h4>
<input type="hidden" id="analysis_dir_to_delete" name="analysis_dir" value="">
<div class="toolbar" style="margin-top:8px">
<button type="submit" name="action" value="refresh_outputs">Refresh output list</button>
</div>
<div style="margin:4px 0 8px 0;color:#444"><small>{len(output_dirs)} result directories</small></div>
<div class="toolbar" style="margin-bottom:8px">
<button type="button" onclick="filterOutputs('analysis')">Show analysis only</button>
<button type="button" onclick="filterOutputs('')">Show all</button>
<button type="button" onclick="selectAllOutputs(true)">Select all</button>
<button type="button" onclick="selectAllOutputs(false)">Clear all</button>
<label style="margin-left:8px"><input type="checkbox" id="select_all_outputs_box"> Select all rows</label>
<button type="submit" name="action" value="delete_selected_outputs" class="danger" onclick="return confirm('Delete selected result directories, including all logs and analysis files?')">Delete selected result dirs</button>
</div>
<table>
<thead>
<tr>
<th style="width:36px"></th>
<th style="width:36px"></th>
<th class="col-mini">Cluster</th>
<th class="col-mini">MPI</th>
<th class="col-mini">Topology</th>
<th class="col-mini">Msg Size</th>
<th class="col-mini">Compute</th>
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
            if parsed.path in {"/chart", "/chart-image"}:
                raw = parse_qs(parsed.query).get("path", [""])[0]
                analysis_dir = _safe_analysis_dir(raw)
                if analysis_dir is None:
                    self._send("<h1>Chart not found</h1>", 404)
                    return
                image_path = analysis_dir / "overlap_metrics.png"
                if parsed.path == "/chart-image":
                    body = image_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                image_url = "/chart-image?path=" + quote(str(analysis_dir))
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

                filtered = dict(cfg)
                filtered["mpi_impl"] = {k: dict(v) for k, v in cfg.get("mpi_impl", {}).items() if k in selected["mpi"]}
                filtered["topology"] = [t for t in cfg.get("topology", []) if t.get("name") in selected["topology"]]
                filtered["grid"] = {k: v for k, v in cfg.get("grid", {}).items() if k in selected["grid"]}
                # Always keep all compute modes to generate paired overlap cases.
                if cfg.get("compute_mode") is not None:
                    filtered["compute_mode"] = dict(cfg.get("compute_mode", {}))

                out = form.get("output", [""])[0].strip()
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
                        (analysis_dir / "overlap_metrics.png").unlink()
                    except Exception as exc:
                        self._send(_render(cfg_path, cfg, msg=f"Failed to delete chart: {exc}", selected_clusters=selected_clusters))
                        return
                    self._send(_render(cfg_path, cfg, msg="Deleted chart PNG; results and CSV were kept.", selected_clusters=selected_clusters))
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
                        out_dir = _safe_generated_dir_path(p)
                        if out_dir is None:
                            lines.append(f"refused {Path(p).name}: invalid output directory")
                            continue
                        try:
                            parent = out_dir.parent
                            shutil.rmtree(out_dir)
                            while parent != base and parent.exists() and not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent
                            lines.append(f"deleted {out_dir.name}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {Path(p).name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Deleted {ok}/{len(selected_dirs)} output directories.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "submit_selected":
                    selected_scripts = form.get("script", [])
                    if not selected_scripts:
                        self._send(_render(cfg_path, cfg, msg="No scripts selected.", selected_clusters=selected_clusters))
                        return
                    lines = []
                    ok = 0
                    for p in selected_scripts:
                        sp = Path(p)
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
                        sp = Path(p)
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
                            sp.unlink()
                            while parent != base and parent.exists() and not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent
                            lines.append(f"deleted {sp.name}")
                            ok += 1
                        except Exception as exc:
                            lines.append(f"failed {Path(p).name}: {exc}")
                    self._send(_render(cfg_path, cfg, msg=f"Deleted {ok}/{len(selected_scripts)} scripts.", items=lines, selected_clusters=selected_clusters))
                    return

                if action == "generate":
                    if not selected_clusters:
                        self._send(_render(cfg_path, cfg, msg="Select at least one cluster profile.", selected_clusters=[]))
                        return

                    all_scripts = []
                    lines = []
                    for profile in selected_clusters:
                        if profile not in CLUSTER_PROFILES:
                            continue
                        cluster_cfg = _with_cluster_profile(filtered, profile, out or None)
                        jobs = expand_matrix(cluster_cfg)
                        if not jobs:
                            lines.append(f"{profile}: no jobs")
                            continue
                        scripts = generate_all(jobs, dry_run=dry_run)
                        all_scripts.extend(scripts)
                        lines.append(f"{profile}: generated {len(scripts)} scripts")

                    if not all_scripts:
                        self._send(_render(cfg_path, cfg, msg="No jobs to generate. Please adjust selections.", items=lines, selected_clusters=selected_clusters))
                        return

                    msg = f"Generated {len(all_scripts)} scripts ({'dry-run' if dry_run else 'written'}) across {', '.join(selected_clusters)}."
                    details = lines + [str(x) for x in all_scripts[:40]]
                    if len(all_scripts) > 40:
                        details.append(f"... and {len(all_scripts) - 40} more")
                    self._send(_render(cfg_path, cfg, msg=msg, items=details, selected_clusters=selected_clusters))
                    return

                self._send(_render(cfg_path, cfg, msg=f"Unknown action: {action}", selected_clusters=selected_clusters))
            except Exception as exc:
                self._send(f"<h1>Error</h1><pre>{escape(str(exc))}</pre>", 500)

        def log_message(self, fmt, *args):
            return

    print(f"[mpi_lab web gui] Open http://{host}:{int(port)}")
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()
