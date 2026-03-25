import './base';
import 'jstree';
import 'video.js';

import '../css/base-with-markup.css';

// Pre-built regex patterns for recognized matrix environments (global flag for all matches)
const MATRIX_PATTERNS = [
  'pmatrix',
  'bmatrix',
  'vmatrix',
  'Vmatrix',
  'Bmatrix',
  'matrix',
  'smallmatrix',
].map(
  (env) =>
    new RegExp(`\\\\begin\\{${env}\\}([\\s\\S]*?)\\\\end\\{${env}\\}`, 'g'),
);

/**
 * Convert a LaTeX matrix environment body (between \begin{env} and \end{env})
 * into a numpy array literal.
 * Rows are delimited by \\ and columns by &.
 */
function matrixBodyToNumpy(body) {
  const rows = body
    .split(/\\\\(?:\[[^\]]*\])?/)
    .map((row) => row.trim())
    .filter((row) => row.length > 0);
  const rowStrings = rows.map((row) => {
    const cols = row.split('&').map((el) => el.trim());
    return `[${cols.join(', ')}]`;
  });
  return `np.array([${rowStrings.join(', ')}])`;
}

/**
 * Given a TeX source string, return newline-joined NumPy array literals for
 * all matrix environments found (in document order), or null if none found.
 */
function latexToNumpyCode(tex) {
  // Collect all matches with their positions so we can sort by document order.
  const hits = [];
  for (const p of MATRIX_PATTERNS) {
    p.lastIndex = 0;
    let m;
    while ((m = p.exec(tex)) !== null) {
      hits.push({ index: m.index, body: m[1] });
    }
  }

  // Also handle \begin{array}{cols}...\end{array}
  const arrayPattern = /\\begin\{array\}\{[^}]*\}([\s\S]*?)\\end\{array\}/g;
  let am;
  while ((am = arrayPattern.exec(tex)) !== null) {
    hits.push({ index: am.index, body: am[1] });
  }

  if (hits.length === 0) {
    return null;
  }

  hits.sort((a, b) => a.index - b.index);
  return hits.map(({ body }) => matrixBodyToNumpy(body)).join('\n');
}

/**
 * Copy text to the clipboard.  Falls back to execCommand when the Clipboard
 * API is unavailable (e.g. non-secure contexts).
 */
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for non-secure contexts
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:absolute;left:-9999px;top:-9999px';
  document.body.appendChild(ta);
  ta.select();
  try {
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (!ok) {
      return Promise.reject(new Error('execCommand copy returned false'));
    }
    return Promise.resolve();
  } catch (err) {
    document.body.removeChild(ta);
    return Promise.reject(err);
  }
}

/**
 * For every displayed MathJax math item whose TeX source contains a matrix
 * environment, insert a small "Copy as NumPy" button immediately after the
 * rendered container element.
 */
const numpyButtonText = 'Copy matrices in numpy format';

function addNumpyCopyButtons() {
  const mjax = window.MathJax;
  const doc = mjax && mjax.startup && mjax.startup.document;
  if (!doc) {
    return;
  }

  for (const mathItem of doc.math) {
    if (!mathItem.display) {
      continue;
    }

    const numpyCode = latexToNumpyCode(mathItem.math);
    if (!numpyCode) {
      continue;
    }

    const root = mathItem.typesetRoot;
    if (!root) {
      continue;
    }

    // Avoid adding the button more than once (e.g. after re-typesetting).
    if (
      root.nextElementSibling &&
      root.nextElementSibling.classList.contains('relate-numpy-copy')
    ) {
      continue;
    }

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'relate-numpy-copy btn btn-sm btn-outline-secondary';
    btn.textContent = numpyButtonText;
    btn.title = numpyCode;
    let resetTimeoutId;

    btn.addEventListener('click', () => {
      copyText(numpyCode)
        .then(() => {
          btn.textContent = 'Copied!';
          if (resetTimeoutId) {
            clearTimeout(resetTimeoutId);
          }
          resetTimeoutId = setTimeout(() => {
            btn.textContent = numpyButtonText;
          }, 2000);
        })
        .catch((err) => {
          // biome-ignore lint/suspicious/noConsole: intentional error logging
          console.error('relate: failed to copy NumPy code:', err);
          btn.textContent = 'Copy failed';
          if (resetTimeoutId) {
            clearTimeout(resetTimeoutId);
          }
          resetTimeoutId = setTimeout(() => {
            btn.textContent = numpyButtonText;
          }, 2000);
        });
    });

    root.insertAdjacentElement('afterend', btn);
  }
}

window.MathJax = {
  tex: {
    inlineMath: [
      ['$', '$'],
      ['\\(', '\\)'],
    ],
    displayMath: [
      ['$$', '$$'],
      ['\\[', '\\]'],
    ],
  },
  // based on https://github.com/mathjax/MathJax/issues/3436#issuecomment-3481724702
  loader: {
    paths: {
      fonts: '[mathjax]',
      'mathjax-mhchem-extension': '[fonts]/mathjax-mhchem-font-extension',
      'mathjax-bbm-extension': '[fonts]/mathjax-bbm-font-extension',
      'mathjax-bboldx-extension': '[fonts]/mathjax-bboldx-font-extension',
      'mathjax-dsfont-extension': '[fonts]/mathjax-dsfont-font-extension',
    },
  },
  options: {
    processHtmlClass: 'relate-markup',
  },
  startup: {
    ready() {
      window.MathJax.startup.defaultReady();
      window.MathJax.startup.promise.then(() => {
        addNumpyCopyButtons();
      });
    },
  },
};
