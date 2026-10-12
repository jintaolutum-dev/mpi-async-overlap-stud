const resourceMetric = () => document.getElementById("resource-metric").value;
const resourceRows = (id) => (isStd() ? STD_RESOURCES : RESOURCE_DATA).filter(r => r.mpi === mpiSelect.value && r.case === id && (!isStd() || r.topology === datasetSelect.value));
const resourceLabel = (id) => {
  const app = {"04": 1, "05": 12, "06": 23}[id];
  const reserved = mpiSelect.value === "mpich" ? 1 : id === "05" ? 12 : 1;
  return `Case ${id}: OMP ${app}, ${mpiSelect.value === "openmpi" ? "reserved CPUs" : "progress threads"} ${reserved}`;
};
function updateResourceChart() {
  const metric = resourceMetric();
  const metricName = document.getElementById("resource-metric").selectedOptions[0].textContent;
  const rows = resourceRows("04");
  const colors = ["#087f73", "#0065bd", "#d04a2b"];
  document.getElementById("mpi-title").textContent = MPI_NAMES[mpiSelect.value];
  document.getElementById("case-title").textContent = "Case 04 vs 05 vs 06";
  document.getElementById("configuration").textContent = "2N2R · OMP/SEQ-SEQ · WAIT_ALL · ASYNC ON";
  document.getElementById("primary-key").textContent = metricName;
  document.getElementById("range-key").hidden = true;
  document.getElementById("comparison-key").hidden = true;
  document.querySelector(".unit").textContent = metricName;
  chart.data.labels = rows.map(r => splitPayload(r.payload));
  chart.data.datasets = ["04", "05", "06"].map((id, i) => ({
    label: resourceLabel(id), data: resourceRows(id).map(r => r[metric]),
    borderColor: colors[i], backgroundColor: colors[i], borderWidth: 2,
    pointRadius: 4, tension: 0, caseId: id,
  }));
  chart.options.plugins.legend.display = true;
  chart.options.scales.y.title.text = metricName;
  chart.options.scales.y.ticks.callback = (value) => metric === "overlap" ? `${value}%` : `${value}`;
  delete chart.options.scales.y.min;
  delete chart.options.scales.y.max;
  chart.options.scales.y.beginAtZero = true;
  const head = document.createElement("tr");
  ["Payload", "Case", "Source / cycles", "Runs", "Denominator", `${metricName} mean`, "Min", "Max"].forEach(v => {
    const th = document.createElement("th"); th.textContent = v; head.append(th);
  });
  document.getElementById("data-head").replaceChildren(head);
  const table = rows.flatMap((_, i) => ["04", "05", "06"].map(id => resourceRows(id)[i])).map(r => {
    const tr = document.createElement("tr");
    [r.payload, r.case, `${r.source} / ${r.cycles}`, r.runs, normalizationLabel(r),
      r[metric].toFixed(4), r[metric + "_min"].toFixed(4), r[metric + "_max"].toFixed(4)].forEach((v, index) => {
      const td = document.createElement("td"); td.textContent = v;
      if (index === 3) td.className = "run-list";
      tr.append(td);
    }); return tr;
  });
  document.getElementById("comparison-body").replaceChildren(...table);
  document.getElementById("difference-title").textContent = "Case 04 / 05 / 06 · OMP/SEQ-SEQ";
  document.getElementById("comparison-csv").href = "resources-current.csv";
  document.getElementById("runs-csv").href = "resources-runs-current.csv";
  document.getElementById("data-status").textContent = `${rows.length} message sizes · ${rows.filter(r => r.source === "retest").length} retest points · runtime: mean of per-run rank maxima`;
  if (isStd()) {
    document.getElementById("configuration").textContent = `CM4_STD · ${datasetSelect.value.slice(0, 4).toUpperCase()} · OMP/SEQ-SEQ · WAIT_ALL · ASYNC ON`;
    document.getElementById("comparison-csv").href = "std-resources-current.csv";
    document.getElementById("runs-csv").href = "std-comparison-runs-current.csv";
    document.getElementById("data-status").textContent = rows.length
      ? `${rows.length} message sizes · Matched Case 04/05/06 runs · Measured compute denominator · Maximum remote-peer payload`
      : "No complete Case 04/05/06 resource data available for this selection";
  }
  document.title = `${MPI_NAMES[mpiSelect.value]} · Case 04 / 05 / 06 · ${metricName}`;
  chart.update();
}
