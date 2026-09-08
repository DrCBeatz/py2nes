// Full JSNES integration for the playable keys-and-platforms example.
// Setup: npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// Run: node tools/platformer_smoke.mjs [build/keys_and_platforms.nes]
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
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'keys_and_platforms.nes'));
const labels = new Map();
for (const line of fs.readFileSync(rom.replace(/\.nes$/i, '.lbl'), 'utf8').split('\n')) {
  const match = line.match(/^\s*al\s+([\da-f]+)\s+\.?([^\s]+)/i);
  if (match) labels.set(match[2], parseInt(match[1], 16));
}
let pixels, snapshot, frameCount = 0, soundSamples = 0, maxAmplitude = 0;
let captureJumpAudio = false;
const jumpAudio = [], animationFrames = new Set(), displayedFeet = new Set(), hazardPositions = new Set();
const nes = new NES({
  emulateSound: true,
  onFrame: frame => { pixels = Uint32Array.from(frame); },
  onAudioSample: (left, right) => {
    soundSamples++;
    if (captureJumpAudio) jumpAudio.push(left);
    maxAmplitude = Math.max(maxAmplitude, Math.abs(left), Math.abs(right));
  },
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
    assert.ok(frameCount++ < 1000, 'playthrough must finish within 1000 video frames');
    nes.frame();
  }
  snapshot = nes.toJSON();
  animationFrames.add(actor(0, 'frame'));
  displayedFeet.add(snapshot.ppu.spriteMem[9]);
  hazardPositions.add(actor(5, 'x'));
}
function read(name) {
  assert.ok(labels.has(name), `missing assembly symbol ${name}`);
  return snapshot.cpu.mem[labels.get(name)];
}
function variable(name) { return read(`v_${name}`); }
function actor(index, field) { return variable(`actor_${index}_${field}`); }
function signed(value) { return value < 128 ? value : value - 256; }
function state() {
  return { frameCount, x: actor(0, 'x'), y: actor(0, 'y'), vy: signed(actor(0, 'vy')),
    grounded: actor(0, 'grounded'), keys: variable('keys'), lives: variable('lives'),
    won: variable('won'), hazard: actor(5, 'x') };
}
function until(condition, maximum = 100) {
  for (let i = 0; i < maximum; i++) {
    if (condition()) return;
    frames(1);
  }
  assert.fail(`controller route did not reach expected state: ${JSON.stringify(state())}`);
}
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
function textAt(column, row, width) {
  return Array.from(snapshot.ppu.vramMem.slice(0x2000 + row * 32 + column,
    0x2000 + row * 32 + column + width));
}
function encoded(text) { return Array.from(text, character => character.charCodeAt(0) - 32); }
function pixelsAt(x, y, width, height) {
  return Array.from({ length: width * height }, (_, index) =>
    pixels[(y + Math.floor(index / width)) * 256 + x + index % width]);
}
const RIGHT = Controller.BUTTON_RIGHT;
const A = Controller.BUTTON_A;
frames(20);
assert.deepEqual([actor(0, 'x'), actor(0, 'y'), actor(0, 'grounded')], [24, 208, 1],
  'player starts standing on the floor');
assert.deepEqual([variable('keys'), variable('lives'), variable('won')], [0, 3, 0]);
assert.deepEqual([0, 1, 2, 3].map(index => snapshot.ppu.spriteMem[index * 4 + 3]),
  [24, 32, 24, 32], 'four hardware sprite parts have their expected X offsets');
assert.deepEqual([0, 1, 2, 3].map(index => snapshot.ppu.spriteMem[index * 4]),
  [207, 207, 215, 215], 'four sprite parts convert visible Y into OAM Y correctly');
assert.ok(new Set(pixelsAt(24, 208, 16, 16)).size >= 3, 'the four-part player renders colored graphics');
assert.deepEqual(textAt(2, 4, 23), encoded('KEYS:0/3        LIVES:3'), 'the complete initial HUD is in background VRAM');
const keyTile = snapshot.ppu.spriteMem[17];
const initialCounter = pixelsAt(56, 32, 8, 8);
const initialMessage = pixelsAt(48, 80, 160, 8);
const initialScreenshot = screenshot('');

// Walk to the first platform: the floor key is collected before jumping.
buttons(RIGHT);
until(() => actor(0, 'x') >= 56);
assert.equal(variable('keys'), 1, 'walk through the first key');
assert.equal(variable('key0_taken'), 1);
assert.equal(actor(1, 'visible'), 0);
assert.deepEqual(textAt(7, 4, 1), encoded('1'), 'the first collection updates the displayed counter');
assert.deepEqual(new Set(animationFrames), new Set([0, 1]), 'walking advances both animation frames');
assert.equal(displayedFeet.size, 2, 'both foot graphics reach the hardware OAM buffer');

// Release A and press it again while airborne. A new edge must not double-jump.
captureJumpAudio = true;
buttons(RIGHT, A);
frames(1);
assert.equal(signed(actor(0, 'vy')), -7, 'grounded A starts a jump before gravity');
assert.equal(actor(0, 'grounded'), 0);
buttons(RIGHT);
frames(1);
const velocityBeforeSecondPress = signed(actor(0, 'vy'));
const yBeforeSecondPress = actor(0, 'y');
buttons(RIGHT, A);
frames(1);
assert.equal(signed(actor(0, 'vy')), velocityBeforeSecondPress + 1, 'airborne A does not reset jump velocity');
assert.equal(actor(0, 'y'), yBeforeSecondPress + velocityBeforeSecondPress + 1);
buttons(RIGHT);
until(() => actor(0, 'grounded') && actor(0, 'y') === 184);
captureJumpAudio = false;
assert.ok(actor(0, 'x') + 14 > 72, 'first landing overlaps the first solid platform');
assert.equal(variable('lives'), 3);
assert.ok(jumpAudio.length > 1000, 'the emulator produces audio samples during the jump');
assert.ok(Math.max(...jumpAudio) - Math.min(...jumpAudio) > 0.01,
  'the jump tone produces a changing, nonzero audio waveform');

// Walk along platform one, then jump across the gap to platform two.
until(() => actor(0, 'x') >= 116);
assert.equal(variable('keys'), 2, 'the second key is collected on platform one');
assert.equal(variable('key1_taken'), 1);
assert.deepEqual(textAt(7, 4, 1), encoded('2'));
buttons(RIGHT, A);
frames(1);
buttons(RIGHT);
until(() => actor(0, 'grounded') && actor(0, 'y') === 160);
assert.ok(actor(0, 'x') + 14 > 136, 'second landing overlaps the second solid platform');
until(() => actor(0, 'x') >= 168);
assert.equal(variable('keys'), 3, 'all three keys are collected with controller input');
assert.equal(variable('key2_taken'), 1);

// Leap from the upper platform, clearing the moving floor hazard, to the exit.
buttons(RIGHT, A);
frames(1);
buttons(RIGHT);
until(() => variable('won') === 1);
buttons();
frames(8); // Let the longer win message drain across vblanks and render.
assert.equal(variable('lives'), 3, 'the successful route avoids the hazard without damage');
assert.equal(variable('lost'), 0);
assert.deepEqual(textAt(2, 4, 23), encoded('KEYS:3/3        LIVES:3'), 'the final HUD is committed to PPU memory');
assert.deepEqual(textAt(30, 25, 1), [keyTile], 'collecting all keys adds the background exit marker');
assert.deepEqual(textAt(6, 10, 20), encoded('YOU WIN! PRESS START'), 'the complete win message reaches PPU memory');
assert.notDeepEqual(pixelsAt(56, 32, 8, 8), initialCounter, 'the framebuffer renders the changed key counter');
assert.notDeepEqual(pixelsAt(48, 80, 160, 8), initialMessage, 'the framebuffer renders the new win message');
for (let index = 1; index <= 3; index++) {
  assert.equal(actor(index, 'visible'), 0, `collected key ${index} is hidden`);
  assert.equal(snapshot.ppu.spriteMem[(index + 3) * 4], 255, `key ${index} is hidden in hardware OAM`);
}
assert.ok(hazardPositions.size > 20, 'the hazard patrols during gameplay');
assert.ok([...hazardPositions].every(x => x >= 168 && x <= 208), 'patrol turns around at its boundaries');
assert.ok(soundSamples > 0 && maxAmplitude > 0.05, 'sound reaches the emulator audio output');
const victoryScreenshot = screenshot('-victory');
const victory = state();
const stoppedX = actor(0, 'x');
buttons(RIGHT, A);
frames(6);
assert.equal(actor(0, 'x'), stoppedX, 'winning disables movement');
assert.equal(actor(0, 'y'), 208, 'winning disables jumping');

buttons(Controller.BUTTON_START);
frames(1);
buttons();
frames(8);
assert.deepEqual([variable('keys'), variable('lives'), variable('won'), variable('lost')], [0, 3, 0, 0],
  'Start resets counters and end-state flags');
assert.deepEqual([actor(0, 'x'), actor(0, 'y'), actor(0, 'grounded')], [24, 208, 1], 'Start returns the player to the floor');
assert.deepEqual(textAt(2, 4, 23), encoded('KEYS:0/3        LIVES:3'), 'restart resets the complete HUD');
assert.deepEqual(textAt(30, 25, 1), [0], 'restart removes the background exit marker');
assert.deepEqual(textAt(6, 10, 20), Array(20).fill(0), 'restart clears the win message');
for (let index = 1; index <= 3; index++) {
  assert.equal(variable(`key${index - 1}_taken`), 0);
  assert.equal(actor(index, 'visible'), 1, 'restart restores each collectible');
  assert.notEqual(snapshot.ppu.spriteMem[(index + 3) * 4], 255, 'restored key is visible in hardware OAM');
}
buttons(RIGHT);
frames(3);
assert.ok(actor(0, 'x') > 24, 'the restarted game accepts movement again');
buttons();
// A second route deliberately walks beneath platform two into the hazard.
// Each hit must consume exactly one life, respawn, and eventually show game over.
for (let expectedLives = 2; expectedLives >= 0; expectedLives--) {
  buttons(RIGHT);
  until(() => actor(0, 'x') >= 56);
  buttons(RIGHT, A);
  frames(1);
  buttons(RIGHT);
  until(() => actor(0, 'grounded') && actor(0, 'y') === 184);
  until(() => variable('lives') === expectedLives, 120);
  buttons();
  frames(5);
  assert.deepEqual([actor(0, 'x'), actor(0, 'y')], [24, 208], 'hazard damage respawns the player');
  assert.equal(variable('lost'), Number(expectedLives === 0));
  assert.deepEqual(textAt(24, 4, 1), encoded(String(expectedLives)), 'damage updates the visible life counter');
  if (expectedLives > 0) until(() => variable('invincible') === 0, 70);
}
assert.deepEqual(textAt(6, 10, 20), encoded('GAME OVER. START'.padEnd(20)), 'losing shows the complete game-over message');
buttons(RIGHT, A);
frames(5);
assert.deepEqual([actor(0, 'x'), actor(0, 'y')], [24, 208], 'game over disables player movement');
buttons(Controller.BUTTON_START);
frames(1);
buttons();
frames(8);
assert.deepEqual([variable('keys'), variable('lives'), variable('won'), variable('lost')], [0, 3, 0, 0],
  'Start also restarts after game over');
assert.deepEqual(textAt(6, 10, 20), Array(20).fill(0), 'restart clears the game-over message');
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', videoFrames: frameCount,
  victory, soundSamples, maxAmplitude, initialScreenshot, victoryScreenshot }, null, 2));
