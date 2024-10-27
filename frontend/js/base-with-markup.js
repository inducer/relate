import './base';
import 'jstree';
import 'video.js';

import '../css/base-with-markup.css';

window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
  },
  options: {
    processHtmlClass: 'relate-markup',
  },
};
