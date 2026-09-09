// Controller-only playthrough of PNG/Tiled art and fractional movement in a complete NES emulator.
// Setup: npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// Run: node tools/visual_adventure_smoke.mjs [build/visual_adventure.nes]
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
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'visual_adventure.nes'));
const romBytes = fs.readFileSync(rom);
const chrStart = 16 + romBytes[4] * 16384;
const atlasPath = path.join(root, 'examples', 'assets', 'adventure', 'tiles.png');
const atlasBytes = fs.readFileSync(atlasPath);
const atlas = PNG.sync.read(atlasBytes);
// Read palette order from PNG metadata instead of assuming particular RGB colors.
const pngColors = new Map();
for (let offset = 8; offset < atlasBytes.length;) {
  const length = atlasBytes.readUInt32BE(offset), type = atlasBytes.toString('ascii', offset + 4, offset + 8);
  if (type === 'PLTE') {
    for (let index = 0; index < Math.min(length / 3, 4); index++) {
      pngColors.set(Array.from(atlasBytes.subarray(offset + 8 + index * 3, offset + 11 + index * 3)).join(','), index);
    }
  }
  offset += length + 12;
}
assert.ok(pngColors.size > 0, 'the example atlas uses indexed PNG colors');
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
nes.loadROM(romBytes);
const held = new Set();
const walkingLegTiles = new Set();
function buttons(...next) {
  for (const button of held) if (!next.includes(button)) nes.buttonUp(1, button);
  for (const button of next) if (!held.has(button)) nes.buttonDown(1, button);
  held.clear();
  for (const button of next) held.add(button);
}
function frames(count) {
  for (let i = 0; i < count; i++) {
    assert.ok(frameCount++ < 2000, 'playthrough must finish within 2000 video frames');
    nes.frame();
    if (held.has(Controller.BUTTON_RIGHT) || held.has(Controller.BUTTON_LEFT)) {
      walkingLegTiles.add(nes.ppu.spriteMem[9]);
    }
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
function atlasPixel(column, row, x, y) {
  const offset = ((row * 8 + y) * atlas.width + column * 8 + x) * 4;
  if (atlas.data[offset + 3] === 0) return 0;
  const value = pngColors.get(Array.from(atlas.data.subarray(offset, offset + 3)).join(','));
  assert.notEqual(value, undefined, 'visible PNG pixel belongs to its first four palette entries');
  return value;
}
function chrPixel(tile, x, y) {
  return ((romBytes[chrStart + tile * 16 + y] >> (7 - x)) & 1)
    | (((romBytes[chrStart + tile * 16 + y + 8] >> (7 - x)) & 1) << 1);
}
function assertAtlasTile(tile, column, row) {
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    assert.equal(chrPixel(tile, x, y), atlasPixel(column, row, x, y),
      `CHR tile ${tile} must preserve PNG tile (${column}, ${row}) pixel (${x}, ${y})`);
  }
}
function assertPlayerArt() {
  const sprite = snapshot.ppu.spriteMem;
  const step = actor(room() * 8, 'frame') ? 2 : 0;
  for (let part = 0; part < 4; part++) {
    assertAtlasTile(sprite[part * 4 + 1], step + part % 2, 1 + Math.floor(part / 2));
  }
  const visible = new Set();
  for (let y = sprite[0] + 1; y < sprite[0] + 17; y++) {
    for (let x = sprite[3]; x < sprite[3] + 16; x++) visible.add(pixels[y * 256 + x]);
  }
  assert.ok(visible.size >= 3, 'the imported player appears with its distinct source colors');
}
function assertRoomPalette(expectedPalette, atlasColumn) {
  const column = 16, row = 28;
  const attributes = snapshot.ppu.vramMem[0x23C0 + Math.floor(row / 4) * 8 + Math.floor(column / 4)];
  const shift = (row & 2 ? 4 : 0) + (column & 2 ? 2 : 0);
  assert.equal((attributes >> shift) & 3, expectedPalette, 'Tiled palette property reaches PPU attributes');
  const tile = snapshot.ppu.vramMem[0x2000 + row * 32 + column];
  assertAtlasTile(tile, atlasColumn, 0);
  const colors = new Set();
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
    const value = atlasPixel(atlasColumn, 0, x, y);
    const expected = snapshot.ppu.imgPalette[value ? expectedPalette * 4 + value : 0];
    const actual = pixels[(row * 8 + y) * 256 + column * 8 + x];
    assert.equal(actual, expected, `room ${room()} renders imported floor pixel (${x}, ${y}) in its selected palette`);
    colors.add(actual);
  }
  assert.ok(colors.size > 1, 'PNG floor texture reaches the rendered frame');
  return [...colors].sort();
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
assertPlayerArt();
const hallColors = assertRoomPalette(0, 0);
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
const gardenColors = assertRoomPalette(2, 1);
assert.notDeepEqual(gardenColors, hallColors, 'garden and hall use different hardware colors');
buttons(RIGHT);
until(() => actor(8, 'x') >= 44);
// Start before the ledge so the head clears its underside; hold A for full height.
buttons(RIGHT, A);
until(() => !actor(8, 'grounded'));
until(() => actor(8, 'grounded') && actor(8, 'y') === 184);
buttons(RIGHT);
until(() => variable('keys') === 1);
buttons();
frames(5);
assert.equal(variable('room_1_key_taken'), 1);
assert.equal(actor(10, 'visible'), 0);
assert.deepEqual(textAt(7, 4, 1), encoded('1'));
assert.deepEqual(textAt(5, 19, 22), encoded('KEY FOUND! RETURN LEFT'));
screenshots.push(screenshot('-garden'));

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
const towerColors = assertRoomPalette(3, 2);
assert.notDeepEqual(towerColors, hallColors, 'tower and hall use different hardware colors');
assert.notDeepEqual(towerColors, gardenColors, 'tower and garden use different hardware colors');
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
assert.equal(walkingLegTiles.size, 2, 'walking switches between both PNG leg poses in hardware OAM');
for (const column of [0, 2]) {
  assert.ok([...walkingLegTiles].some(tile => {
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      if (chrPixel(tile, x, y) !== atlasPixel(column, 2, x, y)) return false;
    }
    return true;
  }), `animation uses the imported leg pose at PNG column ${column}`);
}
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', videoFrames: frameCount,
  victory, maxAmplitude, walkingLegTiles: [...walkingLegTiles], screenshots }, null, 2));
