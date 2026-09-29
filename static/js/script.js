document.addEventListener('DOMContentLoaded', function () {
  const toggles = document.querySelectorAll('[data-toggle-password]');
  toggles.forEach((button) => {
    button.addEventListener('click', function () {
      const targetId = button.getAttribute('data-toggle-password');
      const input = document.getElementById(targetId);
      if (!input) return;
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      button.textContent = visible ? 'Show' : 'Hide';
    });
  });

  const upiRadio = document.getElementById('upi');
  const upiFields = document.getElementById('upi-fields');
  if (upiRadio && upiFields) {
    const toggleUpi = () => {
      const show = upiRadio.checked;
      upiFields.style.display = show ? 'block' : 'none';
      const submitButton = document.querySelector('button[type="submit"]');
      if (submitButton) {
        submitButton.textContent = show ? 'Pay using UPI' : 'Place COD Order';
      }
    };
    upiRadio.addEventListener('change', toggleUpi);
    document.getElementById('cod')?.addEventListener('change', toggleUpi);
    toggleUpi();
  }
});
