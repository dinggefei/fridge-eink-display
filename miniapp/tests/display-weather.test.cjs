const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page(request = async () => ({}), download = async () => '/tmp/preview.png') {
  let definition;
  const navigations = [];
  const toasts = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/display-settings/index.js'), 'utf8'), {
    require: () => ({ request, downloadFile: download }),
    Page: value => { definition = value; },
    wx: {
      showToast(options) { toasts.push(options); },
      navigateTo(options) { navigations.push(options); }
    }
  });
  definition.setData = function (patch) { Object.assign(this.data, patch); };
  definition.navigations = navigations;
  definition.toasts = toasts;
  return definition;
}

test('weather entry requires updated backend; old backend stays usable', () => {
  const p = page();
  p.applySettings({ display_mode: 'inventory' });
  assert.equal(p.data.modes.some(m => m.value === 'weather'), false);
  p.applySettings({ display_mode: 'inventory', weather_mode_available: true,
    timetable_mode_available: true });
  assert.equal(p.data.modes.some(m => m.value === 'weather'), true);
  assert.deepEqual(
    Array.from(p.data.modes, mode => mode.value),
    ['inventory', 'almanac', 'weather', 'timetable', 'market', 'album']
  );
});

test('selecting weather while the provider is unavailable keeps the active mode', () => {
  const p = page();
  let saved = false;
  p.saveMode = () => { saved = true; };
  p.onSelectMode({ currentTarget: { dataset: { mode: 'weather' } } });
  assert.equal(p.data.selectedMode, 'inventory');
  assert.equal(saved, false);
  assert.match(p.toasts[0].title, /未配置/);
});

test('selecting weather without a city opens city setup without changing the device mode', () => {
  const p = page();
  p.data.weatherProviderReady = true;
  let saved = false;
  p.saveMode = () => { saved = true; };
  p.onSelectMode({ currentTarget: { dataset: { mode: 'weather' } } });
  assert.equal(p.data.selectedMode, 'weather');
  assert.equal(saved, false);
  assert.match(p.toasts[0].title, /选择城市/);
});

test('weather city selection preserves almanac switch and then enables weather', async () => {
  const writes = [];
  const p = page(async options => {
    writes.push(options);
    return { display_mode: 'inventory', weather_enabled: false, weather_mode_available: true,
      weather_location: { name: '上海' } };
  });
  p.data.selectedMode = 'weather';
  let selected;
  p.saveMode = async mode => { selected = mode; };
  await p.saveWeatherSettings(null, { name: '上海' });
  assert.equal(writes[0].data.enabled, null);
  assert.equal(p.data.weatherEnabled, false);
  assert.equal(selected, 'weather');
});

test('preview is authenticated household download and handles failure', async () => {
  let options;
  const p = page(undefined, async value => { options = value; throw new Error('offline'); });
  await p.loadWeatherPreview();
  assert.equal(options.householdScoped, true);
  assert.equal(options.path, '/display-settings/weather-preview');
  assert.equal(p.data.weatherPreviewPath, '');
  assert.equal(p.data.weatherPreviewLoading, false);
  assert.match(p.data.weatherPreviewError, /失败/);
});

test('older preview downloads cannot replace new city previews', async () => {
  const pending = [];
  const p = page(undefined, () => new Promise(resolve => pending.push(resolve)));
  const old = p.loadWeatherPreview();
  const current = p.loadWeatherPreview();
  pending[1]('/tmp/new-city.png');
  await current;
  pending[0]('/tmp/old-city.png');
  await old;
  assert.equal(p.data.weatherPreviewPath, '/tmp/new-city.png');
});

test('inventory mode opens todo management as a secondary page', () => {
  const p = page();
  p.goToTodo();
  assert.equal(p.navigations[0].url, '/pages/todo/index');
});
