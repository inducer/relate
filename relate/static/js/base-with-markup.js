// FIXME: blueimp-tmpl is deprecated. Only used in flow-page and grade-flow-page.
import tmpl from 'blueimp-tmpl';

import './base';
import * as bootstrap from 'bootstrap';
import * as rlUtils from './rlUtils';
import 'jstree';
import 'video.js';

import '../css/base-with-markup.css';

window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
  },
};

export { rlUtils, tmpl, bootstrap };
