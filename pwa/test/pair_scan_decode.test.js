// The phone must be able to read the exact QR the desktop draws.
//
// iOS Safari has no BarcodeDetector, so scanning fell back to hand-typing a
// 62-character key — the primary way to connect a phone, on the platform
// where it was hardest. PairScan now loads jsQR when the native detector is
// missing; this test renders a pairing payload with the *desktop's* encoder
// (app/static/js/vendor/qrcode.js) and decodes it with jsQR, so the two ends
// are checked against each other rather than each against itself.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import jsQR from 'jsqr';
import { PAIRING_PREFIX } from '../src/lib/vault.js';

const here = dirname(fileURLToPath(import.meta.url));
const ENCODER = join(here, '../../app/static/js/vendor/qrcode.js');

// The vendor file is a plain script that defines `qrcode`; evaluate it and
// hand the factory back.
function loadDesktopEncoder() {
  const src = readFileSync(ENCODER, 'utf8');
  // eslint-disable-next-line no-new-func
  return new Function(`${src}; return qrcode;`)();
}

// Render the QR matrix into an RGBA bitmap the way a camera would see it:
// black modules on white, several pixels per module, with a quiet zone.
function toImageData(qr, { cellSize = 6, margin = 4 } = {}) {
  const modules = qr.getModuleCount();
  const size = (modules + margin * 2) * cellSize;
  const data = new Uint8ClampedArray(size * size * 4).fill(255);
  for (let r = 0; r < modules; r++) {
    for (let c = 0; c < modules; c++) {
      if (!qr.isDark(r, c)) continue;
      const x0 = (c + margin) * cellSize;
      const y0 = (r + margin) * cellSize;
      for (let y = y0; y < y0 + cellSize; y++) {
        for (let x = x0; x < x0 + cellSize; x++) {
          const i = (y * size + x) * 4;
          data[i] = data[i + 1] = data[i + 2] = 0;
        }
      }
    }
  }
  return { data, width: size, height: size };
}

function roundTrip(text, opts) {
  const qrcode = loadDesktopEncoder();
  const qr = qrcode(0, 'M');           // same parameters the sync page uses
  qr.addData(text);
  qr.make();
  const img = toImageData(qr, opts);
  return jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
}

describe('the phone decodes the desktop QR', () => {
  it('reads a full pairing payload', () => {
    const payload = PAIRING_PREFIX
      + '227BD-NZLU5-RYTKK-BX3N3-6BV3U-J4X3N-PZFHM-6PV2I-3AZTS-NOA6Z-WA';
    expect(roundTrip(payload)?.data).toBe(payload);
  });

  it('still reads it at a smaller module size, as on a phone held further away', () => {
    const payload = PAIRING_PREFIX
      + 'AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF-GGGGG-HHHHH-IIIII-JJJJJ-KK';
    expect(roundTrip(payload, { cellSize: 3, margin: 4 })?.data).toBe(payload);
  });
});
