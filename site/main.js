const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
const minJerk = (t) => t * t * t * (10 + t * (-15 + 6 * t));

class Spring {
  constructor(x = 0, k = 300, c = 30) { this.x = x; this.v = 0; this.target = x; this.k = k; this.c = c; }
  step(dt) {
    let t = Math.min(dt, 0.064);
    while (t > 0) { const h = Math.min(t, 1 / 240); const a = this.k * (this.target - this.x) - this.c * this.v; this.v += a * h; this.x += this.v * h; t -= h; }
  }
}
const damp = (k, ratio = 1) => 2 * Math.sqrt(k) * ratio;

function initHero() {
  const hero = document.querySelector(".hero");
  requestAnimationFrame(() => requestAnimationFrame(() => hero?.classList.add("in")));
  const svg = document.querySelector(".hero-mark svg");
  const dot = document.getElementById("heroDot");
  const trail = document.getElementById("heroTrail");
  if (!svg || !dot || !trail || reducedMotion()) return;
  const glides = [[[300, 470], [700, 590], 70], [[710, 370], [390, 520], -60], [[300, 610], [660, 440], 0]];
  let visible = true;
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }).observe(svg);
  const waitVisible = async () => { while (!visible || document.hidden) await sleep(250); };
  const bez = ([a, b, bend], u) => { const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1, cx = mx - dy / len * bend, cy = my + dx / len * bend, iu = 1 - u; return [iu * iu * a[0] + 2 * iu * u * cx + u * u * b[0], iu * iu * a[1] + 2 * iu * u * cy + u * u * b[1]]; };
  const draw = (glide, u0, u1, scale, alpha) => { const points = []; for (let i = 0; i <= 24; i++) { const p = bez(glide, u0 + (u1 - u0) * i / 24); points.push(`${p[0].toFixed(1)} ${p[1].toFixed(1)}`); } trail.setAttribute("d", `M${points.join(" L")}`); trail.setAttribute("stroke-opacity", (0.1 * Math.max(0, alpha)).toFixed(3)); const head = bez(glide, u1); dot.setAttribute("cx", head[0].toFixed(1)); dot.setAttribute("cy", head[1].toFixed(1)); dot.setAttribute("r", (74 * scale).toFixed(1)); dot.setAttribute("fill-opacity", (0.62 * Math.max(0, alpha)).toFixed(3)); };
  async function run(ms, springs, paint) { const start = performance.now(); let last = start; for (;;) { const now = await nextFrame(), dt = (now - last) / 1000; last = now; springs.forEach((s) => s.step(dt)); const f = Math.min(1, (now - start) / ms); paint(f); if (f >= 1) return; } }
  async function glide(glidePath) { const scale = new Spring(0.8, 420, damp(420, 0.6)), alpha = new Spring(0, 260, damp(260)); scale.target = 1; alpha.target = 1; await run(240, [scale, alpha], () => draw(glidePath, 0, 0, scale.x, alpha.x)); await run(950, [scale, alpha], (f) => draw(glidePath, 0, minJerk(f), scale.x, alpha.x)); }
  async function lift(glidePath) { const tail = new Spring(0, 110, damp(110)); tail.target = 1; await run(480, [tail], () => draw(glidePath, Math.min(1, tail.x), 1, 1, 1)); const scale = new Spring(1, 300, damp(300)), alpha = new Spring(1, 200, damp(200)); scale.target = 1.14; alpha.target = 0; await run(380, [scale, alpha], () => draw(glidePath, 1, 1, scale.x, alpha.x)); draw(glidePath, 1, 1, 1, 0); }
  (async () => { await sleep(1800); for (;;) { await waitVisible(); await lift(glides[2]); for (let i = 0; i < glides.length; i++) { await sleep(i ? 360 : 520); await waitVisible(); await glide(glides[i]); if (i < glides.length - 1) { await sleep(180); await lift(glides[i]); } } await sleep(4200); } })();
}

function initReveals() {
  const elements = [...document.querySelectorAll(".reveal")];
  if (reducedMotion()) { elements.forEach((element) => element.classList.add("in")); return; }
  const observer = new IntersectionObserver((entries) => { let delay = 0; entries.forEach((entry) => { if (!entry.isIntersecting) return; entry.target.style.setProperty("--d", `${delay++ * 70}ms`); entry.target.classList.add("in"); observer.unobserve(entry.target); }); }, { rootMargin: "0px 0px -12% 0px" });
  elements.forEach((element) => observer.observe(element));
}

function initNav() {
  const nav = document.querySelector("[data-nav]"), links = document.querySelector(".gn-links"), indicator = document.querySelector(".nav-ind"), tops = [...document.querySelectorAll(".gn-top")], darks = [...document.querySelectorAll("[data-dark]")], button = document.querySelector("[data-menu-button]"), sheet = document.querySelector("[data-menu]");
  if (!nav) return;
  const place = (link) => { if (!link || !links || !indicator) { if (indicator) indicator.style.opacity = "0"; return; } const scale = links.getBoundingClientRect().width / links.offsetWidth || 1; indicator.style.width = `${link.offsetWidth}px`; indicator.style.transform = `translateX(${(link.getBoundingClientRect().left - links.getBoundingClientRect().left) / scale}px)`; indicator.style.opacity = "1"; };
  tops.forEach((link) => { link.addEventListener("pointerenter", () => place(link)); link.addEventListener("focus", () => place(link)); });
  links?.addEventListener("pointerleave", () => place(tops.find((link) => link.classList.contains("is-active"))));
  const update = () => { nav.classList.toggle("scrolled", scrollY > 24); nav.classList.toggle("on-dark", darks.some((section) => { const rect = section.getBoundingClientRect(); return rect.top <= 38 && rect.bottom >= 38; })); };
  let ticking = false; addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { ticking = false; update(); }); } }, { passive: true }); update();
  const setSheet = (open) => { sheet?.classList.toggle("open", open); nav.classList.toggle("sheet-open", open); document.documentElement.style.overflow = open ? "hidden" : ""; button?.setAttribute("aria-expanded", String(open)); sheet?.setAttribute("aria-hidden", String(!open)); if (button) button.textContent = open ? "Close" : "Menu"; };
  button?.addEventListener("click", () => setSheet(!sheet?.classList.contains("open"))); sheet?.addEventListener("click", (event) => { if (event.target.closest("a")) setSheet(false); }); addEventListener("keydown", (event) => { if (event.key === "Escape" && sheet?.classList.contains("open")) { setSheet(false); button?.focus(); } });
}

function initDeviceScene() {
  const stage = document.querySelector("[data-device-stage]"), dots = [...document.querySelectorAll(".device-dots button")];
  if (!stage) return;
  const scenes = [
    { title: "Scan once.", copy: "The phone finds the local hub.", mac: "Scan to connect", status: "Waiting for iPhone", kicker: "Ready to scan", phone: "Be the camera", pill: "Connect" },
    { title: "Send what you see.", copy: "The newest camera frame wins.", mac: "iPhone connected", status: "Receiving live camera", kicker: "Sending live", phone: "14.8 fps · active camera", pill: "Live" },
    { title: "Move together.", copy: "Every screen follows one lesson state.", mac: "Step verified", status: "Everyone is on step 5", kicker: "Watching", phone: "Step 5 of 8", pill: "Next" }
  ];
  let current = 0, visible = false, timer;
  const paint = (index) => { current = index; const scene = scenes[index]; stage.dataset.scene = String(index + 1); document.querySelector("[data-scene-index]").textContent = `0${index + 1} / 03`; document.querySelector("[data-scene-title]").textContent = scene.title; document.querySelector("[data-scene-copy]").textContent = scene.copy; document.querySelector("[data-mac-title]").textContent = scene.mac; document.querySelector("[data-mac-status]").textContent = scene.status; document.querySelector("[data-phone-kicker]").textContent = scene.kicker; document.querySelector("[data-phone-title]").textContent = scene.phone; document.querySelector("[data-phone-pill]").textContent = scene.pill; dots.forEach((dot, at) => dot.setAttribute("aria-selected", String(at === index))); };
  const schedule = () => { clearTimeout(timer); if (!visible || reducedMotion()) return; timer = setTimeout(() => { paint((current + 1) % scenes.length); schedule(); }, 3200); };
  dots.forEach((dot, index) => dot.addEventListener("click", () => { paint(index); schedule(); }));
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) schedule(); else clearTimeout(timer); }, { threshold: 0.35 }).observe(stage);
  paint(0);
  if (!reducedMotion()) { let ticking = false; const linked = () => { ticking = false; const rect = stage.getBoundingClientRect(), span = innerHeight + rect.height, progress = Math.max(0, Math.min(1, (innerHeight - rect.top) / span)); stage.querySelector(".device-pair").style.transform = `translateY(${((0.5 - progress) * 36).toFixed(1)}px)`; }; addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(linked); } }, { passive: true }); linked(); }
}

function initInstallPicker() {
  const picker = document.querySelector("[data-install-picker]");
  if (!picker) return;
  const tabs = [...picker.querySelectorAll('[role="tab"]')];
  const panels = [...document.querySelectorAll("[data-install-panel]")];
  const select = (platform, focus = false) => {
    tabs.forEach((tab) => {
      const active = tab.dataset.platform === platform;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus) tab.focus();
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.installPanel !== platform; });
    try { history.replaceState(null, "", "#" + platform); } catch {}
  };
  const requested = location.hash.slice(1);
  const detected = /android/i.test(navigator.userAgent) ? "android" : /iphone|ipad|ipod/i.test(navigator.userAgent) ? "iphone" : "mac";
  select(tabs.some((tab) => tab.dataset.platform === requested) ? requested : detected);
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(tab.dataset.platform));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      select(tabs[next].dataset.platform, true);
    });
  });
}

initHero(); initReveals(); initNav(); initDeviceScene(); initInstallPicker();
