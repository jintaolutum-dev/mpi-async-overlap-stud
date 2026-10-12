const metricSelect = document.getElementById('metric');
const metricLabels = {overlap: 'Overlap (%)', hidden_us: 'Wait-time reduction (μs)', hidden_tcomm: 'Hidden communication (×Tcomm)'};
const caseSelect = document.getElementById('case');
const policySelect = document.getElementById('policy');
for (let i = 0; i < 10; i++) {
  const option = document.createElement('option');
  option.value = String(i).padStart(2, '0'); option.textContent = `Case ${option.value}`;
  option.selected = i === 1; caseSelect.append(option);
}
const payloads = [...new Set(COMPUTE_TIME_DATA.map(r => r.payload))];
Chart.defaults.font.family = '"IBM Plex Mono", monospace';
Chart.defaults.color = '#68737d';
const background = {id:'exportBackground', beforeDraw(chart) {
  const ctx = chart.ctx; ctx.save(); ctx.globalCompositeOperation = 'destination-over';
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, chart.width, chart.height); ctx.restore();
}};
const alignHiddenPoints = {
  id: 'alignHiddenPoints',
  afterDatasetsUpdate(chart) {
    if (metricSelect.value !== 'combined') return;
    for (let group = 0; group < 3; group++) {
      const bars = chart.getDatasetMeta(group).data;
      chart.getDatasetMeta(group + 3).data.forEach((point, index) => {
        if (bars[index]) point.x = bars[index].x;
      });
    }
  }
};
const connectWithinPayload = {
  id: 'connectWithinPayload',
  afterDatasetsDraw(chart) {
    if (metricSelect.value !== 'combined') return;
    const ctx = chart.ctx;
    ctx.save(); ctx.strokeStyle = '#334155'; ctx.lineWidth = 2;
    for (let index = 0; index < payloads.length; index++) {
      for (let group = 0; group < 2; group++) {
        const left = group + 3, right = left + 1;
        if (!chart.isDatasetVisible(left) || !chart.isDatasetVisible(right)) continue;
        if (chart.data.datasets[left].data[index] == null || chart.data.datasets[right].data[index] == null) continue;
        const a = chart.getDatasetMeta(left).data[index], b = chart.getDatasetMeta(right).data[index];
        const length = Math.hypot(b.x-a.x, b.y-a.y);
        if (length <= 12) continue;
        const dx = (b.x-a.x)*6/length, dy = (b.y-a.y)*6/length;
        ctx.beginPath(); ctx.moveTo(a.x+dx, a.y+dy); ctx.lineTo(b.x-dx, b.y-dy); ctx.stroke();
      }
    }
    ctx.restore();
  }
};
const chart = new Chart(document.getElementById('chart'), {
  type:'bar', data:{labels:payloads, datasets:[]}, plugins:[background, alignHiddenPoints, connectWithinPayload],
  options:{responsive:true, maintainAspectRatio:false, animation:false, layout:{padding:{top:22}},
    scales:{x:{title:{display:true,text:'Peer payload'},grid:{display:false}},
      yHidden:{position:'right',display:false,beginAtZero:true,title:{display:true,text:'Hidden Tcomm (%)'},grid:{drawOnChartArea:false}},
      y:{beginAtZero:true,title:{display:true,text:'Compute overlap (%)'},grid:{color:'#dfe4df'}}},
    plugins:{title:{display:true,text:''},legend:{position:'top',labels:{boxWidth:14,boxHeight:14,padding:20,filter:item=>metricSelect.value !== 'combined' || item.datasetIndex < 3}},tooltip:{callbacks:{
      label(ctx){return `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}${ctx.dataset.yAxisID === 'yHidden' || ['combined','overlap'].includes(metricSelect.value) ? '%' : ''}`;}

    }}}
  }
});
function update() {
  const combined = metricSelect.value === 'combined';
  const rows = COMPUTE_TIME_DATA.filter(r => r.case === caseSelect.value && r.policy === policySelect.value).map(r => combined || metricSelect.value === 'overlap' ? r : {...r, ...r.metrics[metricSelect.value]});
  chart.options.scales.y.title.text = combined ? 'Overlap (%) · Bars' : metricLabels[metricSelect.value];
  chart.options.scales.yHidden.display = combined;
  document.getElementById('table-title').textContent = combined ? '统计数据 · Overlap 与隐藏 Tcomm' : '统计数据 · ' + metricLabels[metricSelect.value];
  document.getElementById('baseline').textContent = '固定 Tcomm（原始 Case 06 基准，同一执行策略下各组共用）: ' + rows.filter(r => r.factor === '1').map(r => `${r.payload}: ${r.tcomm_us == null ? '不可用' : r.tcomm_us.toFixed(3) + ' μs'}`).join('；');
  chart.data.datasets = ['0.5','1','2'].map((factor, i) => {
    const selected = payloads.map(payload => rows.find(r => r.payload === payload && r.factor === factor));
    return {label:factor === '1' ? 'Tcomm (original configuration)' : `${factor}T communication`, type:'bar',yAxisID:'y',order:2,data:selected.map(r => r.mean), rows:selected,
      backgroundColor:['#a9d5ca','#a9c5e5','#edc0a4'][i],borderColor:['#6cae9d','#769fcf','#d79b73'][i],borderWidth:1,borderRadius:3,maxBarThickness:48,categoryPercentage:.65,barPercentage:.86};
  });
  if (combined) {
    chart.data.datasets.forEach((d,i) => d.label = ['0.5 Tcomm', 'Tcomm (original)', '2 Tcomm'][i]);
    chart.data.datasets.push(...['0.5','1','2'].map((factor, i) => {
      const selected = payloads.map(payload => rows.find(r => r.payload === payload && r.factor === factor));
      return {type:'line',yAxisID:'yHidden',order:1,label:`${factor}T · Hidden Tcomm`,
        data:selected.map(r => r.metrics.hidden_tcomm.mean == null ? null : r.metrics.hidden_tcomm.mean*100),
        borderColor:['#087f73','#0065bd','#e25d3f'][i],backgroundColor:'#ffffff',
        showLine:false,pointStyle:'circle',pointRadius:5,pointHoverRadius:7,pointBorderColor:['#087f73','#0065bd','#b56936'][i],pointBorderWidth:2,borderWidth:0,spanGaps:false};
    }));
  }
  const valid = rows.filter(r => r.n);
  const min = Math.min(0, ...valid.map(r => r.mean)), max = Math.max(0, ...valid.map(r => r.mean));
  const pad = Math.max(5, (max-min)*.12);
  chart.options.scales.y.min = min < 0 ? min-pad : 0;
  chart.options.scales.y.max = max+pad;
  if (combined) {
    const values = chart.data.datasets.flatMap(d => d.data).filter(v => v != null);
    const lo = Math.min(0,...values), hi = Math.max(0,...values);
    const step = hi-lo > 60 ? 20 : hi-lo > 20 ? 10 : 5;
    for (const axis of [chart.options.scales.y, chart.options.scales.yHidden]) {
      axis.min = Math.floor(lo/step)*step; axis.max = Math.ceil((hi+step*.3)/step)*step;
      axis.ticks = {stepSize:step};
    }
  } else { chart.options.scales.y.ticks = {}; }
  document.getElementById('hidden-head').hidden = !combined;
  chart.options.plugins.title.text = `Intel MPI · Case ${caseSelect.value} · ${policySelect.value}`;
  chart.update();
  document.getElementById('rows').replaceChildren(...rows.map(r => {
    const tr = document.createElement('tr');
    [r.payload,`${r.factor}T${r.reference_config ? ' (' + r.reference_config + ')' : ''}`,`${r.n} / ${r.requested}`,...['min','mean','max'].map(k => r[k] === null ? 'N/A' : r[k].toFixed(2)),r.runs || '—',r.missing || '—', ...(combined ? [r.metrics.hidden_tcomm.mean == null ? 'N/A' : (r.metrics.hidden_tcomm.mean*100).toFixed(2)] : [])].forEach(value => {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }); return tr;
  }));
}
metricSelect.addEventListener('change', update);
caseSelect.addEventListener('change', update); policySelect.addEventListener('change', update);
document.getElementById('export').addEventListener('click', () => {
  const a = document.createElement('a'); a.download = `compute-time-${metricSelect.value}-case${caseSelect.value}-${policySelect.value.replaceAll('/','-')}.png`;
  a.href = chart.toBase64Image(); a.click();
});
update();
