// Small progressive enhancements. Every page works without this file.
(function () {
  // Hover tooltips for chart marks (elements with data-tip).
  var tip = null;
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (!el) { if (tip) { tip.remove(); tip = null; } return; }
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; document.body.appendChild(tip); }
    tip.textContent = el.getAttribute("data-tip");
  });
  document.addEventListener("mousemove", function (e) {
    if (tip) { tip.style.left = e.clientX + 12 + "px"; tip.style.top = e.clientY - 30 + "px"; }
  });

  // Live character counter for SMS text.
  document.querySelectorAll("textarea[data-count]").forEach(function (ta) {
    var out = document.getElementById(ta.getAttribute("data-count"));
    var max = parseInt(ta.getAttribute("maxlength") || "0", 10);
    function update() { out.textContent = ta.value.length + (max ? " / " + max : "") + " characters"; }
    ta.addEventListener("input", update);
    update();
  });

  // Confirm before irreversible actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // Show the resolution choice only when resolving.
  document.querySelectorAll("form[data-respond]").forEach(function (f) {
    var res = f.querySelector("[data-resolution]");
    function sync() {
      var k = f.querySelector("input[name=kind]:checked");
      if (res) res.hidden = !(k && k.value === "resolved");
    }
    f.addEventListener("change", sync);
    sync();
  });
})();
