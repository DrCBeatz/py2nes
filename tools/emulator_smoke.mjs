// Full-emulator smoke check for examples/hello_nes.py, with rendered PNG output.
// Setup: npm install --prefix build/emulator jsnes@2.1.0 pngjs@7.0.0
// Run: node tools/emulator_smoke.mjs [build/hello_nes.nes]
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependencyPaths = [path.join(root, 'build', 'emulator'), root];
// Use the ESM entry: jsnes 2.1.0's CommonJS distribution has no exports on Node 22.
const jsnesEntry = require.resolve('jsnes', { paths: dependencyPaths });
const { NES, Controller } = await import(pathToFileURL(path.resolve(path.dirname(jsnesEntry), '../src/index.js')));
const { PNG } = require(require.resolve('pngjs', { paths: dependencyPaths }));
const rom = path.resolve(process.argv[2] || path.join(root, 'build', 'hello_nes.nes'));
let pixels;
const nes = new NES({ emulateSound: false, onFrame: frame => { pixels = Uint32Array.from(frame); } });
nes.loadROM(fs.readFileSync(rom));
function frames(count) { for (let i = 0; i < count; i++) nes.frame(); }
function oam() { return nes.toJSON().ppu.spriteMem; }
function screenshot(suffix) {
  const png = new PNG({ width: 256, height: 240 });
  for (let i = 0; i < pixels.length; i++) {
    // JSNES's native framebuffer stores the red channel in the low byte.
    png.data[i * 4] = pixels[i] & 255;
    png.data[i * 4 + 1] = (pixels[i] >>> 8) & 255;
    png.data[i * 4 + 2] = (pixels[i] >>> 16) & 255;
    png.data[i * 4 + 3] = 255;
  }
  const output = rom.replace(/\.nes$/i, '') + suffix + '.png';
  fs.writeFileSync(output, PNG.sync.write(png));
  return output;
}
function tap(button, count = 1) {
  nes.buttonDown(1, button);
  frames(count);
  nes.buttonUp(1, button);
  frames(2); // Allow the main-loop / next-vblank pipeline to commit.
}
frames(20);
assert.equal(oam()[3], 80, 'initial X');
assert.equal(oam()[0], 80, 'initial Y');
for (let i = 1; i < 64; i++) assert.equal(oam()[i * 4], 255, 'unused sprite hidden');
assert.ok(new Set(pixels).size >= 4, 'frame should contain text and colored graphics');
const textPixels = [];
for (let y = 16; y < 24; y++) for (let x = 16; x < 88; x++) textPixels.push(pixels[y * 256 + x]);
assert.ok(new Set(textPixels).size >= 2, 'HELLO NES text must render');
const initialTile = oam()[1];
const initialScreenshot = screenshot('');
tap(Controller.BUTTON_RIGHT, 60);
assert.equal(oam()[3], 140, 'right held for 60 frames moves 60 pixels');
tap(Controller.BUTTON_LEFT, 20);
assert.equal(oam()[3], 120, 'left movement');
tap(Controller.BUTTON_UP, 10);
assert.equal(oam()[0], 70, 'up movement');
tap(Controller.BUTTON_DOWN, 5);
assert.equal(oam()[0], 75, 'down movement');
tap(Controller.BUTTON_A, 5);
assert.notEqual(oam()[1], initialTile, 'A changes the character');
const movedScreenshot = screenshot('-moved');
tap(Controller.BUTTON_B);
assert.equal(oam()[1], initialTile, 'B restores the character');
tap(Controller.BUTTON_START);
assert.equal(oam()[3], 80, 'Start resets X');
assert.equal(oam()[0], 80, 'Start resets Y');
const atRest = Array.from(oam().slice(0, 4));
frames(120);
assert.deepEqual(Array.from(oam().slice(0, 4)), atRest, 'released inputs stay idle');
console.log(JSON.stringify({ emulator: 'JSNES', rom, checks: 'passed', initialScreenshot, movedScreenshot }, null, 2));
