/*
 * WattWise -- small animation helpers shared by index.html and results.html.
 * No frameworks, no build step -- plain DOM/requestAnimationFrame, kept easy
 * to explain line-by-line in viva.
 */

/**
 * Animates a number counting up from 0 to `target` inside `el`.
 * Preserves any non-numeric prefix/suffix already in the element's text
 * (e.g. "₹3650" keeps the ₹, "45/100" keeps the "/100").
 */
function wattwiseCountUp(el, target, opts) {
  opts = opts || {};
  const duration = opts.duration || 900;
  const decimals = opts.decimals || 0;
  const prefix = opts.prefix || "";
  const suffix = opts.suffix || "";

  if (typeof target !== "number" || isNaN(target)) return;

  const start = performance.now();
  const from = 0;

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    // ease-out cubic -- fast start, gentle settle, feels less mechanical
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = from + (target - from) * eased;
    el.textContent = prefix + value.toFixed(decimals) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/**
 * Scans elements with [data-countup] and animates each one.
 * Expects data-countup="1234.5" data-decimals="0" data-prefix="₹" data-suffix="%"
 */
function wattwiseInitCountUps(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-countup]").forEach(function (el) {
    const target = parseFloat(el.getAttribute("data-countup"));
    wattwiseCountUp(el, target, {
      decimals: parseInt(el.getAttribute("data-decimals") || "0", 10),
      prefix: el.getAttribute("data-prefix") || "",
      suffix: el.getAttribute("data-suffix") || "",
      duration: 900,
    });
  });
}

/** Animate .bar-fill elements to their real width (CSS starts them at 0). */
function wattwiseInitBars(root) {
  const scope = root || document;
  scope.querySelectorAll(".bar-fill[data-width]").forEach(function (el, i) {
    setTimeout(function () {
      el.style.width = el.getAttribute("data-width") + "%";
    }, 150 + i * 80);
  });
}

document.addEventListener("DOMContentLoaded", function () {
  wattwiseInitCountUps();
  wattwiseInitBars();
});
