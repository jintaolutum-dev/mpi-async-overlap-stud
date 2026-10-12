(() => {
  const caseSelect = document.getElementById('polling-case');
  const mpiSelect = document.getElementById('polling-mpi');
  const metricSelect = document.getElementById('polling-metric');
  const rows = () => POLLING_DATA.filter(row => row.mpi === mpiSelect.value && row.case === caseSelect.value);
  const colors = ['#087f73', '#e25d3f'];
  const cohorts = ['no_polling', 'polling'];
  const format = value => value == null ? '—' : value.toFixed(2);
  const stats = group => group.n ? [group.min, group.overlap, group.max].map(format).join(' / ') : '暂无结果';
  const ranges = {
    id: 'pollingRanges',
    afterDatasetsDraw(chart) {
      if (metricSelect.value !== 'overlap') return;
      const {ctx, scales: {y}} = chart;
      ctx.save();
      cohorts.forEach((key, cohortIndex) => {
        if (!chart.isDatasetVisible(cohortIndex)) return;
        ctx.strokeStyle = '#17202a';
        ctx.lineWidth = 1.5;
        rows().forEach((row, index) => {
          const group = row[key];
          if (!group.n) return;
          const bar = chart.getDatasetMeta(cohortIndex).data[index];
          if (!bar) return;
          const px = bar.x;
          const low = y.getPixelForValue(group.min), high = y.getPixelForValue(group.max);
          ctx.beginPath(); ctx.moveTo(px, low); ctx.lineTo(px, high);
          ctx.moveTo(px-4, low); ctx.lineTo(px+4, low);
          ctx.moveTo(px-4, high); ctx.lineTo(px+4, high); ctx.stroke();
        });
      });
      ctx.restore();
    },
  };
  const background = {id: 'pollingExportBackground', beforeDraw(chart) {
    const ctx = chart.ctx; ctx.save(); ctx.globalCompositeOperation = 'destination-over';
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, chart.width, chart.height); ctx.restore();
  }};
  const chart = new Chart(document.getElementById('polling-chart'), {
    type: 'bar', data: {labels: [], datasets: []}, plugins: [background, ranges],
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      scales: {x: {title: {display: true, text: 'Peer payload'}}, y: {beginAtZero: true, title: {display: true, text: 'Overlap (%)'}}},
      plugins: {title: {display: true, text: ''}, tooltip: {callbacks: {afterLabel(context) {
        const group = rows()[context.dataIndex][cohorts[context.datasetIndex]];
        return [`n=${group.n}/${group.requested.length}`, `Overlap: ${stats(group)} %`,
          `Compute: ${format(group.compute_us)} μs`, `Runs: ${group.runs.join(', ')}`];
      }}}},
    },
  });
  function update() {
    const selected = rows();
    chart.data.labels = selected.map(row => row.payload);
    chart.data.datasets = cohorts.map((key, index) => ({
      label: index ? 'Polling (count=2)' : 'No polling',
      data: selected.map(row => row[key][metricSelect.value]),
      borderColor: colors[index], backgroundColor: colors[index],
      borderWidth: 1, maxBarThickness: 64,
      categoryPercentage: 0.7, barPercentage: 0.85,
    }));
    chart.options.scales.y.title.text = metricSelect.selectedOptions[0].textContent;
    chart.options.plugins.title.text = `${mpiSelect.selectedOptions[0].textContent} · ${caseSelect.selectedOptions[0].textContent} · seq/seq/seq`;
    chart.update();
    const body = document.getElementById('polling-body');
    body.replaceChildren(...selected.map(row => {
      const a = row.no_polling, b = row.polling;
      const tr = document.createElement('tr');
      [row.payload, stats(a), stats(b), a.n && b.n ? format(b.overlap-a.overlap) : '—',
        `${a.n}/${a.requested.length}: ${a.runs.join(', ') || '—'}`,
        `${b.n}/${b.requested.length}: ${b.runs.join(', ') || '—'}`,
        `${a.target_us.join(', ') || '—'} / ${b.target_us.join(', ') || '—'}`,
        `${a.cycles.join(', ') || '—'} / ${b.cycles.join(', ') || '—'}`].forEach((value, index) => {
          const td = document.createElement('td'); td.textContent = value;
          if (index === 4 || index === 5) td.className = 'run-list';
          tr.append(td);
        });
      return tr;
    }));
    document.getElementById('polling-status').textContent = `Case ${caseSelect.value}：${selected.filter(row => row.no_polling.n && row.polling.n).length}/${selected.length} 个消息大小可对比。数据取自最近一次生成的快照；各 case 按完整计时结果独立计数。`;
    const missing = selected.flatMap(row => cohorts.flatMap(key => row[key].missing.map(issue => {
      const li = document.createElement('li');
      li.textContent = `${row.payload} · ${key === 'polling' ? '有 polling' : '无 polling'} · ${issue}`;
      return li;
    })));
    document.getElementById('polling-missing').replaceChildren(...missing);
  }
  document.getElementById('polling-download').addEventListener('click', () => {
    chart.update('none');
    const link = document.createElement('a');
    link.download = `polling-${mpiSelect.value}-case${caseSelect.value}-${metricSelect.value}.png`;
    link.href = chart.toBase64Image('image/png', 1);
    link.click();
  });
  caseSelect.addEventListener('change', update);
  metricSelect.addEventListener('change', update);
  function selectMpi() {
    const previous = caseSelect.value;
    const cases = mpiSelect.value === 'openmpi'
      ? [['01', '01 · wait_all · 24 · off'], ['02', '02 · test_all · 24 · off'],
         ['03', '03 · wait_all · 23 · on'], ['04', '04 · test_all · 23 · on']]
      : Array.from({length: 10}, (_, i) => [String(i).padStart(2, '0'), `Case ${String(i).padStart(2, '0')}`]);
    caseSelect.replaceChildren(...cases.map(([value, label]) => new Option(label, value)));
    caseSelect.value = cases.some(([value]) => value === previous) ? previous : '01';
    update();
  }
  mpiSelect.addEventListener('change', selectMpi);
  selectMpi();
})();
