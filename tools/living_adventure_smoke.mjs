// Controller-only playthrough: modal conversation, damage, checkpoint, rooms, and music.
// npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// node tools/living_adventure_smoke.mjs [build/living_adventure.nes]
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
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'living_adventure.nes'));
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
function state() {
  return { totalFrames, room: room(), x: actor('x'), y: actor('y'),
    keys: variable('keys'), deaths: variable('deaths'), health: variable('room_1_health_player'),
    guardX: actor('x', 11), chatStep: variable('room_0_sequence_guide_chat_step') };
}
function frames(count = 1) {
  for (let i = 0; i < count; i++) {
    assert.ok(++totalFrames < 6000, 'playthrough must finish within 6000 video frames');
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
assert.deepEqual([room(), actor('x'), actor('y')], [0, 120, 208]);
assert.equal(read('fx_music_current_song'), 0);
buttons(RIGHT); until(() => actor('x') >= 140); buttons(); frames(5);
buttons(B); until(() => variable('room_0_sequence_guide_chat_step') === 5); frames(4);
assert.equal(actor('frozen'), 1);
assert.deepEqual(textAt(2, 11, 8), encoded('WELCOME!'));
const frozenX = actor('x');
buttons(RIGHT, A); until(() => variable('room_0_sequence_guide_chat_step') === 11); frames(15);
assert.equal(variable('room_0_sequence_guide_chat_active'), 1, 'holding A does not confirm the answer');
assert.equal(actor('x'), frozenX, 'movement remains frozen through page upload and held input');
assert.deepEqual(textAt(2, 14, 7), encoded('> READY'));
screenshot('-dialogue');
buttons(); frames(3); buttons(DOWN); frames(5);
assert.equal(variable('room_0_dialogue_guide_chat_selection'), 1);
buttons(A); until(() => !variable('room_0_sequence_guide_chat_active')); buttons(); frames(4);
assert.equal(actor('frozen'), 0);
assert.deepEqual(textAt(2, 11, 28), Array(28).fill(0), 'dialogue clears its reserved rectangle');

buttons(LEFT); until(() => actor('x') <= 24); enter(1);
assert.deepEqual([actor('x'), actor('y'), variable('room_1_health_player')], [40, 208, 3]);
// Walk beneath the key ledge into the guard's patrol; stay until lethal damage.
buttons(RIGHT); until(() => actor('x') >= 144); buttons(); frames(5);
until(() => variable('deaths') === 1, 1100); frames(4);
assert.deepEqual([actor('x'), actor('y'), variable('room_1_health_player')], [40, 208, 3]);
assert.ok(variable('room_1_health_player_invulnerability') > 0, 'respawn grants temporary protection');
screenshot('-respawn');

// Jump onto the key ledge, activate its checkpoint, and return to the hall.
buttons(RIGHT); until(() => actor('x') >= 44);
buttons(RIGHT, A); until(() => !actor('grounded'));
until(() => actor('grounded') && actor('y') === 184);
buttons(RIGHT); until(() => variable('keys') === 1); buttons(); frames(6);
assert.equal(variable('room_1_checkpoint_player'), 1);
assert.equal(actor('visible', 10), 0);
screenshot('-checkpoint');
buttons(LEFT); until(() => actor('x') <= 24 && actor('y') === 208 && actor('grounded')); enter(0);
assert.equal(variable('keys'), 1);
buttons(RIGHT); until(() => actor('x') >= 140); buttons(); frames(5);
buttons(B); until(() => variable('room_0_sequence_guide_thanks_step') === 2); frames(4);
assert.deepEqual(textAt(2, 17, 18), encoded('YOU FOUND THE KEY!'));
buttons(A); until(() => !variable('room_0_sequence_guide_thanks_active')); buttons(); frames(4);
buttons(RIGHT); until(() => actor('x') >= 216); enter(2);
buttons(RIGHT); until(() => actor('x') >= 216); buttons(UP); until(() => variable('won') === 1);
buttons(); until(() => read('fx_music_current_song') === 1);
until(() => !variable('room_2_sequence_ending_active')); frames(6);
assert.deepEqual(textAt(5, 17, 22), encoded('YOU WIN! PRESS START'.padEnd(22)));
screenshot('-victory');
const victory = state();
assert.ok(maxAmplitude > .05 && audioSamples > 10000, 'music/effects produce emulator audio');
assert.ok(pitches.size >= 3, 'the music changes notes on pulse channel 2');
buttons(START); until(() => room() === 0); buttons(); frames(12);
assert.deepEqual([variable('keys'), variable('won'), variable('deaths')], [0, 0, 0]);
assert.equal(read('fx_music_current_song'), 0, 'restart restores exploration music');
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', totalFrames,
  victory, maxAmplitude, musicPitches: pitches.size, screenshots }, null, 2));
