import './jquery-importer';
import jQuery from 'jquery';
import * as bootstrap from 'bootstrap';

import select2 from 'select2';
import * as rlUtils from './rlUtils';

import '../css/base.scss';

select2(jQuery);

/* eslint-disable-next-line import/prefer-default-export */
export { rlUtils, bootstrap };
