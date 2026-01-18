/* static/pwa-ui.js */
(() => {
  const isStandalone =
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;

  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isMobile = /android|iphone|ipad|ipod/i.test(navigator.userAgent);
  const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);

  // ---------- Small helpers ----------
  function vibrate(msOrPattern) {
    try {
      if (!isMobile) return;
      if (!("vibrate" in navigator)) return;
      navigator.vibrate(msOrPattern);
    } catch (_) {}
  }

  // ---------- Ensure Toast exists (so no HTML break) ----------
  function ensureToastEl() {
    let toast = document.getElementById("pwaToast");
    if (toast) return toast;

    toast = document.createElement("div");
    toast.id = "pwaToast";
    toast.style.position = "fixed";
    toast.style.left = "50%";
    toast.style.bottom = "18px";
    toast.style.transform = "translateX(-50%)";
    toast.style.background = "rgba(20,20,20,0.92)";
    toast.style.color = "#fff";
    toast.style.padding = "10px 14px";
    toast.style.borderRadius = "14px";
    toast.style.boxShadow = "0 10px 30px rgba(0,0,0,.35)";
    toast.style.maxWidth = "min(92vw, 520px)";
    toast.style.zIndex = "99999";
    toast.style.display = "none";
    toast.style.opacity = "0";
    toast.style.transition = "opacity 160ms ease";
    toast.innerHTML = `<span data-msg></span>`;
    document.body.appendChild(toast);
    return toast;
  }

  const toast = ensureToastEl();

  function showToast(msg, vibeMs = 0, durationMs = 2600) {
    if (!toast) return;
    if (vibeMs) vibrate(vibeMs);

    const msgEl = toast.querySelector("[data-msg]");
    if (msgEl) msgEl.textContent = msg;

    toast.style.display = "block";
    requestAnimationFrame(() => (toast.style.opacity = "1"));

    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => (toast.style.display = "none"), 200);
    }, durationMs);
  }

  // ---------- Splash overlay (Android-like) ----------
  // Only show when installed (standalone) so it feels like a real app.
  function showSplashIfStandalone() {
    if (!isStandalone) return;

    const splash = document.createElement("div");
    splash.style.position = "fixed";
    splash.style.inset = "0";
    splash.style.zIndex = "99998";
    splash.style.background = "#0b5cff";
    splash.style.display = "flex";
    splash.style.alignItems = "center";
    splash.style.justifyContent = "center";

    splash.innerHTML = `
      <div style="text-align:center; color:#fff; padding:18px;">
        <div style="
          width:84px; height:84px; border-radius:22px;
          background: rgba(255,255,255,0.16);
          display:inline-flex; align-items:center; justify-content:center;
          margin-bottom:14px;
        ">
          <span style="font-size:34px;">📘</span>
        </div>
        <div style="font-size:20px; font-weight:700;">${document.title || "Gada"}</div>
        <div style="opacity:.9; font-size:13px; margin-top:6px;">Loading…</div>
      </div>
    `;
    document.body.appendChild(splash);

    window.addEventListener(
      "load",
      () => {
        setTimeout(() => splash.remove(), 420);
      },
      { once: true }
    );
  }

  // ---------- Native-like transitions ----------
  // Adds a small fade-out on internal navigation
  function enableTransitions() {
    // ensure body has transition style (safe even if you already set in CSS)
    document.body.style.transition = document.body.style.transition || "opacity 140ms ease";

    window.addEventListener("pageshow", () => {
      document.body.classList.remove("page-fade-out");
      document.body.style.opacity = "1";
    });

    document.addEventListener(
      "click",
      (e) => {
        const a = e.target && e.target.closest ? e.target.closest("a") : null;
        if (!a) return;

        const href = a.getAttribute("href") || "";
        if (!href || href.startsWith("#")) return;
        if (a.target === "_blank") return;
        if (href.startsWith("http")) return; // external

        // Same-origin internal
        if (href.startsWith("/")) {
          e.preventDefault();
          vibrate(10);
          document.body.classList.add("page-fade-out");
          document.body.style.opacity = "0";
          setTimeout(() => (window.location.href = href), 110);
        }
      },
      { passive: false }
    );
  }

  // ---------- Install button (Android/Desktop) ----------
  const installBtn = document.getElementById("installBtn");
  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;

    // show install button if exists + show a toast prompt
    if (installBtn) installBtn.style.display = "inline-block";
    showToast("Install this app for faster access.", 10, 3500);
  });

  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      vibrate(12);
      if (!deferredPrompt) {
        if (isIOS && !isStandalone) {
          showToast("On iPhone: Share → Add to Home Screen", 10, 5500);
        } else {
          showToast("Install not available yet. Try again later.", 10);
        }
        return;
      }
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      installBtn.style.display = "none";
      if (choice && choice.outcome === "accepted") showToast("Installed ✅", 30);
      else showToast("Install canceled", 10);
    });
  }

  // ---------- iOS install helper (uses your existing element if present) ----------
  const iosHelp = document.getElementById("iosInstallHelp");
  if (iosHelp && isIOS && isSafari && !isStandalone) {
    iosHelp.style.display = "block";
  } else if (isIOS && !isStandalone) {
    // If you don't have iosHelp element, show once as toast (safe)
    const key = "gada_ios_a2hs_seen";
    if (!localStorage.getItem(key)) {
      setTimeout(() => {
        showToast("On iPhone: Share → Add to Home Screen to install.", 0, 6500);
        localStorage.setItem(key, "1");
      }, 1200);
    }
  }

  // ---------- Service Worker registration + update prompt ----------
  const updateBar = document.getElementById("pwaUpdateBar");

  function showUpdateBar(reg) {
    if (!updateBar) {
      // fallback toast if update bar not present in HTML
      showToast("Update available — reload to get latest version.", 10, 5000);
      return;
    }

    updateBar.style.display = "block";

    const reloadBtn = updateBar.querySelector("[data-reload]");
    const closeBtn = updateBar.querySelector("[data-close]");

    if (reloadBtn) {
      reloadBtn.onclick = () => {
        vibrate(15);
        try {
          reg.waiting?.postMessage({ type: "SKIP_WAITING" });
        } catch (_) {}
        showToast("Updating…", 10, 1200);
        setTimeout(() => location.reload(), 350);
      };
    }
    if (closeBtn) closeBtn.onclick = () => (updateBar.style.display = "none");
  }

  // IMPORTANT: your app.py serves SW at /service-worker.js (root)
  const SW_URL = "/service-worker.js";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
      try {
        const reg = await navigator.serviceWorker.register(SW_URL);

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

        navigator.serviceWorker.addEventListener("message", (event) => {
          if (event?.data?.type === "OFFLINE_READY") showToast("Offline ready ✅", 10);
        });
      } catch (_) {
        // ignore
      }
    });
  }

  // ---------- Background sync (optional) ----------
  // NOTE (important): true offline re-upload of AUDIO FILES is hard because storing blobs
  // reliably needs IndexedDB + bigger code. This version only notifies user.
  // If you want full offline audio queue, tell me and I’ll add IndexedDB-based queue.
  window.addEventListener("offline", () => {
    showToast("You are offline. Some uploads may fail.", 10, 3500);
  });
  window.addEventListener("online", () => {
    showToast("Back online ✅", 10, 2500);
  });

  // ---------- Haptic “native tap” ----------
  document.addEventListener(
    "click",
    (e) => {
      const t = e.target;
      if (!t) return;
      const clickable = t.closest && t.closest("button, a, .chip");
      if (!clickable) return;
      vibrate(8);
    },
    { passive: true }
  );

  // Boot
  showSplashIfStandalone();
  enableTransitions();
})();

