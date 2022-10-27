import jQuery from 'jquery';

export function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; ++i) { /* eslint-disable-line no-plusplus */
      const cookie = jQuery.trim(cookies[i]);
      // Does this cookie string begin with the name we want?
      if (cookie.substring(0, name.length + 1) === (name + '=')) { /* eslint-disable-line prefer-template */
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

// {{{ file upload support

function embedUploadedFileViewer(mimeType, dataUrl) {
  jQuery('#file_upload_viewer_div').html(
    `<object id="file_upload_viewer" data='${dataUrl}' type='${mimeType}' style='width:100%; height: 80vh;'>
    <p>(
    Your browser reported itself unable to render <tt>${mimeType}</tt> inline.
    )</p>
    </object>`,
  );
}

function matchUploadDataURL(dataUrl) {
  // take apart data URL
  const parts = dataUrl.match(/data:([^;]*)(;base64)?,([0-9A-Za-z+/]+)/);
  return {
    mimeType: parts[1],
    encoding: parts[2],
    base64Data: parts[3],
  };
}

function convertUploadDataUrlToObjectUrl(dataUrlParts) {
  // https://code.google.com/p/chromium/issues/detail?id=69227#37
  const isWebKit = /WebKit/.test(navigator.userAgent);

  if (isWebKit) {
    // assume base64 encoding
    const binStr = atob(dataUrlParts.base64Data);

    // convert to binary in ArrayBuffer
    const buf = new ArrayBuffer(binStr.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < view.length; i += 1) {
      view[i] = binStr.charCodeAt(i);
    }

    const blob = new Blob([view], { type: dataUrlParts.mimeType });
    return webkitURL.createObjectURL(blob); // eslint-disable-line no-undef
  }
  return null;
}

export function enablePreviewForFileUpload() {
  let dataUrl = document.getElementById('file_upload_download_link').href;
  const dataUrlParts = matchUploadDataURL(dataUrl);

  const objUrl = convertUploadDataUrlToObjectUrl(dataUrlParts);
  if (objUrl) {
    dataUrl = objUrl;
  }

  jQuery('#file_upload_download_link').attr('href', dataUrl);

  if (dataUrlParts.mimeType === 'application/pdf') {
    embedUploadedFileViewer(dataUrlParts.mimeType, dataUrl);
  }
}

// }}}

// {{{ grading ui: next/previous points field

// based on https://codemirror.net/addon/search/searchcursor.js (MIT)

export function goToNextPointsField(cm) {
  const regexp = /\[pts:/g;
  for (let { line, ch } = cm.getCursor(), last = cm.lastLine(); line <= last; line += 1, ch = 0) {
    regexp.lastIndex = ch;
    const string = cm.getLine(line);
    const match = regexp.exec(string);
    if (match) {
      cm.setCursor({ line, ch: match.index + match[0].length });
      return;
    }
  }
}

function lastMatchIn(string, regexp, endMargin) {
  let match;
  let from = 0;
  while (from <= string.length) {
    // eslint-disable-next-line no-param-reassign
    regexp.lastIndex = from;
    const newMatch = regexp.exec(string);
    if (!newMatch) break;
    const end = newMatch.index + newMatch[0].length;
    if (end > string.length - endMargin) break;
    if (!match || end > match.index + match[0].length) {
      match = newMatch;
    }
    from = newMatch.index + 1;
  }
  return match;
}

export function goToPreviousPointsField(cm) {
  const cursor = cm.getCursor();
  const regexp = /\[pts:/g;

  for (let { line, ch } = cursor, first = cm.firstLine(); line >= first; line -= 1, ch = -1) {
    const string = cm.getLine(line);
    const match = lastMatchIn(string, regexp, ch < 0 ? 0 : string.length - ch);
    if (match) {
      const newCh = match.index + match[0].length;
      if (line !== cursor.line || ch !== newCh) {
        cm.setCursor({ line, ch: newCh });
        return;
      }
    }
  }
}

// }}}

// {{{ grading UI: points spec processing

function parseFloatRobust(s) {
  const result = Number.parseFloat(s);
  if (Number.isNaN(result)) {
    throw new Error(`Numeral not understood: ${s}`);
  }
  return result;
}

export function parsePointsSpecs(feedbackText) {
  const result = [];
  const pointsRegex = /\[pts:\s*([^\]]*)\]/g;
  const pointsBodyRegex = /^([-0-9.]*)\s*((?:\/\s*[-0-9.]*)?)\s*((?:#[a-zA-Z_]\w*)?)\s*$/;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const bodyMatch = pointsRegex.exec(feedbackText);
    if (bodyMatch === null) {
      break;
    }

    const pointsBody = bodyMatch[1];
    const match = pointsBody.match(pointsBodyRegex);
    if (match === null) {
      throw new Error(`Points spec not understood: '${pointsBody}'`);
    }

    const [_fullMatch, pointsStr, maxPointsStr, identifierStr] = match;
    let points = null;
    if (pointsStr.length) {
      points = parseFloatRobust(pointsStr);
    }

    let maxPoints = null;
    if (maxPointsStr.length) {
      maxPoints = parseFloatRobust(maxPointsStr.substring(1));
      if (maxPoints <= 0) {
        throw new Error(`Point denominator must be positive: '${pointsBody}'`);
      }
    }

    let identifier = null;
    if (identifierStr.length) {
      identifier = identifierStr;
    }

    result.push({
      points,
      maxPoints,
      identifier,
      matchStart: bodyMatch.index,
      matchLength: bodyMatch[0].length,
    });
  }

  return result;
}

// }}}

// vim: foldmethod=marker
