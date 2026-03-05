import './jquery-importer';
import jQuery from 'jquery';
import * as bootstrap from 'bootstrap';

import TomSelect from 'tom-select';
import * as rlUtils from './rlUtils';
import * as bsUtils from './bsUtils';

import 'htmx.org';

import '../css/base.scss';

document.addEventListener('DOMContentLoaded', () => {
  // Initialize TomSelect on all plain <select> elements (i.e. those not already
  // handled by django-tomselect's own widget templates).
  document.querySelectorAll('select:not([data-tomselect-initialized])').forEach((el) => {
    // eslint-disable-next-line no-new
    new TomSelect(el, { allowEmptyOption: true });
  });

  // document.body is not available until the DOM is loaded.
  document.body.addEventListener('htmx:responseError', (evt) => {
    bsUtils.showToast(
      `HTMX request failed: ${evt.detail.xhr.status}:
      ${evt.detail.xhr.statusText}
      (${evt.detail.xhr.responseURL})`,
    );
  });
});

// Make TomSelect available globally so django-tomselect widget templates can use it.
globalThis.TomSelect = TomSelect;
globalThis.jQuery = jQuery;
globalThis.rlUtils = rlUtils;
globalThis.bsUtils = bsUtils;
globalThis.bootstrap = bootstrap;
