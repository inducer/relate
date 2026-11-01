import { readFileSync } from 'node:fs';
import {
  parsePointsSpecs,
  sumPointsSpecs,
} from '../../frontend/js/pointsSpecs.mjs';

const text = JSON.parse(readFileSync(0, 'utf8'));

let response;
try {
  const specs = parsePointsSpecs(text);
  response = {
    result: process.argv[2] === 'sum' ? sumPointsSpecs(specs) : specs,
  };
} catch (error) {
  response = { error: error.message };
}

process.stdout.write(JSON.stringify(response));
