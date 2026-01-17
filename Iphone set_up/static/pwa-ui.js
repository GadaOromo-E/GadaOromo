// static/pwa-ui.js
// - Install button (Android/desktop)
// - iOS "Add to Home Screen" helper
// - Update prompt when a new SW is available

let deferredPrompt = null;

function isIOS() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}
function isInStandaloneMode() {
  return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
         (window.navigator.standalone === true);
}

function show(el) { if (el) el.style.display = ""; }
function hide(el) { if (el) el.style.display = "none"; }

function toast(msg) {
  const el = document.getElementById("pwaToast");
  if (!el) return alert(msg);
  el.querySelector("[data-msg]").textContent = msg;
  show(el);
  setTimeout(() => hide(el), 3500);
}

function showUpdateBanner(reg) {
  const bar = document.getElementById("pwaUpdateBar");
  if (!bar) return;

  show(bar);

  const btn = bar.querySelector("[data-reload]");
  if (btn) {
    btn.onclick = () => {
      // Tell SW to skip waiting if supported
      if (reg && reg.waiting) reg.waiting.postMessage({ type: "SKIP_WAITING" });
      // Reload after a short delay
      setTimeout(() => window.location.reload(), 250);
    };
  }

  const closeBtn = bar.querySelector("[data-close]");
  if (closeBtn) closeBtn.onclick = () => hide(bar);
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;

  const btn = document.getElementById("installBtn");
  if (btn && !isInStandaloneMode() && !isIOS()) show(btn);
});

window.addEventListener("appinstalled", () => {
  deferredPrompt = null;
  const btn = document.getElementById("installBtn");
  hide(btn);
  toast("App installed ✅");
});

async function handleInstallClick() {
  if (!deferredPrompt) return;

  deferredPrompt.prompt();
  const choice = await deferredPrompt.userChoice;
  deferredPrompt = null;

  if (choice && choice.outcome === "accepted") toast("Installing…");
  else toast("Install dismissed");
}

// iOS helper (shows instructions only on iPhone/iPad Safari when not installed)
function setupIOSInstallHelp() {
  const iosHelp = document.getElementById("iosInstallHelp");
  if (!iosHelp) return;

  if (isIOS() && !isInStandaloneMode()) show(iosHelp);
  else hide(iosHelp);
}

// SW registration + update detection
async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const reg = await navigator.serviceWorker.register("/static/sw.js");

    // If there's already a waiting SW, show update prompt
    if (reg.waiting) showUpdateBanner(reg);

    reg.addEventListener("updatefound", () => {
      const newWorker = reg.installing;
      if (!newWorker) return;

      newWorker.addEventListener("statechange", () => {
        if (newWorker.state === "installed") {
          // If there's a controller, then an update exists
          if (navigator.serviceWorker.controller) {
            showUpdateBanner(reg);
          }
        }
      });
    });

    // Listen for controllerchange (after SKIP_WAITING)
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // optional: toast("Updated ✅");
    });

  } catch (e) {
    // silent
  }
}

window.addEventListener("load", () => {
  // Install button click handler
  const btn = document.getElementById("installBtn");
  if (btn) {
    btn.onclick = handleInstallClick;
    // default hidden until event fires
    hide(btn);
  }

  setupIOSInstallHelp();
  registerServiceWorker();
});
