import './base';
import 'jstree';
import 'video.js';

import '../css/base-with-markup.css';

window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
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
};
