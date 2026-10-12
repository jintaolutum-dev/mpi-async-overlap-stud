const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', options: [], parentElement: {}, style: {},
    addEventListener() {}, append() {}, replaceChildren() {},
    getContext() { return {}; },
  });
  return elements.get(id);
}
for (const [id, values] of Object.entries({
  'mpi-select': ['openmpi', 'intelmpi', 'intelmpi_tcp', 'mpich'],
  'case-select': ['01', '06', '01-06', '06-09', '03-06', '03-09', '01-03', 'resources'],
  'dataset-select': ['inter', '2n2r_c24', '4n4r_c24'],
})) {
  element(id).options = values.map(value => ({value}));
  element(id).value = values[0];
}
class Chart {
  static defaults = {font: {}};
  constructor(_, config) { this.data = config.data; this.options = config.options; }
  update() {}
}
const context = vm.createContext({Chart, URLSearchParams, console,
  window: {location: {search: ''}}, lucide: {createIcons() {}},
  document: {documentElement: {style: {setProperty() {}}}, getElementById: element, querySelector: element,
    createElement: () => ({append() {}})},
});
for (const file of ['data.js', 'std-data.js', 'std-comparisons-data.js', 'resources-data.js', 'resources.js', 'app.js'])
  vm.runInContext(fs.readFileSync(`${__dirname}/${file}`, 'utf8'), context);
function check(dataset, mpi, count) {
  element('dataset-select').value = dataset;
  element('mpi-select').value = mpi;
  for (const caseId of ['01', '06']) {
    element('case-select').value = caseId;
    vm.runInContext('updateChart()', context);
    assert.equal(vm.runInContext('chart.data.labels.length', context), count);
    assert.equal(element('runs-csv').href, dataset === 'inter' ? 'overlap-runs-current.csv' : 'std-runs-current.csv');
  }
}
check('2n2r_c24', 'intelmpi', 19);
check('2n2r_c24', 'mpich', 18);
check('4n4r_c24', 'intelmpi', 12);
check('4n4r_c24', 'mpich', 19);
check('4n4r_c24', 'openmpi', 0);
element('mpi-select').value = 'mpich';
for (const topology of ['2n2r_c24', '4n4r_c24']) {
  element('dataset-select').value = topology;
  for (const pair of ['01-06', '01-03', '03-06', '03-09', '06-09']) {
    element('case-select').value = pair;
    vm.runInContext('updateChart()', context);
    assert(vm.runInContext('chart.data.labels.length > 0', context));
    assert.equal(vm.runInContext('chart.data.datasets.length', context), 2);
    assert.equal(element('comparison-csv').href, 'std-comparisons-current.csv');
  }
  element('case-select').value = 'resources';
  for (const metric of ['overlap', 'wait_mid_us', 'bench_mid']) {
    element('resource-metric').value = metric;
    element('resource-metric').selectedOptions = [{textContent: metric}];
    vm.runInContext('updateChart()', context);
    assert.equal(vm.runInContext('chart.data.datasets.length', context), 3);
    assert.equal(vm.runInContext('chart.options.scales.y.ticks.callback(10)', context), metric === 'overlap' ? '10%' : '10');
    assert.equal(element('comparison-csv').href, 'std-resources-current.csv');
  }
}
check('inter', 'mpich', 19);
assert(element('case-select').options.every(option => !option.disabled));
console.log('PASS: std topology/case switches, missing-data state, CSV links, and inter restoration');

for (const mpi of ['openmpi', 'intelmpi', 'intelmpi_tcp', 'mpich']) {
  element('dataset-select').value = 'inter';
  element('mpi-select').value = mpi;
  element('case-select').value = '01-06';
  vm.runInContext('updateChart()', context);
  assert.equal(vm.runInContext('chart.data.labels.length', context), 19);
  assert.equal(vm.runInContext('chart.data.datasets.length', context), 2);
  assert.equal(element('comparison-csv').href, 'case01_vs_case06-current.csv');
  assert(element('configuration').textContent.includes('01: ASYNC OFF'));
}
console.log('PASS: Case 01 vs 06 for all four inter MPI configurations');
