import Sparkline from 'sparklines';

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.relate-sparkline').forEach((el) => {
    const rawData = el.dataset.points;
    if (!rawData) {
      return;
    }
    const raw = JSON.parse(rawData);
    // Only include quartiles that have actual data (non-null).
    const available = raw
      .map((v, i) => ({ quartile: i + 1, pct: v === null ? null : v * 100 }))
      .filter((d) => d.pct !== null);
    if (available.length === 0) {
      return;
    }
    const points = available.map((d) => d.pct);
    Sparkline.draw(el, points, {
      width: 64,
      lineColor: '#0d6efd',
      startColor: 'transparent',
      endColor: 'transparent',
      minValue: 0,
      maxValue: 100,
      tooltip: (_value, index) =>
        `Q${available[index].quartile}: ${points[index].toFixed(1)}%`,
    });
  });
});
