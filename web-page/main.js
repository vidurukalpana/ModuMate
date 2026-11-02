const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Nav shadow on scroll + hero screenshot flattens as you scroll
const nav = document.querySelector('.nav');
const browser = document.querySelector('.browser');
function onScroll() {
  const y = window.scrollY;
  nav.classList.toggle('scrolled', y > 10);
  if (!reduceMotion && browser) {
    const t = Math.min(y / 500, 1);
    browser.style.setProperty('--tilt', `${14 * (1 - t)}deg`);
    browser.style.setProperty('--scale', `${0.96 + 0.04 * t}`);
  }
}
addEventListener('scroll', onScroll, { passive: true });
onScroll();

// Reveal on scroll
const io = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  });
}, { threshold: 0.12 });
document.querySelectorAll('.reveal').forEach((el, i) => {
  el.style.transitionDelay = `${(i % 5) * 70}ms`;
  io.observe(el);
});

// Count-up for stats
document.querySelectorAll('[data-count]').forEach(el => {
  const end = Number(el.dataset.count);
  const suffix = el.dataset.suffix || '';
  if (reduceMotion) return;
  const obs = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return;
    obs.disconnect();
    const start = performance.now();
    const step = now => {
      const p = Math.min((now - start) / 1200, 1);
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3))) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  obs.observe(el);
});

// Feature tabs
const tabs = [...document.querySelectorAll('[role="tab"]')];
const panel = document.getElementById('panel');
const panelImg = panel.querySelector('img');
function select(tab, focus) {
  tabs.forEach(t => {
    const on = t === tab;
    t.setAttribute('aria-selected', on);
    t.tabIndex = on ? 0 : -1;
  });
  panel.setAttribute('aria-labelledby', tab.id);
  if (focus) tab.focus();
  panelImg.classList.add('swap');
  const next = new Image();
  next.src = `assets/screenshots/${tab.dataset.img}`;
  next.onload = () => {
    panelImg.src = next.src;
    panelImg.alt = tab.dataset.alt;
    panelImg.classList.remove('swap');
  };
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => select(tab));
  tab.addEventListener('keydown', e => {
    const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    if (d) {
      e.preventDefault();
      select(tabs[(i + d + tabs.length) % tabs.length], true);
    }
  });
});
// Preload feature screenshots
tabs.forEach(t => { new Image().src = `assets/screenshots/${t.dataset.img}`; });

// Lightbox
const box = document.querySelector('.lightbox');
const boxImg = box.querySelector('img');
document.addEventListener('click', e => {
  const img = e.target.closest('.zoomable');
  if (!img) return;
  boxImg.src = img.src;
  boxImg.alt = img.alt;
  box.showModal();
});
box.addEventListener('click', e => { if (e.target !== boxImg) box.close(); });

// Show a note if the demo video file is missing
const video = document.querySelector('video');
const showMissing = () => { document.querySelector('.video-missing').hidden = false; };
video.querySelector('source').addEventListener('error', showMissing);
if (video.networkState === HTMLMediaElement.NETWORK_NO_SOURCE) showMissing();
