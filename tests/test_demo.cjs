const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

function demo(random = Math.random) {
  const math = Object.create(Math);
  math.random = random;
  const context = { window: {}, URL, structuredClone, Math: math };
  vm.runInNewContext(readFileSync('static/demo.js', 'utf8'), context);
  return context.window.createDemo();
}

const players = ['player1', 'player2', 'player3'];

test('starts with three populated playlists, shared tracks and a unique mix', async () => {
  const state = await demo().call('/api/status');
  assert.ok(players.every(id => state.source_pools[id].length > 0));
  assert.ok(state.duplicates.some(track => track.players.length > 1));
  assert.equal(new Set(state.mix.map(track => track.id)).size, state.mix.length);
  assert.equal(state.mix.length, new Set(players.flatMap(id => state.source_pools[id].map(t => t.id))).size);
});

test('balanced generation uses the smallest source, refresh keeps other selections', async () => {
  const client = demo();
  const state = await client.call('/api/generate?balanced=true', 'POST');
  const count = Math.min(...players.map(id => state.source_pools[id].length));
  assert.ok(players.every(id => state.players[id].selection.length === count));
  const next = await client.call('/api/refresh/player1?balanced=true', 'POST');
  for (const id of ['player2', 'player3']) {
    assert.deepEqual(next.players[id].selection, state.players[id].selection);
  }
  assert.equal(new Set(next.mix.map(t => t.id)).size, next.mix.length);
});

test('reset restores full selections, and separate demos do not share state', async () => {
  const client = demo();
  await client.call('/api/generate?balanced=true', 'POST');
  const independent = await demo().call('/api/status');
  const reset = await client.call('/api/reset', 'POST');
  for (const state of [independent, reset]) {
    assert.ok(players.every(id => state.players[id].selection.length === state.source_pools[id].length));
  }
});

test('uses neutral names and randomly sampled example tracks with a deliberate conflict', async () => {
  const first = await demo(() => 0).call('/api/status');
  const second = await demo(() => 0.99).call('/api/status');
  for (const [index, id] of players.entries()) {
    assert.equal(first.players[id].name, `Playlist ${index + 1}`);
  }
  assert.notDeepEqual(first.source_pools.player1, second.source_pools.player1);
  assert.ok(first.duplicates.length > 0);
  for (const duplicate of first.duplicates) {
    assert.ok(duplicate.players.length > 1);
    assert.equal(first.mix.filter(track => track.id === duplicate.id).length, 1);
    for (const id of duplicate.players) {
      assert.ok(first.source_pools[id].some(track => track.id === duplicate.id));
    }
  }
});
