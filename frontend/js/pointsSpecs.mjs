function parseFloatRobust(s) {
  const result = Number.parseFloat(s);
  if (Number.isNaN(result)) {
    throw new Error(`Numeral not understood: ${s}`);
  }
  return result;
}

export function parsePointsSpecs(feedbackText) {
  const result = [];
  const pointsRegex = /\[pts:\s*([^\]]*)\]/g;
  const pointsBodyRegex =
    /^([-0-9.]*)\s*((?:\/\s*[-0-9.]*)?)\s*((?:#[a-zA-Z_]\w*)?)\s*$/;

  while (true) {
    const bodyMatch = pointsRegex.exec(feedbackText);
    if (bodyMatch === null) {
      break;
    }

    const pointsBody = bodyMatch[1];
    const match = pointsBody.match(pointsBodyRegex);
    if (match === null) {
      throw new Error(`Points spec not understood: '${pointsBody}'`);
    }

    const [_fullMatch, pointsStr, maxPointsStr, identifierStr] = match;
    let points = null;
    if (pointsStr.length) {
      points = parseFloatRobust(pointsStr);
    }

    let maxPoints = null;
    if (maxPointsStr.length) {
      maxPoints = parseFloatRobust(maxPointsStr.substring(1));
      if (maxPoints <= 0) {
        throw new Error(`Point denominator must be positive: '${pointsBody}'`);
      }
    }

    let identifier = null;
    if (identifierStr.length) {
      identifier = identifierStr;
    }

    result.push({
      points,
      maxPoints,
      identifier,
      matchStart: bodyMatch.index,
      matchLength: bodyMatch[0].length,
    });
  }

  return result;
}

// Totals stay null when no corresponding values occur in the specs.
export function sumPointsSpecs(pointsSpecs) {
  let points = null;
  let maxPoints = null;

  for (const pspec of pointsSpecs) {
    if (pspec.points === null) {
      throw new Error(
        'Not applying points total when a pts spec ' +
          'is missing a point value.',
      );
    }
    points = (points === null ? 0 : points) + pspec.points;
    if (pspec.maxPoints !== null) {
      maxPoints = (maxPoints === null ? 0 : maxPoints) + pspec.maxPoints;
    }
  }

  return { points, maxPoints };
}
