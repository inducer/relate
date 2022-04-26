import jQuery from 'jquery';

/* eslint-disable-next-line import/prefer-default-export */
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
    `<object data='${dataUrl}' type='${mimeType}' style='width:100%; height: 80vh;'>
    <p>(
    Your browser reported itself unable to render <tt>${dataUrl.mimeType}</tt> inline.
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

function convertUploadDataUrlToObjectUrl(dataUrl) {
  // https://code.google.com/p/chromium/issues/detail?id=69227#37
  const isWebKit = /WebKit/.test(navigator.userAgent);

  if (isWebKit) {
    // assume base64 encoding
    const binStr = atob(dataUrl.base64Data);

    // convert to binary in ArrayBuffer
    const buf = new ArrayBuffer(binStr.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < view.length; i += 1) {
      view[i] = binStr.charCodeAt(i);
    }

    const blob = new Blob([view], { type: dataUrl.mimeType });
    return webkitURL.createObjectURL(blob); // eslint-disable-line no-undef
  }
  return null;
}

export function enablePreviewForFileUpload() {
  const dataUrl = matchUploadDataURL(jQuery('#file_upload_download_link').attr('href'));
  const objUrl = convertUploadDataUrlToObjectUrl(dataUrl);

  if (objUrl) {
    jQuery('#file_upload_download_link').attr('href', objUrl);
  }

  if (dataUrl.mimeType === 'application/pdf') {
    embedUploadedFileViewer(dataUrl.mimeType, objUrl);
  }
}

// }}}

// vim: foldmethod=marker
