/* Autumn MCP pages (consent, add account, connections).
   Progressive enhancement only: every form here submits and works without
   this file. Nothing in it selects an account or grants a permission. */
(function () {
  "use strict";

  // Revoking and unlinking take effect immediately, so ask first.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form && form.getAttribute && form.getAttribute("data-mcp-confirm");
    if (message && !window.confirm(message)) event.preventDefault();
  });

  // Copy the server URL. The button stays hidden where the clipboard API is
  // unavailable; the URL itself is select-all on click either way.
  document.querySelectorAll("[data-mcp-copy]").forEach(function (button) {
    var source = document.getElementById(button.getAttribute("data-mcp-copy"));
    if (!source || !navigator.clipboard || !window.isSecureContext) return;
    var label = button.querySelector("[data-mcp-copy-label]");
    var status = document.querySelector("[data-mcp-copy-status]");
    var reset;
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(source.textContent.trim()).then(function () {
        if (label) label.textContent = "Copied";
        if (status) status.textContent = "Server URL copied.";
        clearTimeout(reset);
        reset = setTimeout(function () {
          if (label) label.textContent = "Copy";
          if (status) status.textContent = "";
        }, 2500);
      }, function () {
        if (status) status.textContent = "Couldn't copy. Select the URL and copy it instead.";
      });
    });
  });

  // Consent: mark the default account's row, and once the person changes
  // something, say plainly when the default and the ticked accounts disagree.
  // The server still validates; this only explains it sooner.
  var consent = document.querySelector("[data-mcp-consent]");
  if (!consent) return;
  var select = consent.querySelector('select[name="default_account"]');
  var boxes = consent.querySelectorAll('input[type="checkbox"][name="accounts"]');
  var accountsHint = consent.querySelector("[data-mcp-accounts-hint]");
  var defaultHint = consent.querySelector("[data-mcp-default-hint]");

  function say(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  function sync(explain) {
    var chosen = select ? select.value : "";
    var anyTicked = false;
    var defaultTicked = false;
    boxes.forEach(function (box) {
      var row = box.closest("[data-mcp-account]");
      var flag = row && row.querySelector("[data-mcp-default-flag]");
      var isDefault = chosen !== "" && box.value === chosen;
      if (flag) flag.hidden = !isDefault;
      if (box.checked) anyTicked = true;
      if (isDefault && box.checked) defaultTicked = true;
    });
    if (!explain) return;
    say(accountsHint, anyTicked ? "" : "No accounts are ticked. Tick at least one to connect.");
    var message = "";
    if (anyTicked && !chosen) {
      message = "Choose a default from the accounts you're sharing.";
    } else if (anyTicked && !defaultTicked) {
      message = "Your default isn't one of the accounts you're sharing. Tick it, or choose another default.";
    }
    say(defaultHint, message);
  }

  consent.addEventListener("change", function () { sync(true); });
  sync(false);
})();
