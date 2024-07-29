// FIXME: blueimp-tmpl is deprecated. Only used in flow-page and grade-flow-page.
import tmpl from 'blueimp-tmpl';

import './base';
import 'jstree';
import 'video.js';

import '../css/base-with-markup.css';

window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
  },
};
