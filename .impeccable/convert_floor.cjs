const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const source = path.resolve('f0', 'E Block - Ground Floor.svg');
const target = path.resolve('.impeccable', 'mocks', 'decision', 'ground-floor-reference.png');
fs.mkdirSync(path.dirname(target), { recursive: true });
sharp(source, { density: 180 })
  .resize({ width: 1600 })
  .png()
  .toFile(target)
  .then(() => process.stdout.write(target));
