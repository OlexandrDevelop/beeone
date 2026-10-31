// Run with node --test; exercises the real Application route method without a DB.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../../frappe/public/js/frappe/desk.js'), 'utf8');
for (const [name, saved, restored, expected] of [
 ['restores active window', null, ['Form', 'Customer', 'C1'], ['Form', 'Customer', 'C1']],
 ['session route has precedence', 'List/Item', ['Form', 'Customer', 'C1'], ['List/Item']],
 ['explicit URL uses router', null, null, ['router']],
 ['empty layout uses router', null, undefined, ['router']],
]) {
 test(name, () => {
  const calls = [];
  const storage = new Map(saved ? [['session_last_route', saved]] : []);
  const context = {
   frappe: {}, document: {}, window: {}, $: () => ({ ready() {} }),
   localStorage: { getItem: key => storage.get(key), removeItem: key => storage.delete(key) },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  Object.assign(context.frappe, {
   boot: {}, set_route: (...args) => calls.push(args),
   router: { route: () => calls.push(['router']), on() {} },
  });
  context.frappe.Application.prototype.set_route.call({}, restored);
  assert.deepEqual(calls, [expected]);
  assert.equal(storage.has('session_last_route'), false);
 });
}
