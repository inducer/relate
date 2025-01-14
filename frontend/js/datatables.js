/* eslint-disable func-names */

import './base';
import jQuery from 'jquery';

import datatables from 'datatables.net';

import datatablesBs from 'datatables.net-bs5/js/dataTables.bootstrap5';
import 'datatables.net-bs5/css/dataTables.bootstrap5.css';

import datatablesFixedColumns from 'datatables.net-fixedcolumns/js/dataTables.fixedColumns';
import 'datatables.net-fixedcolumns-bs5/css/fixedColumns.bootstrap5.css';
import 'datatables.net-fixedcolumns-bs5/js/fixedColumns.bootstrap5';

/* eslint-disable camelcase, import/extensions */
import language_es_CO from 'datatables.net-plugins/i18n/es-CO.mjs';
import language_es_CL from 'datatables.net-plugins/i18n/es-CL.mjs';
import language_es_MX from 'datatables.net-plugins/i18n/es-MX.mjs';
import language_ca from 'datatables.net-plugins/i18n/ca.mjs';
import language_en_GB from 'datatables.net-plugins/i18n/en-GB.mjs';
import language_pt_BR from 'datatables.net-plugins/i18n/pt-BR.mjs';
import language_it_IT from 'datatables.net-plugins/i18n/it-IT.mjs';
import language_fr_FR from 'datatables.net-plugins/i18n/fr-FR.mjs';
import language_nl_NL from 'datatables.net-plugins/i18n/nl-NL.mjs';
import language_fa from 'datatables.net-plugins/i18n/fa.mjs';
import language_ru from 'datatables.net-plugins/i18n/ru.mjs';
import language_pl from 'datatables.net-plugins/i18n/pl.mjs';
import language_zh from 'datatables.net-plugins/i18n/zh.mjs';
import language_he from 'datatables.net-plugins/i18n/he.mjs';
import language_ar from 'datatables.net-plugins/i18n/ar.mjs';
import language_ro from 'datatables.net-plugins/i18n/ro.mjs';
import language_lv from 'datatables.net-plugins/i18n/lv.mjs';
import language_vi from 'datatables.net-plugins/i18n/vi.mjs';
import language_es_ES from 'datatables.net-plugins/i18n/es-ES.mjs';
import language_km from 'datatables.net-plugins/i18n/km.mjs';
import language_sr_SP from 'datatables.net-plugins/i18n/sr-SP.mjs';
import language_lt from 'datatables.net-plugins/i18n/lt.mjs';
import language_cs from 'datatables.net-plugins/i18n/cs.mjs';
import language_sk from 'datatables.net-plugins/i18n/sk.mjs';
import language_sv_SE from 'datatables.net-plugins/i18n/sv-SE.mjs';
import language_id from 'datatables.net-plugins/i18n/id.mjs';
import language_tr from 'datatables.net-plugins/i18n/tr.mjs';
import language_pt_PT from 'datatables.net-plugins/i18n/pt-PT.mjs';
import language_de_DE from 'datatables.net-plugins/i18n/de-DE.mjs';
import language_sq from 'datatables.net-plugins/i18n/sq.mjs';
import language_da from 'datatables.net-plugins/i18n/da.mjs';
import language_zh_HANT from 'datatables.net-plugins/i18n/zh-HANT.mjs';
import language_bn from 'datatables.net-plugins/i18n/bn.mjs';
import language_hu from 'datatables.net-plugins/i18n/hu.mjs';
import language_th from 'datatables.net-plugins/i18n/th.mjs';
import language_eu from 'datatables.net-plugins/i18n/eu.mjs';
import language_no_NB from 'datatables.net-plugins/i18n/no-NB.mjs';
import language_hr from 'datatables.net-plugins/i18n/hr.mjs';
import language_uz from 'datatables.net-plugins/i18n/uz.mjs';
import language_el from 'datatables.net-plugins/i18n/el.mjs';
import language_gl from 'datatables.net-plugins/i18n/gl.mjs';
import language_uk from 'datatables.net-plugins/i18n/uk.mjs';
import language_ka from 'datatables.net-plugins/i18n/ka.mjs';
import language_bg from 'datatables.net-plugins/i18n/bg.mjs';
import language_sl from 'datatables.net-plugins/i18n/sl.mjs';
import language_az_AZ from 'datatables.net-plugins/i18n/az-AZ.mjs';
/* eslint-enable camelcase, import/extensions */

function stripLanguageTag(localeId) {
  const hyphenPos = localeId.indexOf('-');
  if (hyphenPos !== -1) {
    return localeId.substring(0, hyphenPos);
  }
  return null;
}

function addFallbacks(tbl) {
  const newtbl = { ...tbl };
  Object.keys(tbl).forEach((localeId) => {
    const strippedId = stripLanguageTag(localeId);
    if (strippedId) {
      if (!(strippedId in newtbl)) {
        newtbl[strippedId] = tbl[localeId];
      }
    }
  });
  return newtbl;
}

/* eslint-disable camelcase, quote-props */
const i18nTables = addFallbacks({
  'es-CO': language_es_CO,
  'es-CL': language_es_CL,
  'es-MX': language_es_MX,
  'ca': language_ca,
  'en-GB': language_en_GB,
  'pt-BR': language_pt_BR,
  'it-IT': language_it_IT,
  'fr-FR': language_fr_FR,
  'nl-NL': language_nl_NL,
  'fa': language_fa,
  'ru': language_ru,
  'pl': language_pl,
  'zh': language_zh,
  'he': language_he,
  'ar': language_ar,
  'ro': language_ro,
  'lv': language_lv,
  'vi': language_vi,
  'es-ES': language_es_ES,
  'km': language_km,
  'sr-SP': language_sr_SP,
  'lt': language_lt,
  'cs': language_cs,
  'sk': language_sk,
  'sv-SE': language_sv_SE,
  'id': language_id,
  'tr': language_tr,
  'pt-PT': language_pt_PT,
  'de-DE': language_de_DE,
  'sq': language_sq,
  'da': language_da,
  'zh-HANT': language_zh_HANT,
  'bn': language_bn,
  'hu': language_hu,
  'th': language_th,
  'eu': language_eu,
  'no-NB': language_no_NB,
  'hr': language_hr,
  'uz': language_uz,
  'el': language_el,
  'gl': language_gl,
  'uk': language_uk,
  'ka': language_ka,
  'bg': language_bg,
  'sl': language_sl,
  'az-AZ': language_az_AZ,
});
/* eslint-enable camelcase, quote-props */

datatables(window, jQuery);
datatablesBs(window, jQuery);
datatablesFixedColumns(window, jQuery);

// eslint-disable-next-line import/prefer-default-export
export function getI18nTable(localeId) {
  if (localeId in i18nTables) {
    return i18nTables[localeId];
  }

  const strippedId = stripLanguageTag(localeId);
  if (strippedId in i18nTables) {
    return i18nTables[strippedId];
  }
  return null;
}

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

// raw list of datatables translations with 'good' completion, from
// https://datatables.net/plug-ins/i18n/:

// es-CO
// es-CL
// es-MX
// ca
// en-GB
// pt-BR
// it-IT
// fr-FR
// nl-NL
// fa
// ru
// pl
// zh
// he
// ar
// ro
// lv
// vi
// es-ES
// km
// sr-SP
// lt
// cs
// sk
// sv-SE
// id
// tr
// pt-PT
// de-DE
// sq
// da
// zh-HANT
// bn
// hu
// th
// eu
// no-NB
// hr
// uz
// el
// gl
// uk
// ka
// bg
// sl
// az-AZ

// vim: foldmethod=marker
