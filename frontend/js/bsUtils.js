import * as bootstrap from 'bootstrap';

export function showToast(msg, title) {
  const errorToast = document.getElementById('relate-ui-toast');
  document.getElementById('relate-ui-toast-body').innerHTML = msg;
  if (title) {
    document.getElementById('relate-ui-toast-title').innerHTML = title;
  }
  const toast = new bootstrap.Toast(errorToast);
  toast.show();
}
