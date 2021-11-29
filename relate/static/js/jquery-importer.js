// This ensures that the '$' and jQuery aliases are set before other modules
// use them.

import jQuery from 'jquery';

window.$ = jQuery;
window.jQuery = jQuery;
