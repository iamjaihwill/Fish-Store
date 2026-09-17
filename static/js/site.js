/* Progressive enhancement only: every feature below works without JS,
   these just remove a page load or a tap. */
(function () {
  "use strict";

  // Mobile navigation
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("primary-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  // Filter drawer on small screens
  var filterToggle = document.querySelector("[data-toggle-filters]");
  var filters = document.getElementById("filters");
  if (filterToggle && filters) {
    filterToggle.addEventListener("click", function () {
      filters.classList.toggle("is-open");
    });
  }

  // Sort select submits its form
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () {
      el.form.submit();
    });
  });

  // Product gallery
  var gallery = document.querySelector("[data-gallery]");
  var mainImage = document.getElementById("gallery-main-image");
  if (gallery && mainImage) {
    gallery.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-src]");
      if (!button) return;
      mainImage.src = button.dataset.src;
      gallery.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-current", String(b === button));
      });
      var caption = document.getElementById("gallery-caption");
      if (caption) caption.textContent = button.dataset.caption || "";
    });
  }

  // Live sale countdowns
  document.querySelectorAll("[data-countdown]").forEach(function (el) {
    var target = new Date(el.dataset.countdown).getTime();
    if (isNaN(target)) return;
    var tick = function () {
      var delta = Math.max(0, target - Date.now());
      var seconds = Math.floor(delta / 1000);
      var parts = {
        days: Math.floor(seconds / 86400),
        hours: Math.floor((seconds % 86400) / 3600),
        minutes: Math.floor((seconds % 3600) / 60),
        seconds: seconds % 60
      };
      Object.keys(parts).forEach(function (unit) {
        var node = el.querySelector('[data-unit="' + unit + '"]');
        if (node) node.textContent = String(parts[unit]).padStart(2, "0");
      });
      if (delta === 0) clearInterval(timer);
    };
    tick();
    var timer = setInterval(tick, 1000);
  });
})();
