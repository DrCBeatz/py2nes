// Controller-only playthrough of the room adventure in a complete NES emulator.
// Setup: npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// Run: node tools/rooms_smoke.mjs [build/three_rooms.nes]
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependencyPaths = [path.join(root, 'build', 'emulator'), root];
const jsnesEntry = require.resolve('jsnes', { paths: dependencyPaths });
const { NES, Controller } = await import(pathToFileURL(path.resolve(path.dirname(jsnesEntry), '../src/index.js')));
const { PNG } = require(require.resolve('pngjs', { paths: dependencyPaths }));
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'three_rooms.nes'));
const labels = new Map();
for (const line of fs.readFileSync(rom.replace(/\.nes$/i, '.lbl'), 'utf8').split('\n')) {
  const match = line.match(/^\s*al\s+([\da-f]+)\s+\.?([^\s]+)/i);
  if (match) labels.set(match[2], parseInt(match[1], 16));
}
let pixels, snapshot, frameCount = 0, maxAmplitude = 0;
const nes = new NES({
  emulateSound: true,
  onFrame: frame => { pixels = Uint32Array.from(frame); },
  onAudioSample: (left, right) => { maxAmplitude = Math.max(maxAmplitude, Math.abs(left), Math.abs(right)); },
});
nes.loadROM(fs.readFileSync(rom));
const held = new Set();
function buttons(...next) {
  for (const button of held) if (!next.includes(button)) nes.buttonUp(1, button);
  for (const button of next) if (!held.has(button)) nes.buttonDown(1, button);
  held.clear();
  for (const button of next) held.add(button);
}
function frames(count) {
  for (let i = 0; i < count; i++) {
    assert.ok(frameCount++ < 1400, 'playthrough must finish within 1400 video frames');
    nes.frame();
  }
  snapshot = nes.toJSON();
}
function read(name) {
  assert.ok(labels.has(name), `missing assembly symbol ${name}`);
  return snapshot.cpu.mem[labels.get(name)];
}
function variable(name) { return read(`v_${name}`); }
function actor(index, field) { return variable(`actor_${index}_${field}`); }
function room() { return read('rt_room'); }
function state() {
  return { frameCount, room: room(), x: actor(room() * 8, 'x'), y: actor(room() * 8, 'y'),
    keys: variable('keys'), taken: variable('room_1_key_taken'), won: variable('won') };
}
function until(condition, maximum = 150) {
  for (let i = 0; i < maximum; i++) {
    if (condition()) return;
    frames(1);
  }
  assert.fail(`controller route did not reach expected state: ${JSON.stringify(state())}`);
}
function textAt(column, row, width) {
  return Array.from(snapshot.ppu.vramMem.slice(0x2000 + row * 32 + column,
    0x2000 + row * 32 + column + width));
}
function encoded(text) { return Array.from(text, character => character.charCodeAt(0) - 32); }
function screenshot(suffix) {
  const png = new PNG({ width: 256, height: 240 });
  for (let i = 0; i < pixels.length; i++) {
    png.data[i * 4] = pixels[i] & 255;
    png.data[i * 4 + 1] = (pixels[i] >>> 8) & 255;
    png.data[i * 4 + 2] = (pixels[i] >>> 16) & 255;
    png.data[i * 4 + 3] = 255;
  }
  const output = rom.replace(/\.nes$/i, '') + suffix + '.png';
  fs.writeFileSync(output, PNG.sync.write(png));
  return output;
}
const RIGHT = Controller.BUTTON_RIGHT, LEFT = Controller.BUTTON_LEFT;
const UP = Controller.BUTTON_UP, A = Controller.BUTTON_A;
const screenshots = [];
function enter(expectedRoom) {
  buttons(UP);
  until(() => room() === expectedRoom, 30);
  frames(10);
  assert.equal(room(), expectedRoom, 'holding Up through entry must not retrigger a pressed action');
  buttons();
  frames(2);
  assert.equal(read('rt_room_loading'), 0);
}

frames(20);
assert.deepEqual([room(), actor(0, 'x'), actor(0, 'y'), variable('keys')], [0, 120, 208, 0]);
assert.deepEqual(textAt(9, 2, 14), encoded('THE CROSSROADS'));
screenshots.push(screenshot(''));

// First demonstrate that the final room is locked and gives an explanation.
buttons(RIGHT);
until(() => actor(0, 'x') >= 216);
buttons(UP);
frames(8);
assert.equal(room(), 0);
assert.equal(variable('room_0_lock_explained'), 1);
assert.deepEqual(textAt(6, 19, 20), encoded('FIND THE GARDEN KEY'.padEnd(20)));

// Walk back to the garden door, enter, and jump onto the key's ledge.
buttons(LEFT);
until(() => actor(0, 'x') <= 24);
enter(1);
assert.deepEqual([actor(8, 'x'), actor(8, 'y'), actor(8, 'grounded')], [40, 208, 1]);
assert.deepEqual(textAt(9, 2, 14), encoded('THE KEY GARDEN'));
assert.equal(actor(10, 'visible'), 1);
buttons(RIGHT);
until(() => actor(8, 'x') >= 56);
buttons(RIGHT, A);
frames(1);
buttons(RIGHT);
until(() => actor(8, 'grounded') && actor(8, 'y') === 184);
until(() => variable('keys') === 1);
buttons();
frames(5);
assert.equal(variable('room_1_key_taken'), 1);
assert.equal(actor(10, 'visible'), 0);
assert.deepEqual(textAt(7, 4, 1), encoded('1'));
assert.deepEqual(textAt(5, 19, 22), encoded('KEY FOUND! RETURN LEFT'));
screenshots.push(screenshot('-garden-key'));

// Return to the hall. Its actor is reset to the named spawn; inventory survives.
buttons(LEFT);
until(() => actor(8, 'x') <= 24 && actor(8, 'grounded') && actor(8, 'y') === 208);
enter(0);
assert.deepEqual([actor(0, 'x'), actor(0, 'y'), variable('keys')], [40, 208, 1]);
assert.equal(variable('room_0_lock_explained'), 0, 'temporary hall state resets on re-entry');
assert.deepEqual(textAt(8, 19, 16), encoded('TOWER UNLOCKED'.padEnd(16)));
assert.deepEqual(textAt(7, 4, 1), encoded('1'));
screenshots.push(screenshot('-hall-unlocked'));

// Revisit the garden: actor initialization must not resurrect its collected key.
buttons(LEFT);
until(() => actor(0, 'x') <= 24);
enter(1);
assert.equal(actor(10, 'visible'), 0);
assert.equal(snapshot.ppu.spriteMem[8 * 4], 255, 'persistent collection hides the key in hardware OAM');
assert.deepEqual(textAt(5, 19, 21), encoded('KEY ALREADY COLLECTED'));
buttons(LEFT);
until(() => actor(8, 'x') <= 24);
enter(0);

// Unlock the tower and walk to its final exit.
buttons(RIGHT);
until(() => actor(0, 'x') >= 216);
enter(2);
assert.deepEqual([actor(16, 'x'), actor(16, 'y'), variable('keys')], [40, 208, 1]);
assert.deepEqual(textAt(9, 2, 14), encoded('THE OPEN TOWER'));
buttons(RIGHT);
until(() => actor(16, 'x') >= 216);
buttons(UP);
until(() => variable('won') === 1, 20);
buttons();
frames(8);
assert.deepEqual(textAt(6, 19, 20), encoded('YOU WIN! PRESS START'));
screenshots.push(screenshot('-victory'));
const victory = state(), stoppedX = actor(16, 'x');
buttons(RIGHT, A);
frames(5);
assert.deepEqual([actor(16, 'x'), actor(16, 'y')], [stoppedX, 208]);
assert.ok(maxAmplitude > 0.05, 'jump, key, and victory sounds reach emulator audio output');

// Start is an explicit new-game rule, including flags that normally persist.
buttons(Controller.BUTTON_START);
until(() => room() === 0, 30);
buttons();
frames(10);
assert.deepEqual([variable('keys'), variable('won'), variable('room_1_key_taken')], [0, 0, 0]);
assert.deepEqual([actor(0, 'x'), actor(0, 'y'), actor(0, 'grounded')], [120, 208, 1]);
assert.deepEqual(textAt(7, 4, 1), encoded('0'));
assert.deepEqual(textAt(8, 19, 16), Array(16).fill(0), 'restart clears the unlocked message');
buttons(LEFT);
until(() => actor(0, 'x') <= 24);
enter(1);
assert.equal(actor(10, 'visible'), 1, 'new game makes the key collectible again');
assert.notEqual(snapshot.ppu.spriteMem[8 * 4], 255);
assert.deepEqual(textAt(5, 19, 21), Array(21).fill(0));
buttons();
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', videoFrames: frameCount,
  victory, maxAmplitude, screenshots }, null, 2));
