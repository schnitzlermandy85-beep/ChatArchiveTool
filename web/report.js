/* Static progressive enhancement. Report content is already rendered server-side. */
(() => {
  'use strict';
  const printButton = document.getElementById('print-report');
  if (printButton) printButton.addEventListener('click', () => window.print());
})();
