// Exercise the actual frontend progress functions with routes captured from FastAPI.
// Map rendering is covered separately by the live browser walkthroughs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = process.argv[2] || path.join(__dirname, '../frontend/app.js');
const source = fs.readFileSync(sourcePath, 'utf8').replace(/\bboot\(\);\s*$/, '');
const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'routes.json'), 'utf8'))
  .filter(fixture => !process.argv[3] || fixture.params.start === process.argv[3]);

function createContext(fixture) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      textContent: '', hidden: false, disabled: false, style: {},
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute() {}, querySelectorAll() { return []; },
      querySelector() { return element(id + '-child'); },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    fixture, console, URLSearchParams, setTimeout, clearTimeout,
    window: { location: { search: '?api=http://127.0.0.1:8001' }, matchMedia: () => ({ matches: false }) },
    document: { getElementById: element, querySelectorAll: () => [] },
  });
  vm.runInContext(source, context, { filename: sourcePath });
  vm.runInContext(`
    api = async () => JSON.parse(JSON.stringify(fixture.route));
    renderBlockedStatus = renderInstructions = renderFloorButtons = drawRouteOverlay = () => {};
    showToast = message => { state.lastToast = message; };
    loadFloorMap = async floor => { state.selectedFloor = floor; state.currentSvg = { dataset: { floor } }; };
    focusRemainingRoute = cp => { state.lastFocus = cp; };
    centerCurrentCheckpoint = () => { state.lastFocus = state.route.checkpoints[state.currentCheckpointIndex]; };
    state.selectedStart = { floor_id: fixture.params.start_floor, code: fixture.params.start };
    state.selectedDestination = { floor_id: fixture.params.destination_floor, code: fixture.params.destination };
    state.floors = fixture.route.floors.map(floor_id => ({ floor_id, floor_name: floor_id }));
  `, context);
  return { context, elements, run: code => vm.runInContext(code, context) };
}

async function verify(fixture) {
  const { elements, run } = createContext(fixture);
  const route = fixture.route;
  const checkpoints = route.checkpoints;
  const name = `${fixture.params.mode} ${fixture.params.start_floor}/${fixture.params.start} -> ${fixture.params.destination_floor}/${fixture.params.destination}`;
  let assertions = 0;
  function check(index) {
    const cp = checkpoints[index];
    const next = checkpoints[index + 1];
    const expectedMap = next && next.floor_id !== cp.floor_id ? next.floor_id : cp.floor_id;
    assert.equal(run('state.currentCheckpointIndex'), index, name + ': confirmed index');
    assert.equal(run('state.selectedFloor'), expectedMap, name + ': displayed floor at point ' + cp.checkpoint);
    assert.equal(run('state.currentSvg.dataset.floor'), expectedMap, name + ': loaded map');
    assert.equal(elements.get('progressPercent').textContent, cp.progress_percent + '%', name + ': progress anchor');
    assert.equal(elements.get('remainingText').textContent, cp.remaining_distance_m + ' m remaining', name + ': remaining distance');
    assert.equal(elements.get('confirmNextBtn').disabled, !next, name + ': confirmation button');
    assert.equal(run('state.progressBusy'), false, name + ': progress lock');
    const original = route.floor_routes[cp.floor_id].find(point => point.node_id === cp.node_id).original_node_id;
    assert.equal(run('routingCodeForCheckpoint(state.route.checkpoints[state.currentCheckpointIndex])'), original, name + ': reroute uses original node');
    assertions += 8;
  }
  await run(`planRoute({ mode: fixture.params.mode, blocked: fixture.params.blocked || [] })`);
  check(0);
  for (let index = 1; index < checkpoints.length; index++) {
    await run(`reachCheckpoint(${index + 1})`);
    check(index - 1); // A later dot must not skip an unconfirmed point.
    await run(`reachCheckpoint(${index})`);
    check(index);
    await run('previousCheckpoint()');
    check(index - 1); // Undo restores the same hand-off view and position.
    await run(`reachCheckpoint(${index})`);
    check(index);
  }
  assert.equal(elements.get('nextStepSubtitle').textContent, 'Navigation complete');
  assert.equal(checkpoints.at(-1).progress_percent, 100);
  console.log(`PASS ${name}; ${checkpoints.length} checkpoints; ${assertions + 2} assertions`);
  return assertions + 2;
}

(async () => {
  let assertions = 0;
  for (const fixture of fixtures) assertions += await verify(fixture);
  console.log(`PASS ${fixtures.length} routes; ${assertions} assertions`);
})().catch(error => { console.error(error.message); process.exitCode = 1; });
