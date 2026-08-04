from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from core.generator import generate_all
from core.matrix import expand_matrix, load_config


class MpiLabGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("mpi_lab Script Generator")
        self.geometry("1050x700")
        self.minsize(900, 620)

        self.config_path = tk.StringVar()
        self.output_override = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)

        self._cfg: Dict = {}

        self._build_ui()
        self._load_config_candidates()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Config:").pack(side="left")

        self.config_combo = ttk.Combobox(top, textvariable=self.config_path, width=70)
        self.config_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.config_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_selected_config())

        ttk.Button(top, text="Browse...", command=self.choose_config).pack(side="left", padx=4)
        ttk.Button(top, text="Load", command=self.load_selected_config).pack(side="left")

        options = ttk.Frame(self, padding=(12, 0, 12, 8))
        options.pack(fill="x")

        ttk.Checkbutton(options, text="Dry Run", variable=self.dry_run).pack(side="left")
        ttk.Label(options, text="Output Override:").pack(side="left", padx=(16, 4))
        ttk.Entry(options, textvariable=self.output_override, width=50).pack(side="left", fill="x", expand=True)

        selector = ttk.Frame(self, padding=(12, 4, 12, 8))
        selector.pack(fill="both", expand=True)

        self.mpi_list = self._make_listbox(selector, "MPI", 0)
        self.topology_list = self._make_listbox(selector, "Topology", 1)
        self.grid_list = self._make_listbox(selector, "Grid", 2)
        self.compute_list = self._make_listbox(selector, "Compute", 3)

        btns = ttk.Frame(self, padding=(12, 0, 12, 8))
        btns.pack(fill="x")

        ttk.Button(btns, text="Select All", command=self.select_all).pack(side="left")
        ttk.Button(btns, text="Clear Selection", command=self.clear_selection).pack(side="left", padx=6)
        ttk.Button(btns, text="Generate Scripts", command=self.generate_scripts).pack(side="right")

        log_frame = ttk.LabelFrame(self, text="Log", padding=8)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _make_listbox(self, parent: ttk.Frame, label: str, column: int) -> tk.Listbox:
        frame = ttk.LabelFrame(parent, text=label, padding=8)
        frame.grid(row=0, column=column, sticky="nsew", padx=4)
        parent.columnconfigure(column, weight=1)
        parent.rowconfigure(0, weight=1)

        lb = tk.Listbox(frame, selectmode=tk.MULTIPLE, exportselection=False, height=16)
        lb.pack(fill="both", expand=True)
        return lb

    def _load_config_candidates(self) -> None:
        cfg_dir = ROOT / "config"
        candidates: List[str] = []
        if cfg_dir.exists():
            for p in sorted(cfg_dir.glob("*.yaml")) + sorted(cfg_dir.glob("*.yml")):
                candidates.append(str(p))

        self.config_combo["values"] = candidates
        if candidates:
            self.config_path.set(candidates[0])
            self.load_selected_config()

    def choose_config(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose config YAML",
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")],
            initialdir=str(ROOT / "config"),
        )
        if selected:
            self.config_path.set(selected)
            values = list(self.config_combo["values"])
            if selected not in values:
                values.append(selected)
                self.config_combo["values"] = values
            self.load_selected_config()

    def load_selected_config(self) -> None:
        config = self.config_path.get().strip()
        if not config:
            messagebox.showwarning("Config", "Please choose a config file.")
            return

        try:
            self._cfg = load_config(config)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Cannot load config:\n{exc}")
            return

        self._fill_list(self.mpi_list, list(self._cfg.get("mpi_impl", {}).keys()))
        self._fill_list(
            self.topology_list,
            [x.get("name", "") for x in self._cfg.get("topology", []) if x.get("name")],
        )
        self._fill_list(self.grid_list, list(self._cfg.get("grid", {}).keys()))
        self._fill_list(self.compute_list, list(self._cfg.get("compute_mode", {}).keys()))

        self.select_all()
        self._log(f"Loaded config: {config}")

    def _fill_list(self, listbox: tk.Listbox, items: List[str]) -> None:
        listbox.delete(0, tk.END)
        for item in items:
            listbox.insert(tk.END, item)

    def _selected_items(self, listbox: tk.Listbox) -> List[str]:
        return [listbox.get(i) for i in listbox.curselection()]

    def select_all(self) -> None:
        for lb in (self.mpi_list, self.topology_list, self.grid_list, self.compute_list):
            lb.select_set(0, tk.END)

    def clear_selection(self) -> None:
        for lb in (self.mpi_list, self.topology_list, self.grid_list, self.compute_list):
            lb.selection_clear(0, tk.END)

    def _filtered_config(self) -> Dict:
        cfg = dict(self._cfg)

        selected_mpi = set(self._selected_items(self.mpi_list))
        selected_topology = set(self._selected_items(self.topology_list))
        selected_grid = set(self._selected_items(self.grid_list))
        selected_compute = set(self._selected_items(self.compute_list))

        if selected_mpi:
            cfg["mpi_impl"] = {
                k: v for k, v in cfg.get("mpi_impl", {}).items() if k in selected_mpi
            }
        else:
            cfg["mpi_impl"] = {}

        if selected_topology:
            cfg["topology"] = [
                t for t in cfg.get("topology", []) if t.get("name") in selected_topology
            ]
        else:
            cfg["topology"] = []

        if selected_grid:
            cfg["grid"] = {k: v for k, v in cfg.get("grid", {}).items() if k in selected_grid}
        else:
            cfg["grid"] = {}

        if cfg.get("compute_mode") is not None:
            if selected_compute:
                cfg["compute_mode"] = {
                    k: v for k, v in cfg.get("compute_mode", {}).items() if k in selected_compute
                }
            else:
                cfg["compute_mode"] = {}

        override = self.output_override.get().strip()
        if override:
            cfg["output_base"] = override

        return cfg

    def generate_scripts(self) -> None:
        if not self._cfg:
            messagebox.showwarning("Config", "Please load a config first.")
            return

        try:
            filtered = self._filtered_config()
            jobs = expand_matrix(filtered)
            if not jobs:
                messagebox.showinfo("Generate", "No jobs to generate. Check your selection.")
                self._log("No jobs to generate with current selection.")
                return

            scripts = generate_all(jobs, dry_run=self.dry_run.get())
        except Exception as exc:
            messagebox.showerror("Generation failed", str(exc))
            self._log(f"Generation failed: {exc}")
            return

        mode = "dry-run" if self.dry_run.get() else "written"
        self._log(f"Generated {len(scripts)} scripts ({mode}).")
        for p in scripts[:20]:
            self._log(f"  - {p}")
        if len(scripts) > 20:
            self._log(f"  ... {len(scripts) - 20} more")

        if scripts:
            out_root = Path(jobs[0]["output_dir"]).parent.parent
            self._log(f"submit_all.sh location: {out_root / 'submit_all.sh'}")

        messagebox.showinfo("Done", f"Generated {len(scripts)} scripts ({mode}).")

    def _log(self, text: str) -> None:
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)


def run() -> None:
    app = MpiLabGui()
    app.mainloop()


if __name__ == "__main__":
    run()
