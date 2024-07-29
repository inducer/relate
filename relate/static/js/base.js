import './jquery-importer';
import jQuery from 'jquery';
import * as bootstrap from 'bootstrap';

import select2 from 'select2';
import * as rlUtils from './rlUtils';
import * as bsUtils from './bsUtils';

import 'htmx.org';

import '../css/base.scss';

select2(jQuery);

document.addEventListener('DOMContentLoaded', () => {
  // document.body is not available until the DOM is loaded.
  document.body.addEventListener('htmx:responseError', (evt) => {
    bsUtils.showToast(
      `HTMX request failed: ${evt.detail.xhr.status}:
      ${evt.detail.xhr.statusText}
      (${evt.detail.xhr.responseURL})`,
    );
  });
});

globalThis.rlUtils = rlUtils;
globalThis.bsUtils = bsUtils;
globalThis.bootstrap = bootstrap;
