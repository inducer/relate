import {
  parsePointsSpecs,
  sumPointsSpecs,
} from '../../frontend/js/pointsSpecs.mjs';

// Consume subprocess pipes through Node's cross-platform stream API.
process.stdin.setEncoding('utf8');
let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
}
const text = JSON.parse(input);

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
