/* static/pwa-ui.js */
(() => {
  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  // --- Toast ---
  const toast = document.getElementById("pwaToast");
  function showToast(msg, vibeMs = 0) {
    try {
      if (vibeMs && "vibrate" in navigator) navigator.vibrate(vibeMs);
    } catch (_) {}

    if (!toast) return;
    const msgEl = toast.querySelector("[data-msg]");
    if (msgEl) msgEl.textContent = msg;

    toast.style.display = "block";
    toast.style.opacity = "1";

    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => (toast.style.display = "none"), 200);
    }, 2200);
  }

  // --- Install button (Android/Desktop) ---
  const installBtn = document.getElementById("installBtn");
  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBtn) installBtn.style.display = "inline-block";
  });

  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      installBtn.style.display = "none";
      if (choice && choice.outcome === "accepted") showToast("Installed ✅", 30);
    });
  }

  // --- iOS install helper ---
  const iosHelp = document.getElementById("iosInstallHelp");
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);

  if (iosHelp && isIOS && isSafari && !isStandalone) {
    iosHelp.style.display = "block";
  }

  // --- Service Worker registration + update prompt ---
  const updateBar = document.getElementById("pwaUpdateBar");

  function showUpdateBar(reg) {
    if (!updateBar) return;
    updateBar.style.display = "block";

    const reloadBtn = updateBar.querySelector("[data-reload]");
    const closeBtn = updateBar.querySelector("[data-close]");

    if (reloadBtn) {
      reloadBtn.onclick = () => {
        try {
          reg.waiting?.postMessage({ type: "SKIP_WAITING" });
        } catch (_) {}
        showToast("Updating…", 15);
        setTimeout(() => location.reload(), 350);
      };
    }
    if (closeBtn) closeBtn.onclick = () => (updateBar.style.display = "none");
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
      try {
        const reg = await navigator.serviceWorker.register("/static/sw.js");

        // If already waiting, show bar
        if (reg.waiting) showUpdateBar(reg);

        reg.addEventListener("updatefound", () => {
          const newWorker = reg.installing;
          if (!newWorker) return;

          newWorker.addEventListener("statechange", () => {
            if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
              showUpdateBar(reg);
              showToast("New version ready ✅", 20);
            }
          });
        });

        // Listen for SW messages
        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event?.data?.type === "OFFLINE_READY") {
            showToast("Offline ready ✅", 10);
          }
        });
      } catch (e) {
        // ignore
      }
    });
  }

  // --- “native tap” haptics everywhere ---
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!t) return;

    const clickable = t.closest && t.closest("button, a, .chip");
    if (!clickable) return;

    // small haptic on mobile only
    const isMobile = /android|iphone|ipad|ipod/i.test(navigator.userAgent);
    if (isMobile) {
      try {
        if ("vibrate" in navigator) navigator.vibrate(8);
      } catch (_) {}
    }
  }, { passive: true });
})();

