/* eslint-disable func-names */

import './base';
import jQuery from 'jquery';

import datatables from 'datatables.net';

import datatablesBs from 'datatables.net-bs5/js/dataTables.bootstrap5';
import 'datatables.net-bs5/css/dataTables.bootstrap5.css';

import datatablesFixedColumns from 'datatables.net-fixedcolumns/js/dataTables.fixedColumns';
import 'datatables.net-fixedcolumns-bs5/css/fixedColumns.bootstrap5.css';
import 'datatables.net-fixedcolumns-bs5/js/fixedColumns.bootstrap5';

datatables(window, jQuery);
datatablesBs(window, jQuery);
datatablesFixedColumns(window, jQuery);

// {{{ custom sort

function removeTags(s) {
  return s.replace(/(<([^>]+)>)/g, '');
}

jQuery.extend(jQuery.fn.dataTableExt.oSort, {
  'name-asc': function (s1, s2) {
    return removeTags(s1).localeCompare(removeTags(s2));
  },

  'name-desc': function (s1, s2) {
    return removeTags(s2).localeCompare(removeTags(s1));
  },
});

// }}}

// vim: foldmethod=marker
