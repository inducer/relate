import './jquery-importer';
import jQuery from 'jquery';
import * as bootstrap from 'bootstrap';

import select2 from 'select2';
import * as rlUtils from './rlUtils';
import * as bsUtils from './bsUtils';

import '../css/base.scss';

select2(jQuery);

globalThis.rlUtils = rlUtils;
globalThis.bsUtils = bsUtils;
globalThis.bootstrap = bootstrap;
