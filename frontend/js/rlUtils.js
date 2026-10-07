import jQuery from 'jquery';

export function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; ++i) {
      const cookie = jQuery.trim(cookies[i]);
      // Does this cookie string begin with the name we want?
      if (cookie.substring(0, name.length + 1) === `${name}=`) {
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
    // biome-ignore lint/correctness/noUndeclaredVariables: WebKit-specific browser global
    return webkitURL.createObjectURL(blob);
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

export function enablePreviewForNotebookUpload() {
  document
    .querySelectorAll('.relate-notebook-preview[data-preview-url]')
    .forEach((preview) => {
      if (preview.dataset.initialized) {
        return;
      }
      preview.dataset.initialized = 'true';
      const status = preview.querySelector('.relate-notebook-status');
      const container = preview.querySelector('.relate-notebook-frame');
      // Fail closed: this is a conservative support test, not proof of CSP enforcement.
      if (
        !('sandbox' in document.createElement('iframe')) ||
        typeof window.SecurityPolicyViolationEvent !== 'function' ||
        typeof window.URL !== 'function'
      ) {
        status.textContent = status.dataset.unsupported;
        return;
      }

      let url;
      try {
        url = new URL(preview.dataset.previewUrl, window.location.href);
      } catch {
        status.textContent = status.dataset.error;
        return;
      }
      const channel = url.searchParams.get('channel');
      if (
        url.origin !== window.location.origin ||
        !/^[A-Za-z0-9_-]{32,128}$/.test(channel || '')
      ) {
        status.textContent = status.dataset.error;
        return;
      }

      const frame = document.createElement('iframe');
      frame.setAttribute('sandbox', 'allow-scripts');
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.title = container.dataset.title;
      frame.style.width = '100%';
      frame.style.border = '0';
      frame.style.height = '600px';
      status.textContent = status.dataset.loading;
      let ready = false;
      let pendingHeight = null;
      let resizeTimer = null;
      let failed = false;
      const timeout = window.setTimeout(() => {
        failed = true;
        status.textContent = status.dataset.error;
        frame.remove();
        window.removeEventListener('message', onMessage);
        if (resizeTimer !== null) {
          window.clearTimeout(resizeTimer);
        }
      }, 30000);

      function onMessage(event) {
        const message = event.data;
        if (
          failed ||
          event.source !== frame.contentWindow ||
          event.origin !== 'null' ||
          message === null ||
          typeof message !== 'object' ||
          Array.isArray(message) ||
          Object.keys(message).length !== 3 ||
          message.type !== 'relate-notebook-resize' ||
          message.channel !== channel ||
          typeof message.height !== 'number' ||
          !Number.isFinite(message.height)
        ) {
          return;
        }
        if (!ready) {
          ready = true;
          window.clearTimeout(timeout);
          status.textContent = status.dataset.ready;
        }
        pendingHeight = Math.max(
          100,
          Math.min(6000, Math.ceil(message.height)),
        );
        // Apply at most ten resizes/second, retaining the latest valid height.
        if (resizeTimer === null) {
          resizeTimer = window.setTimeout(() => {
            frame.style.height = `${pendingHeight}px`;
            resizeTimer = null;
          }, 100);
        }
      }

      window.addEventListener('message', onMessage);
      // HTTP error documents cannot be inspected across the opaque-origin boundary.
      // Only the trusted child's validated message marks a successful load.
      frame.src = url.href;
      container.appendChild(frame);
      preview.querySelector('.relate-notebook-standalone').hidden = false;
    });
}

// }}}

// {{{ grading ui: next/previous points field

// based on https://codemirror.net/addon/search/searchcursor.js (MIT)

const pointsRegexp = /\[pts:/g;

export function goToNextPointsField(view) {
  pointsRegexp.lastIndex = view.state.selection.main.head;
  const match = pointsRegexp.exec(view.state.doc.toString());
  if (match) {
    view.dispatch({ selection: { anchor: match.index + match[0].length } });
    return true;
  }
  return false;
}

// based on https://stackoverflow.com/a/274094
function regexLastMatch(string, regex, startpos) {
  if (!regex.global) {
    throw new Error('Passed regex not global');
  }

  let start;
  if (typeof startpos === 'undefined') {
    start = string.length;
  } else if (startpos < 0) {
    start = 0;
  } else {
    start = startpos;
  }

  const stringToWorkWith = string.substring(0, start);
  let match;
  let lastMatch = null;
  regex.lastIndex = 0;

  while ((match = regex.exec(stringToWorkWith)) != null) {
    lastMatch = match;
    regex.lastIndex = match.index + 1;
  }
  return lastMatch;
}

export function goToPreviousPointsField(view) {
  const match = regexLastMatch(
    view.state.doc.toString(),
    pointsRegexp,
    // "[pts:" is five characters
    view.state.selection.main.head - 5,
  );

  if (match) {
    view.dispatch({ selection: { anchor: match.index + match[0].length } });
    return true;
  }
  return false;
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
  const pointsBodyRegex =
    /^([-0-9.]*)\s*((?:\/\s*[-0-9.]*)?)\s*((?:#[a-zA-Z_]\w*)?)\s*$/;

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

// http://stackoverflow.com/a/30558011
const SURROGATE_PAIR_REGEXP = /[\uD800-\uDBFF][\uDC00-\uDFFF]/g;
// Match everything outside of normal chars and " (quote character)
const NON_ALPHANUMERIC_REGEXP = /([^#-~| |!])/g;

export function encodeEntities(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(SURROGATE_PAIR_REGEXP, (val) => {
      const hi = val.charCodeAt(0);
      const low = val.charCodeAt(1);
      return `&#${((hi - 0xd800) * 0x400) + (low - 0xdc00) + 0x10000};`;
    })
    .replace(NON_ALPHANUMERIC_REGEXP, (val) => `&#${val.charCodeAt(0)};`)
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export function truncateText(s, length) {
  if (s.length > length) {
    return `${s.slice(0, length)}...`;
  }
  return s;
}

// vim: foldmethod=marker
