const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page(request = async () => ({}), download = async () => '/tmp/timetable.png') {
  let definition;
  const toasts = [];
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, '../pages/display-timetable/index.js'), 'utf8'),
    {
      require: () => ({ request, downloadFile: download }),
      Page: value => { definition = value; },
      getApp: () => ({}),
      Date,
      Set,
      wx: { showToast(value) { toasts.push(value); } }
    }
  );
  definition.setData = function (patch) { Object.assign(this.data, patch); };
  definition.toasts = toasts;
  return definition;
}

function periods() {
  return [
    { id: 'morning-1', section: 'morning', start_time: '08:00', end_time: '08:45' },
    { id: 'afternoon-1', section: 'afternoon', start_time: '13:30', end_time: '14:15' }
  ];
}

test('loads timetable orientation and builds the selected weekday rows', async () => {
  const p = page(async () => ({ orientation: 'landscape', periods: periods(), entries: [
    { weekday: 1, period_id: 'morning-1', course_name: '语文', note: '预习课文' }
  ] }));
  p.data.selectedWeekday = 1;
  p.loadPreview = async () => {};
  await p.loadTimetable();
  assert.equal(p.data.orientation, 'landscape');
  assert.equal(p.data.morningCount, 1);
  assert.equal(p.data.afternoonCount, 1);
  assert.equal(p.data.dayRows[0].courseName, '语文');
  assert.equal(p.data.dayRows[0].note, '预习课文');
});

test('selecting a weekday scrolls the tab into view', () => {
  const p = page();
  p.data.periods = periods();
  p.data.entries = [];
  p.onSelectWeekday({ currentTarget: { dataset: { weekday: '7' } } });
  assert.equal(p.data.selectedWeekday, 7);
  assert.equal(p.data.weekdayScrollIntoView, 'weekday-7');
});

test('rejects more than ten periods before changing the editor', () => {
  const p = page();
  p.data.periods = [
    ...Array.from({ length: 5 }, (_, index) => ({ id: `morning-${index + 1}`, section: 'morning' })),
    ...Array.from({ length: 5 }, (_, index) => ({ id: `afternoon-${index + 1}`, section: 'afternoon' }))
  ];
  p.data.morningCount = 5;
  p.data.afternoonCount = 5;
  p.onCountChange({ currentTarget: { dataset: { section: 'morning' } }, detail: { value: '6' } });
  assert.equal(p.data.morningCount, 5);
  assert.match(p.toasts[0].title, /1～10节/);
});

test('save removes empty cells and keeps course notes', async () => {
  let write;
  const p = page(async options => {
    write = options;
    return { periods: options.data.periods, entries: options.data.entries };
  });
  p.data.periods = periods();
  p.data.orientation = 'landscape';
  p.data.entries = [
    { weekday: 1, period_id: 'morning-1', course_name: '语文', note: '预习课文' },
    { weekday: 1, period_id: 'afternoon-1', course_name: '', note: '' }
  ];
  p.loadPreview = async () => {};
  p.refreshDayRows = () => {};
  await p.saveTimetable();
  assert.equal(write.path, '/display-timetable');
  assert.equal(write.method, 'PUT');
  assert.equal(write.data.orientation, 'landscape');
  assert.equal(write.data.entries.length, 1);
  assert.equal(write.data.entries[0].note, '预习课文');
});

test('selects portrait or landscape without changing timetable data', () => {
  const p = page();
  p.data.periods = periods();
  p.data.entries = [{ weekday: 1, period_id: 'morning-1', course_name: '语文', note: '' }];
  p.onSelectOrientation({ currentTarget: { dataset: { orientation: 'landscape' } } });
  assert.equal(p.data.orientation, 'landscape');
  assert.equal(p.data.periods.length, 2);
  assert.equal(p.data.entries.length, 1);
});
