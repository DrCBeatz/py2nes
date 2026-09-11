// Controller-only playthrough: title/pause/game-over modes, attacks, recoil, and victory.
// npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// node tools/polished_adventure_smoke.mjs [build/polished_adventure.nes]
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependencyPaths = [path.join(root, 'build', 'emulator'), root];
const entry = require.resolve('jsnes', { paths: dependencyPaths });
const { NES, Controller } = await import(pathToFileURL(path.resolve(path.dirname(entry), '../src/index.js')));
const { PNG } = require(require.resolve('pngjs', { paths: dependencyPaths }));
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'polished_adventure.nes'));
const labels = new Map();
for (const line of fs.readFileSync(rom.replace(/\.nes$/i, '.lbl'), 'utf8').split('\n')) {
  const match = line.match(/^\s*al\s+([\da-f]+)\s+\.?([^\s]+)/i);
  if (match) labels.set(match[2], parseInt(match[1], 16));
}
let pixels, totalFrames = 0, maxAmplitude = 0, audioSamples = 0;
const screenshots = [], pitches = new Set();
const nes = new NES({ emulateSound: true,
  onFrame: data => { pixels = Uint32Array.from(data); },
  onAudioSample: (left, right) => {
    maxAmplitude = Math.max(maxAmplitude, Math.abs(left), Math.abs(right));
    audioSamples++;
  },
});
nes.loadROM(fs.readFileSync(rom));
const held = new Set();
const LEFT = Controller.BUTTON_LEFT, RIGHT = Controller.BUTTON_RIGHT;
const UP = Controller.BUTTON_UP, DOWN = Controller.BUTTON_DOWN;
const A = Controller.BUTTON_A, B = Controller.BUTTON_B, START = Controller.BUTTON_START;
function buttons(...next) {
  for (const key of held) if (!next.includes(key)) nes.buttonUp(1, key);
  for (const key of next) if (!held.has(key)) nes.buttonDown(1, key);
  held.clear(); next.forEach(key => held.add(key));
}
function read(name) {
  assert.ok(labels.has(name), `missing symbol ${name}`);
  return nes.cpu.mem[labels.get(name)];
}
function variable(name) { return read(`v_${name}`); }
function room() { return read('rt_room'); }
function actor(field, index = room() * 8) { return variable(`actor_${index}_${field}`); }
function mode() { return read('rt_mode_current'); }
function state() {
  return { totalFrames, mode: mode(), room: room(), x: actor('x'), y: actor('y'),
    keys: variable('keys'), lives: variable('lives'), health: variable('room_1_health_player'),
    guardX: actor('x', 11), guardY: actor('y', 11), guardHealth: variable('room_1_health_guard') };
}
function frames(count = 1) {
  for (let i = 0; i < count; i++) {
    assert.ok(++totalFrames < 9000, 'playthrough must finish within 9000 video frames');
    nes.frame();
    pitches.add(nes.papu.square2.progTimerMax);
  }
}
function until(condition, maximum = 300) {
  for (let i = 0; i < maximum; i++) {
    if (condition()) return;
    frames();
  }
  assert.fail(`controller route timed out: ${JSON.stringify(state())}`);
}
function textAt(column, row, width) {
  return Array.from(nes.ppu.vramMem.slice(0x2000 + row * 32 + column, 0x2000 + row * 32 + column + width));
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
  fs.writeFileSync(output, PNG.sync.write(png)); screenshots.push(output);
}
function enter(destination) {
  buttons(UP); until(() => room() === destination, 60); frames(12);
  buttons(); frames(3);
  assert.equal(read('rt_room_loading'), 0);
  assert.equal(read('fx_music_current_song'), 0, 'exploration music continues through doors');
}

frames(30);
assert.deepEqual([mode(), room(), actor('x'), actor('y')], [0, 0, 120, 208]);
assert.deepEqual(textAt(2, 17, 15), encoded('THE GARDEN GATE'));
screenshot('-title');
buttons(RIGHT, A, B); frames(20);
assert.deepEqual([actor('x'), actor('y'), variable('room_0_attack_player_remaining')], [120, 208, 0]);
buttons(START); until(() => mode() === 1); frames(20);
assert.equal(mode(), 1, 'holding the start press must not immediately pause');
buttons(); frames(4);
assert.deepEqual(textAt(2, 17, 28), Array(28).fill(0));

// Pause in mid-jump: coordinates, velocity fractions, and animation all stop.
buttons(RIGHT, A); until(() => actor('y') < 195);
buttons(START); until(() => mode() === 2); frames(5);
const fields = ['x', 'y', 'vx', 'vy', 'x_fraction', 'y_fraction', 'vx_fraction', 'vy_fraction', 'frame', 'frame_timer'];
const pausedActor = fields.map(field => actor(field));
buttons(RIGHT, A, B); frames(45);
assert.deepEqual(fields.map(field => actor(field)), pausedActor, 'pause holds full actor state');
assert.equal(variable('room_0_attack_player_remaining'), 0, 'paused attack input is ignored');
assert.equal(read('fx_music_mode_paused'), 1);
assert.deepEqual(textAt(2, 19, 6), encoded('PAUSED'));
screenshot('-paused');
buttons(START); until(() => mode() === 1); buttons(); frames(8);
assert.equal(read('fx_music_mode_paused'), 0);
until(() => actor('grounded'));
buttons(LEFT); until(() => actor('x') <= 24); enter(1);

// Swing from outside body contact and inspect recoil/one hit for this swing.
buttons(RIGHT);
until(() => actor('x') + 14 < actor('x', 11) + 2 && actor('x') + 28 > actor('x', 11) + 2);
buttons(B); until(() => variable('room_1_health_guard') === 1, 20);
assert.equal(variable('room_1_health_player'), 3, 'the reach attack lands before body contact');
assert.ok(variable('room_1_hurt_guard_remaining') > 0);
const firstHitX = actor('x', 11);
frames(4);
assert.ok(actor('x', 11) > firstHitX, 'guard recoil is preserved while patrol is suspended');
assert.equal(variable('room_1_health_guard'), 1, 'one swing cannot repeatedly hit');
assert.equal(actor('clip'), 4, 'player uses its named attack animation');
screenshot('-combat');
// The cooldown and the guard's invulnerability both expire before a new swing.
buttons(); until(() => !variable('room_1_attack_player_remaining') && !variable('room_1_health_guard_invulnerability'));
buttons(RIGHT);
until(() => actor('y', 11) === 208 && actor('x') + 14 < actor('x', 11) + 2 && actor('x') + 28 > actor('x', 11) + 2);
buttons(B); until(() => variable('room_1_health_guard') === 0, 30);
buttons(); frames(12);
assert.equal(actor('visible', 11), 0);

// Leave/re-enter to reset the guard, then let damage exhaust the three lives.
buttons(LEFT); until(() => actor('x') <= 24 && actor('grounded') && actor('y') === 208); enter(0);
buttons(LEFT); until(() => actor('x') <= 24); enter(1);
assert.equal(variable('room_1_health_guard'), 2);
for (let i = 0; mode() === 1 && i < 1800; i++) {
  const distance = actor('x', 11) - actor('x');
  if (distance > 3) buttons(RIGHT);
  else if (distance < -3) buttons(LEFT);
  else buttons();
  frames();
}
assert.equal(mode(), 3, `repeated guard contacts reach game over: ${JSON.stringify(state())}`);
buttons(); frames(12);
assert.equal(variable('lives'), 0);
assert.deepEqual(textAt(2, 17, 9), encoded('GAME OVER'));
const deadState = [actor('x'), actor('y'), actor('x', 11), variable('room_1_hurt_player_remaining')];
buttons(A, B, LEFT); frames(20);
assert.deepEqual([actor('x'), actor('y'), actor('x', 11), variable('room_1_hurt_player_remaining')], deadState);
screenshot('-game-over');
buttons(START); until(() => mode() === 1 && room() === 0); buttons(); frames(10);
assert.deepEqual([variable('lives'), variable('keys'), actor('x'), actor('y')], [3, 0, 120, 208]);

// Complete the original room/key route and run a sequence in the victory mode.
buttons(LEFT); until(() => actor('x') <= 24); enter(1);
buttons(RIGHT); until(() => actor('x') >= 44);
buttons(RIGHT, A); until(() => !actor('grounded'));
until(() => actor('grounded') && actor('y') === 184);
buttons(RIGHT); until(() => variable('keys') === 1); buttons(); frames(5);
assert.equal(variable('room_1_checkpoint_player'), 1);
buttons(LEFT); until(() => actor('x') <= 24 && actor('y') === 208 && actor('grounded')); enter(0);
buttons(RIGHT); until(() => actor('x') >= 216); enter(2);
buttons(RIGHT); until(() => actor('x') >= 216); buttons(UP); until(() => mode() === 4);
buttons(); until(() => !variable('sequence_ending_active')); frames(10);
assert.equal(read('fx_music_current_song'), 1);
assert.deepEqual(textAt(2, 19, 28), encoded('YOU WIN! PRESS START'.padEnd(28)));
const victory = state();
screenshot('-victory');
buttons(START); until(() => mode() === 1 && room() === 0); buttons(); frames(10);
assert.deepEqual([variable('lives'), variable('keys'), variable('room_1_key_taken')], [3, 0, 0]);
assert.equal(read('fx_music_current_song'), 0);
assert.ok(maxAmplitude > .05 && audioSamples > 10000);
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', totalFrames,
  victory, maxAmplitude, screenshots }, null, 2));
