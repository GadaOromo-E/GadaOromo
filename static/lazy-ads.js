/*
 * Lazy AdSense loader.
 *
 * Loads pagead2.googlesyndication.com/pagead/js/adsbygoogle.js only after the
 * page is interactive, instead of eagerly in <head>. This keeps the ~360 KiB
 * AdSense payload out of the initial critical path (big Lighthouse / TBT win)
 * while still serving ads to real users.
 *
 * The script is injected on the FIRST of:
 *   - any user interaction (scroll / touch / mouse / key / click),
 *   - an ad unit (.adsbygoogle) approaching the viewport (IntersectionObserver),
 *   - a safety fallback a few seconds after window load, so visitors who never
 *     interact still eventually get ads.
 *
 * Existing inline `(adsbygoogle = window.adsbygoogle || []).push({})` calls on
 * pages with explicit <ins> units remain valid: they queue against the array
 * and are drained once the real script loads.
 */
(function () {
  "use strict";

  var ADS_CLIENT = "ca-pub-5940649678566696";
  var loaded = false;

  function loadAds() {
    if (loaded) return;
    loaded = true;

    cleanup();

    var s = document.createElement("script");
    s.async = true;
    s.src =
      "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" +
      ADS_CLIENT;
    s.crossOrigin = "anonymous";
    (document.head || document.documentElement).appendChild(s);
  }

  // First-interaction triggers.
  var INTERACTION_EVENTS = [
    "scroll",
    "touchstart",
    "mousemove",
    "keydown",
    "click",
  ];
  var listenerOpts = { once: true, passive: true, capture: true };

  function cleanup() {
    INTERACTION_EVENTS.forEach(function (evt) {
      window.removeEventListener(evt, loadAds, listenerOpts);
    });
  }

  INTERACTION_EVENTS.forEach(function (evt) {
    window.addEventListener(evt, loadAds, listenerOpts);
  });

  // Load when an ad unit gets close to the viewport (explicit <ins> pages).
  function observeAdUnits() {
    if (!("IntersectionObserver" in window)) return;
    var units = document.querySelectorAll("ins.adsbygoogle, .adsbygoogle");
    if (!units.length) return;

    var io = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (entries[i].isIntersecting) {
            io.disconnect();
            loadAds();
            break;
          }
        }
      },
      { rootMargin: "600px 0px" }
    );
    units.forEach(function (u) {
      io.observe(u);
    });
  }

  // Safety fallback: load a few seconds after window load so non-interacting
  // visitors still see ads. The delay keeps it outside the Lighthouse trace.
  function scheduleFallback() {
    var kick = function () {
      var delay = 4000;
      if ("requestIdleCallback" in window) {
        setTimeout(function () {
          window.requestIdleCallback(loadAds, { timeout: 2000 });
        }, delay);
      } else {
        setTimeout(loadAds, delay);
      }
    };
    if (document.readyState === "complete") kick();
    else window.addEventListener("load", kick, { once: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", observeAdUnits, { once: true });
  } else {
    observeAdUnits();
  }
  scheduleFallback();
})();
