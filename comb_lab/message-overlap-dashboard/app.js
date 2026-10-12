const MPI_NAMES = {
  openmpi: "Open MPI",
  intelmpi: "Intel MPI verbs",
  intelmpi_tcp: "Intel MPI TCP",
  mpich: "MPICH TCP",
};

const MPI_COLORS = {
  openmpi: "#087f73",
  intelmpi: "#0065bd",
  intelmpi_tcp: "#d04a2b",
  mpich: "#7c5c20",
};

const mpiSelect = document.getElementById("mpi-select");
const caseSelect = document.getElementById("case-select");
const datasetSelect = document.getElementById("dataset-select");
const isStd = () => datasetSelect.value !== "inter";
const requestedView = new URLSearchParams(window.location.search);
for (const [key, select] of [["mpi", mpiSelect], ["case", caseSelect], ["dataset", datasetSelect]]) {
  const value = requestedView.get(key);
  if (Array.from(select.options).some((option) => option.value === value)) select.value = value;
}
const isComparison = () => caseSelect.value.includes("-");
const isResource = () => caseSelect.value === "resources";
const pairCases = () => caseSelect.value.split("-");
const caseLabel = (id) => `${id} · ${["01", "06"].includes(id) ? "wait_all" : "test_all"}`;
const comparisons = {"01-06": COMPARISON0106_DATA, "01-03": COMPARISON01_DATA, "03-06": COMPARISON03_DATA, "06-09": COMPARISON_DATA, "03-09": COMPARISON0309_DATA};
const comparisonRows = () => (isStd() ? STD_COMPARISONS : comparisons[caseSelect.value]).filter((row) => row.mpi === mpiSelect.value && (!isStd() || (row.topology === datasetSelect.value && row.pair === caseSelect.value)));
const selectedRows = () => (isStd() ? STD_DATA : OVERLAP_DATA).filter(
  (row) => (!isStd() || row.topology === datasetSelect.value) && row.mpi === mpiSelect.value && row.case === (isComparison() ? "06" : caseSelect.value),
);
const splitPayload = (payload) => payload.split(" ");
const normalizationLabel = (row) => row.normalization === "fixed_old_baseline"
  ? `Fixed baseline ${row.baseline_us.toFixed(3)} us` : "Measured mid-comm";

const updateTable = (rows) => {
  const compared = isComparison();
  const [first, second] = pairCases();
  const headers = ["Peer payload", "Source", "Runs", "Denominator", ...(compared
    ? [`${first} overlap %`, `${second} overlap %`, "Difference pp", "Paired min-max pp", "Midcomm runtime change %"]
    : ["Min %", "Mean %", "Max %"])];
  const header = document.createElement("tr");
  headers.forEach((label) => { const th = document.createElement("th"); th.textContent = label; header.append(th); });
  document.getElementById("data-head").replaceChildren(header);
  document.getElementById("comparison-body").replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    const values = [row.payload, `${row.source} (${row.run_count}); ${row.cycles} cycles`, row.runs, normalizationLabel(row), ...(compared
      ? [row[`${first}_overlap`].toFixed(2), row[`${second}_overlap`].toFixed(2), row.delta.toFixed(2), `${row.delta_min.toFixed(2)} to ${row.delta_max.toFixed(2)}`, row.bench_change_pct.toFixed(2)]
      : [row.min.toFixed(2), row.mean.toFixed(2), row.max.toFixed(2)])];
    values.forEach((value, index) => {
      const td = document.createElement("td"); td.textContent = value;
      if (index === 2) td.className = "run-list";
      tr.append(td);
    });
    return tr;
  }));
  document.getElementById("difference-title").textContent = compared ? `Case ${second} − Case ${first}` : `Case ${first} data`;
  document.getElementById("comparison-csv").href = compared ? `case${first}_vs_case${second}-current.csv` : "overlap-current.csv";
  const count = rows.filter((row) => row.source === "retest").length;
  const counts = rows.filter((row) => row.source === "retest").map((row) => row.run_count);
  const runRange = counts.length ? `${Math.min(...counts)}-${Math.max(...counts)}` : "0";
  document.getElementById("data-status").textContent = `${count} retest points (${runRange} valid runs each) · ${rows.length - count} original points · Mixed normalization`;
};

Chart.defaults.font.family = '"IBM Plex Mono", monospace';
Chart.defaults.color = "#68737d";

const rangeBars = {
  id: "rangeBars",
  beforeDatasetsDraw(chart, args, options) {
    if (isComparison() || isResource()) return;
    const rows = selectedRows();
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    const context = chart.ctx;

    context.save();
    context.strokeStyle = options.color;
    context.lineWidth = 1.5;

    rows.forEach((row, index) => {
      const x = xScale.getPixelForValue(index);
      const minY = yScale.getPixelForValue(row.min);
      const maxY = yScale.getPixelForValue(row.max);

      context.beginPath();
      context.moveTo(x, minY);
      context.lineTo(x, maxY);
      context.moveTo(x - 4, minY);
      context.lineTo(x + 4, minY);
      context.moveTo(x - 4, maxY);
      context.lineTo(x + 4, maxY);
      context.stroke();
    });

    context.restore();
  },
};

const gridBoundary = {
  id: "gridBoundary",
  beforeDatasetsDraw(chart, args, options) {
    if (isStd()) return;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    const boundary = (xScale.getPixelForValue(7) + xScale.getPixelForValue(8)) / 2;
    const context = chart.ctx;

    context.save();
    context.strokeStyle = options.color;
    context.lineWidth = 2.25;
    context.setLineDash([7, 5]);
    context.beginPath();
    context.moveTo(boundary, yScale.top);
    context.lineTo(boundary, yScale.bottom);
    context.stroke();
    context.restore();
  },
};

const initialRows = selectedRows();
const chart = new Chart(document.getElementById("overlap-chart"), {
  type: "line",
  plugins: [gridBoundary, rangeBars],
  data: {
    labels: initialRows.map((row) => splitPayload(row.payload)),
    datasets: [
      {
        label: "Mean",
        data: initialRows.map((row) => row.mean),
        borderColor: MPI_COLORS.openmpi,
        backgroundColor: "#ffffff",
        pointBorderColor: MPI_COLORS.openmpi,
        pointBorderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        borderWidth: 3,
        tension: 0.16,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 350 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      gridBoundary: { color: "rgba(73, 84, 92, 0.9)" },
      rangeBars: { color: "rgba(8, 127, 115, 0.58)" },
      legend: { display: false },
      tooltip: {
        filter: (item) => isResource() || isComparison() || item.dataset.label === "Mean",
        callbacks: {
          title: (items) => (isResource() ? resourceRows("04") : isComparison() ? comparisonRows() : selectedRows())[items[0].dataIndex].payload,
          label: (item) => {
            if (isResource()) return `${item.dataset.label}: ${item.raw.toFixed(4)}`;
            if (isComparison()) return ` ${item.dataset.label}: ${item.raw.toFixed(2)}%`;
            const row = selectedRows()[item.dataIndex];
            return ` Mean ${row.mean.toFixed(2)}% · ${row.min.toFixed(2)}%–${row.max.toFixed(2)}%`;
          },
          afterLabel: (item) => {
            if (isResource()) {
              const row = resourceRows(item.dataset.caseId)[item.dataIndex];
              const metric = resourceMetric();
              return [`Min-max: ${row[metric + "_min"].toFixed(4)} to ${row[metric + "_max"].toFixed(4)}`,
                `${row.source}: ${row.run_count} runs; ${row.cycles} cycles`, normalizationLabel(row), row.runs];
            }
            const row = (isComparison() ? comparisonRows() : selectedRows())[item.dataIndex];
            const provenance = [`${row.source}: ${row.run_count} runs; ${row.cycles} cycles`, normalizationLabel(row), ...row.runs.split(", ").map((run) => ` ${run}`)];
            if (!isComparison()) return [...provenance, ...(row.anomaly ? ["Review recommended"] : [])];
            return [...provenance, `Difference: ${row.delta.toFixed(2)} pp`, `Paired range: ${row.delta_min.toFixed(2)} to ${row.delta_max.toFixed(2)} pp`];
          },
        },
      },
    },
    scales: {
      x: {
        type: "category",
        offset: true,
        grid: { color: "rgba(23, 32, 42, 0.07)" },
        border: { color: "#aeb7b0" },
        ticks: {
          autoSkip: false,
          maxRotation: 0,
          minRotation: 0,
          padding: 8,
          font: { size: 10, lineHeight: 1.4 },
        },
        title: {
          display: true,
          text: "Peer payload (equally spaced categories)",
          color: "#17202a",
          padding: 12,
        },
      },
      y: {
        suggestedMin: -50,
        suggestedMax: 120,
        grid: {
          color: (context) => context.tick.value === 0 ? "#e25d3f" : "rgba(23, 32, 42, 0.08)",
          lineWidth: (context) => context.tick.value === 0 ? 1.5 : 1,
        },
        border: { color: "#aeb7b0" },
        ticks: { callback: (value) => `${value}%` },
        title: { display: true, text: "Normalized wait reduction (mixed denominators)", color: "#17202a", padding: 12 },
      },
    },
  },
});

const updateChart = () => {
  for (const option of caseSelect.options) option.disabled = false;
  document.querySelector(".grid-boundary-key").parentElement.hidden = isStd();
  document.getElementById("resource-metric-control").hidden = !isResource();
  if (isResource()) { updateResourceChart(); return; }
  chart.options.plugins.legend.display = false;
  chart.options.scales.y.title.text = "Normalized wait reduction (mixed denominators)";
  chart.options.scales.y.ticks.callback = (value) => `${value}%`;
  document.querySelector(".unit").textContent = "Unit: %";
  document.getElementById("runs-csv").href = "overlap-runs-current.csv";
  const rows = selectedRows();
  const color = MPI_COLORS[mpiSelect.value];

  document.getElementById("mpi-title").textContent = MPI_NAMES[mpiSelect.value];
  document.getElementById("case-title").textContent = isComparison() ? `Case ${pairCases().join(" vs ")}` : `Case ${caseSelect.value}`;
  document.getElementById("configuration").textContent = caseSelect.value === "01-03" ? "2N2R · SEQ/SEQ-SEQ · ASYNC OFF · OMP 24" : caseSelect.value === "03-06" ? "2N2R · SEQ/SEQ-SEQ · 03: ASYNC OFF / OMP 24 · 06: ASYNC ON / OMP 23" : isComparison() ? "2N2R · SEQ/SEQ-SEQ · ASYNC ON · OMP 23" : "2N2R · SEQ/SEQ-SEQ · WAIT_ALL";
  if (caseSelect.value === "01-06") document.getElementById("configuration").textContent = "2N2R · SEQ/SEQ-SEQ · WAIT_ALL · 01: ASYNC OFF / OMP 24 · 06: ASYNC ON / OMP 23";
  document.getElementById("primary-key").textContent = isComparison() ? caseLabel(pairCases()[0]) : "Mean";
  if (caseSelect.value === "03-09") document.getElementById("configuration").textContent = "2N2R · SEQ/SEQ-SEQ · 03: ASYNC OFF / OMP 24 · 09: ASYNC ON / OMP 23";
  document.getElementById("range-key").hidden = isComparison();
  document.getElementById("comparison-key").hidden = !isComparison();
  document.title = `${MPI_NAMES[mpiSelect.value]} Case ${caseSelect.value} Communication Overlap`;
  document.documentElement.style.setProperty("--teal", color);

  chart.data.labels = rows.map((row) => splitPayload(row.payload));
  chart.data.datasets[0].data = rows.map((row) => row.mean);
  chart.data.datasets[0].borderColor = color;
  chart.data.datasets[0].pointBorderColor = color;
  chart.data.datasets[0].label = isComparison() ? caseLabel(pairCases()[0]) : "Mean";
  chart.data.datasets = [chart.data.datasets[0]];
  if (isComparison()) {
    const [first, second] = pairCases();
    document.getElementById("secondary-key").textContent = caseLabel(second);
    const compared = comparisonRows();
    chart.data.labels = compared.map((row) => splitPayload(row.payload));
    chart.data.datasets[0].data = compared.map((row) => row[`${first}_overlap`]);
    chart.data.datasets.push({
      ...chart.data.datasets[0], label: caseLabel(second),
      data: compared.map((row) => row[`${second}_overlap`]),
      borderColor: "#e25d3f", pointBorderColor: "#e25d3f", borderDash: [7, 4],
      pointStyle: "rectRot",
    });
  }
  updateTable(isComparison() ? comparisonRows() : rows);
  if (isStd()) {
    const stdRows = isComparison() ? comparisonRows() : rows;
    document.getElementById("configuration").textContent = `CM4_STD · ${datasetSelect.value.slice(0, 4).toUpperCase()} · SEQ/SEQ-SEQ · CASE ${caseSelect.value}`;
    document.getElementById("comparison-csv").href = isComparison() ? "std-comparisons-current.csv" : "std-current.csv";
    document.getElementById("runs-csv").href = isComparison() ? "std-comparison-runs-current.csv" : "std-runs-current.csv";
    document.getElementById("data-status").textContent = stdRows.length
      ? `${stdRows.length} message sizes · ${Math.min(...stdRows.map(r => r.run_count))}-${Math.max(...stdRows.map(r => r.run_count))} complete pairs per point · Measured compute denominator · Maximum remote-peer payload`
      : "No complete paired data available for this selection";
  }
  const plottedRows = isComparison() ? comparisonRows() : rows;
  chart.data.datasets.forEach((dataset) => {
    dataset.pointRadius = plottedRows.map((row) => row.source === "retest" ? 5 : 4);
  });
  // Include run ranges in single-case limits so retest outliers are not clipped.
  const limits = isComparison() ? chart.data.datasets.flatMap((dataset) => dataset.data)
    : rows.flatMap((row) => [row.min, row.max]);
  chart.options.scales.y.min = Math.floor(Math.min(0, ...limits) / 10) * 10 - 10;
  chart.options.scales.y.max = Math.ceil(Math.max(100, ...limits) / 10) * 10 + 10;
  chart.options.plugins.rangeBars.color = `${color}94`;
  chart.update();
};

mpiSelect.addEventListener("change", updateChart);
datasetSelect.addEventListener("change", updateChart);
caseSelect.addEventListener("change", updateChart);
document.getElementById("resource-metric").addEventListener("change", updateChart);
updateChart();
lucide.createIcons();

document.getElementById("download").addEventListener("click", () => {
  const link = document.createElement("a");
  link.download = `${datasetSelect.value}-${mpiSelect.value}-case${caseSelect.value}-overlap-vs-message-size.png`;
  link.href = chart.toBase64Image("image/png", 1);
  link.click();
});
