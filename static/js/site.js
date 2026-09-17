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

/* Instant search suggestions. The form still submits normally without JS. */
(function () {
  "use strict";
  var form = document.querySelector(".search[data-suggest-url]");
  if (!form) return;
  var input = form.querySelector('input[type="search"]');
  var box = form.querySelector(".suggest");
  if (!input || !box) return;

  var timer = null;
  var lastQuery = "";

  function hide() {
    box.hidden = true;
    box.innerHTML = "";
  }

  function render(results) {
    if (!results.length) return hide();
    box.innerHTML = results
      .map(function (item) {
        var badge = item.sold_out
          ? '<span class="suggest-tag">Sold out</span>'
          : item.wysiwyg
          ? '<span class="suggest-tag">WYSIWYG</span>'
          : "";
        var image = item.image
          ? '<img src="' + item.image + '" alt="" loading="lazy">'
          : '<span class="suggest-blank"></span>';
        return (
          '<a class="suggest-item" role="option" href="' + item.url + '">' +
          image +
          '<span class="suggest-name">' + item.name + badge + "</span>" +
          '<span class="suggest-price">$' + item.price + "</span></a>"
        );
      })
      .join("");
    box.hidden = false;
  }

  input.addEventListener("input", function () {
    var query = input.value.trim();
    window.clearTimeout(timer);
    if (query.length < 2) return hide();
    timer = window.setTimeout(function () {
      if (query === lastQuery) return;
      lastQuery = query;
      fetch(form.dataset.suggestUrl + "?q=" + encodeURIComponent(query), {
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (response) { return response.json(); })
        .then(function (data) { render(data.results || []); })
        .catch(hide);
    }, 180);
  });

  document.addEventListener("click", function (event) {
    if (!form.contains(event.target)) hide();
  });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Escape") hide();
  });
})();
