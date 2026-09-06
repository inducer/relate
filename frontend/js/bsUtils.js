import * as bootstrap from 'bootstrap';

export function showToast(
  msg,
  title,
  { autohide = true, spinner = false } = {},
) {
  const errorToast = document.getElementById('relate-ui-toast');
  document.getElementById('relate-ui-toast-body').innerHTML = msg;
  if (title) {
    document.getElementById('relate-ui-toast-title').innerHTML = title;
  }
  if (spinner) {
    const indicator = document.createElement('span');
    indicator.className = 'spinner-border spinner-border-sm me-2';
    indicator.setAttribute('aria-hidden', 'true');
    document.getElementById('relate-ui-toast-body').prepend(indicator);
  }
  const existingToast = bootstrap.Toast.getInstance(errorToast);
  if (existingToast) {
    existingToast.dispose();
  }
  const toast = new bootstrap.Toast(errorToast, { autohide, animation: false });
  toast.show();
}

export function hideToast() {
  const toast = bootstrap.Toast.getInstance(
    document.getElementById('relate-ui-toast'),
  );
  if (toast) {
    toast.hide();
  }
}
