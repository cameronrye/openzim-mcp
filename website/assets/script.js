// OpenZIM MCP — website interactions. No dependencies.
(function () {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function safeStorage(op, key, val) {
    try { return op === 'get' ? localStorage.getItem(key) : localStorage.setItem(key, val); }
    catch (e) { return null; }
  }

  // ============= THEME =============
  function initTheme() {
    const stored = safeStorage('get', 'theme');
    const initial = stored || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.setAttribute('data-theme', initial);

    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      safeStorage('set', 'theme', next);
    });
  }

  // ============= NAV (scroll shadow + mobile menu) =============
  function initNav() {
    const nav = document.getElementById('nav');
    const toggle = document.getElementById('nav-toggle');
    if (nav) {
      const onScroll = () => {
        if (window.scrollY > 0) nav.classList.add('is-scrolled');
        else nav.classList.remove('is-scrolled');
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    }
    if (toggle && nav) {
      const setMenu = (open) => {
        nav.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      };
      toggle.addEventListener('click', () => setMenu(!nav.classList.contains('is-open')));
      // Close on Escape
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && nav.classList.contains('is-open')) setMenu(false);
      });
      // Close on outside click
      document.addEventListener('click', (e) => {
        if (!nav.classList.contains('is-open')) return;
        if (!nav.contains(e.target)) setMenu(false);
      });
      // Close when an anchor is clicked
      nav.querySelectorAll('.nav__link').forEach(link => {
        link.addEventListener('click', () => setMenu(false));
      });
    }
  }

  // ============= CONSTELLATION ANIMATOR =============
  // Stroke-draw animation for the hero brain-circuit illustration.
  // Targets ~600ms total: 50ms stagger × 9 paths + 240ms per-path draw ≈ 690ms.
  function animateConstellation() {
    const svg = document.getElementById('hero-constellation');
    if (!svg) return;

    const lines = svg.querySelectorAll('.constellation__line');
    const dots = svg.querySelectorAll('.constellation__dot');

    if (reduceMotion) {
      lines.forEach(l => { l.style.strokeDasharray = 'none'; l.style.opacity = '1'; });
      dots.forEach(d => { d.style.opacity = '1'; });
      return;
    }

    let anyAnimated = false;
    lines.forEach(l => {
      let len = 0;
      try { len = l.getTotalLength(); } catch (e) { len = 0; }
      if (!isFinite(len) || len <= 0) {
        // Safari quirk on complex arc paths — show statically rather than risk a broken render.
        l.style.opacity = '1';
        return;
      }
      anyAnimated = true;
      l.style.strokeDasharray = String(len);
      l.style.strokeDashoffset = String(len);
      l.style.transition = 'stroke-dashoffset 240ms cubic-bezier(0.2, 0.8, 0.3, 1)';
    });

    if (!anyAnimated) {
      // Nothing measurable — show dots straight away too.
      dots.forEach(d => { d.style.opacity = '1'; });
      return;
    }

    dots.forEach(d => {
      d.style.opacity = '0';
      d.style.transition = 'opacity 200ms cubic-bezier(0.2, 0.8, 0.3, 1)';
    });

    requestAnimationFrame(() => {
      lines.forEach((l, i) => setTimeout(() => { l.style.strokeDashoffset = '0'; }, i * 50));
      dots.forEach((d, i) => {
        const idx = parseInt(d.dataset.i || String(i), 10);
        setTimeout(() => { d.style.opacity = '1'; }, lines.length * 50 + idx * 60);
      });
    });
  }

  // ============= REVEAL ON SCROLL =============
  function initReveal() {
    const items = document.querySelectorAll('[data-reveal]');
    if (!items.length) return;
    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach(el => el.classList.add('revealed'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    items.forEach(el => io.observe(el));
  }

  // ============= COPY BUTTONS =============
  function initCopyButtons() {
    const buttons = document.querySelectorAll('.copy-btn[data-copy-target]');
    buttons.forEach(btn => {
      btn.addEventListener('click', async () => {
        const sel = btn.getAttribute('data-copy-target');
        const target = sel ? document.querySelector(sel) : null;
        if (!target) return;
        const text = target.innerText.trim();
        try {
          await navigator.clipboard.writeText(text);
          showToast('Copied to clipboard');
        } catch (e) {
          // Fallback: select the text so the user can copy it manually.
          const range = document.createRange();
          range.selectNodeContents(target);
          const sel2 = window.getSelection();
          if (sel2) { sel2.removeAllRanges(); sel2.addRange(range); }
          showToast('Press ⌘/Ctrl-C to copy');
        }
      });
    });
  }

  function showToast(msg) {
    let toast = document.getElementById('copy-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'copy-toast';
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add('is-visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove('is-visible'), 1500);
  }

  // ============= TABS =============
  function initTabs() {
    document.querySelectorAll('[data-tabs]').forEach(group => {
      const buttons = Array.from(group.querySelectorAll('.tabs__btn'));
      const panels = Array.from(group.querySelectorAll('.tabs__panel'));

      const activate = (btn) => {
        const target = btn.getAttribute('data-tab');
        buttons.forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', String(active));
          b.setAttribute('tabindex', active ? '0' : '-1');
        });
        panels.forEach(p => {
          const active = p.id === target;
          p.classList.toggle('is-active', active);
          if (active) p.removeAttribute('hidden'); else p.setAttribute('hidden', '');
        });
      };

      // Initial tabindex state — only the active tab is in the tab order.
      buttons.forEach(b => {
        const active = b.classList.contains('is-active');
        b.setAttribute('tabindex', active ? '0' : '-1');
      });

      buttons.forEach(btn => {
        btn.addEventListener('click', () => activate(btn));
        btn.addEventListener('keydown', (e) => {
          const i = buttons.indexOf(btn);
          let next = -1;
          if (e.key === 'ArrowRight') next = (i + 1) % buttons.length;
          else if (e.key === 'ArrowLeft') next = (i - 1 + buttons.length) % buttons.length;
          else if (e.key === 'Home') next = 0;
          else if (e.key === 'End') next = buttons.length - 1;
          if (next >= 0) {
            e.preventDefault();
            buttons[next].focus();
            activate(buttons[next]);
          }
        });
      });
    });
  }

  // ============= LEGACY ANCHOR REDIRECT =============
  // Runs as early as possible so the browser's initial scroll-to-fragment
  // doesn't leave the user stranded at the top of an unmatched anchor.
  // Called both inline (in <head>) and on DOMContentLoaded as a fallback.
  const LEGACY_ALIASES = {
    '#features': '#what',
    '#smart-retrieval': '#what',
    '#advanced-features': '#what',
    '#developer-experience': '#what',
    '#security': '#what',
    '#whats-new': '#v1',
    '#installation': '#try',
    '#usage': '#try',
    '#documentation': '#deeper',
    '#home': '#hero'
  };
  function redirectLegacyAnchors() {
    if (LEGACY_ALIASES[location.hash]) {
      const target = LEGACY_ALIASES[location.hash];
      history.replaceState(null, '', target);
      const el = document.querySelector(target);
      if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initNav();
    animateConstellation();
    initReveal();
    initCopyButtons();
    initTabs();
    redirectLegacyAnchors();
  });
})();
