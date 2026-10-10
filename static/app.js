/* ==========================================================================
   HABIT QUEST — frontend
   Vanilla ES2020. One IIFE, delegated events, no dependencies.
   ========================================================================== */
(function () {
  'use strict';

  /* ======================================================================
     STATE
     ====================================================================== */
  let state = null;                 // full server state
  let activeTab = 'character';
  let selectedArchetype = null;
  let shopFilter = 'all';
  let lastXpPercent = null;
  let pendingXpGain = 0;            // XP just earned, floated over the bar on next render
  let clockOffset = 0;              // server time minus browser time, in milliseconds
  let sessionTimer = null;          // dock tick loop, only alive while a session runs
  let bellMuted = false;            // persisted under 'hq.bell'
  let audioCtx = null;              // created lazily on the first real user gesture
  let bannerTimer = null;
  let hitFlashTimer = null;
  const announcedSessions = {};     // session id -> its zero moment has been announced

  const STAT_COLORS = {
    str: '#ef4444',
    int: '#a855f7',
    vit: '#22c55e',
    agi: '#22d3ee',
    cha: '#f59e0b',
  };

  const TAB_LABEL = { character: 'Hero', tasks: 'Quests', shop: 'Shop', journal: 'Journal' };

  /* ======================================================================
     SMALL UTILITIES
     ====================================================================== */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));

  const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/[&<>"']/g, (c) => ESC_MAP[c]);
  }

  function fmt(n) {
    const num = Number(n);
    if (!isFinite(num)) return '0';
    return Math.round(num).toLocaleString('en-US');
  }

  function num(value, fallback) {
    const parsed = Number(value);
    return isFinite(parsed) ? parsed : (fallback === undefined ? 0 : fallback);
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function hexA(hex, alpha) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ''));
    if (!m) return 'rgba(245,196,81,' + alpha + ')';
    const int = parseInt(m[1], 16);
    return 'rgba(' + ((int >> 16) & 255) + ',' + ((int >> 8) & 255) + ',' + (int & 255) + ',' + alpha + ')';
  }

  function statMeta(key) {
    const list = (state && state.meta && state.meta.stats) || [];
    for (let i = 0; i < list.length; i++) if (list[i].key === key) return list[i];
    return { key: key, label: key, abbr: String(key).toUpperCase(), blurb: '' };
  }

  function itemBonusText(item) {
    if (!item) return '';
    if (item.bonus_text) return item.bonus_text;
    const bonus = item.bonus || {};
    return Object.keys(bonus)
      .map((k) => '+' + bonus[k] + ' ' + statMeta(k).abbr)
      .join('  ');
  }

  function relTime(ts) {
    const then = new Date(ts);
    if (isNaN(then.getTime())) return '';
    const secs = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
    if (secs < 45) return 'just now';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
    if (secs < 604800) return Math.floor(secs / 86400) + 'd ago';
    return then.toLocaleDateString();
  }

  /* ======================================================================
     API
     ====================================================================== */
  async function api(method, path, body) {
    const opts = { method: method, headers: {} };
    if (body !== undefined && body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (netErr) {
      throw new Error('Cannot reach the Habit Quest server.');
    }
    let payload = {};
    try { payload = await res.json(); } catch (parseErr) { payload = {}; }
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || ('Request failed (' + res.status + ')'));
    }
    return payload;
  }

  /* ======================================================================
     TOASTS
     ====================================================================== */
  function toast(message, kind) {
    const layer = $('#toast-layer');
    if (!layer) return;
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || 'info');
    el.textContent = String(message);
    el.style.transition = 'opacity .4s ease, transform .4s ease';
    layer.appendChild(el);
    window.setTimeout(function () {
      el.style.opacity = '0';
      el.style.transform = 'translateY(-8px)';
    }, 3000);
    window.setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 3500);
  }

  /* ======================================================================
     FLOATING NUMBERS + BURSTS
     ====================================================================== */
  function spawnFloat(text, kind, x, y) {
    const layer = $('#fx-layer');
    if (!layer) return;
    const el = document.createElement('div');
    el.className = 'float-point ' + (kind || 'xp');
    el.textContent = text;
    el.style.left = Math.round(x) + 'px';
    el.style.top = Math.round(y) + 'px';
    layer.appendChild(el);
    window.setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 1500);
  }

  function burst(anchorEl) {
    const layer = $('#fx-layer');
    if (!layer) return;
    const rect = anchorEl && anchorEl.getBoundingClientRect
      ? anchorEl.getBoundingClientRect()
      : { left: window.innerWidth / 2 - 60, top: window.innerHeight / 2 - 60, width: 120, height: 120 };
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    const ring = document.createElement('div');
    ring.className = 'level-up-burst';
    ring.style.left = Math.round(cx) + 'px';
    ring.style.top = Math.round(cy) + 'px';
    ring.textContent = '⬆️';
    layer.appendChild(ring);
    window.setTimeout(function () { if (ring.parentNode) ring.parentNode.removeChild(ring); }, 1900);

    for (let i = 0; i < 22; i++) {
      const bit = document.createElement('div');
      bit.className = 'confetti-bit';
      const angle = (Math.PI * 2 * i) / 22;
      const dist = 70 + Math.random() * 130;
      bit.style.left = Math.round(cx) + 'px';
      bit.style.top = Math.round(cy) + 'px';
      bit.style.setProperty('--dx', Math.round(Math.cos(angle) * dist) + 'px');
      bit.style.setProperty('--dy', Math.round(Math.sin(angle) * dist) + 'px');
      bit.style.animationDelay = Math.round(Math.random() * 160) + 'ms';
      bit.style.background = i % 3 === 0 ? '#f5c451' : (i % 3 === 1 ? '#a855f7' : '#3b82f6');
      layer.appendChild(bit);
      window.setTimeout(function () { if (bit.parentNode) bit.parentNode.removeChild(bit); }, 2200);
    }
  }

  /* ======================================================================
     SESSIONS: CLOCK
     The browser clock is never trusted for anything that matters - every
     timestamp is measured against the server's own clock, which arrives in
     each state payload as `server_now`.
     ====================================================================== */
  function syncClock(serverNow) {
    const parsed = Date.parse(serverNow);
    if (isFinite(parsed)) clockOffset = parsed - Date.now();
  }

  function nowMs() { return Date.now() + clockOffset; }

  function minutesLabel(minutes) {
    const m = Math.round(num(minutes, 0));
    if (m <= 0) return '';
    if (m < 60) return m + ' min';
    const hours = Math.floor(m / 60);
    const rest = m % 60;
    return rest === 0 ? hours + ' hr' : hours + ' hr ' + rest + ' min';
  }

  function presetLabel(minutes) {
    const m = num(minutes, 0);
    if (m < 60) return m + 'm';
    const hours = m / 60;
    return (hours % 1 === 0 ? hours : hours.toFixed(1)) + 'h';
  }

  function clockText(seconds) {
    const total = Math.max(0, Math.floor(num(seconds, 0)));
    const hours = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const body = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
    return hours ? hours + ':' + body : body;
  }

  /* Live numbers for a session, derived from the server's own timestamps so a
     refresh mid-countdown stays honest. Display only - the server decides. */
  function sessionTiming(session) {
    const duration = Math.max(0, num(session.duration_seconds, 0));
    const started = Date.parse(session.started_at);
    const ends = Date.parse(session.ends_at);
    const now = nowMs();
    let elapsed = isFinite(started) ? (now - started) / 1000 : num(session.elapsed_seconds, 0);
    let remaining = isFinite(ends) ? (ends - now) / 1000 : duration - elapsed;
    if (!isFinite(elapsed)) elapsed = 0;
    if (!isFinite(remaining)) remaining = 0;
    const overtime = remaining < 0;
    const left = Math.max(0, remaining);
    return {
      duration: duration,
      elapsed: Math.max(0, elapsed),
      remaining: left,
      overtime: overtime ? Math.abs(remaining) : 0,
      over: overtime,
      pct: duration > 0 ? clamp((left / duration) * 100, 0, 100) : 0,
      urgent: left > 0 && (left <= 60 || (duration > 0 && left / duration <= 0.1)),
    };
  }

  /* ======================================================================
     SESSIONS: BELL
     Synthesised with the Web Audio API: no audio files, so the app stays
     offline-first. Every call is guarded - a blocked AudioContext must never
     be able to break the interface.
     ====================================================================== */
  function readBellPref() {
    try { bellMuted = window.localStorage.getItem('hq.bell') === 'muted'; }
    catch (e) { bellMuted = false; }
    const btn = $('#dock-bell');
    if (btn) btn.textContent = bellMuted ? '🔕' : '🔔';
  }

  function setBellMuted(muted) {
    bellMuted = !!muted;
    try { window.localStorage.setItem('hq.bell', bellMuted ? 'muted' : 'on'); }
    catch (e) { /* ignore */ }
  }

  function ensureAudio() {
    if (audioCtx) return audioCtx;
    try {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return null;
      audioCtx = new Ctor();
    } catch (e) { audioCtx = null; }
    return audioCtx;
  }

  /* Call inside a real user gesture (a click) so autoplay policy is satisfied. */
  function unlockAudio() {
    const ctx = ensureAudio();
    if (!ctx) return;
    try { if (ctx.state === 'suspended' && ctx.resume) ctx.resume(); } catch (e) { /* ignore */ }
  }

  function strikeBell(ctx, when, freq, gain, decay) {
    try {
      const osc = ctx.createOscillator();
      const amp = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, when);
      amp.gain.setValueAtTime(0, when);
      amp.gain.linearRampToValueAtTime(gain, when + 0.008);
      amp.gain.exponentialRampToValueAtTime(0.0008, when + decay);
      osc.connect(amp);
      amp.connect(ctx.destination);
      osc.start(when);
      osc.stop(when + decay + 0.05);
    } catch (e) { /* never let audio break the UI */ }
  }

  function ringBell(kind) {
    if (bellMuted) return;
    const ctx = ensureAudio();
    if (!ctx) return;
    try { if (ctx.state === 'suspended' && ctx.resume) ctx.resume(); } catch (e) { /* ignore */ }
    let start;
    try { start = ctx.currentTime + 0.02; } catch (e) { return; }

    if (kind === 'served') {
      // A pleasant rising chime: the time is served, go ahead and finish.
      [523.25, 659.25, 783.99].forEach(function (freq, i) {
        strikeBell(ctx, start + i * 0.16, freq, 0.16, 1.1);
        strikeBell(ctx, start + i * 0.16, freq * 2, 0.05, 0.7);
      });
    } else {
      // An alarming bell: inharmonic partials, struck three times.
      for (let i = 0; i < 3; i++) {
        const when = start + i * 1.0;
        strikeBell(ctx, when, 880, 0.20, 0.9);
        strikeBell(ctx, when, 1174.7, 0.13, 0.8);
        strikeBell(ctx, when, 1760, 0.07, 0.6);
      }
    }
  }

  /* ======================================================================
     SESSIONS: BANNER + HIT FEEDBACK
     ====================================================================== */
  function flashBanner(text, kind) {
    const el = $('#bell-banner');
    if (!el) return;
    el.textContent = text;
    el.classList.remove('hidden', 'times-up', 'done');
    el.classList.add('show', kind === 'done' ? 'done' : 'times-up');
    if (bannerTimer) window.clearTimeout(bannerTimer);
    bannerTimer = window.setTimeout(function () {
      el.classList.remove('show');
      el.classList.add('hidden');
    }, 4000);
  }

  /* Accepts an element or an already-measured rect, so a float can be aimed at
     something that is about to disappear (the dock, once the session ends). */
  function floatFrom(anchor, text, kind, dx, dy) {
    let rect = null;
    if (anchor && typeof anchor.getBoundingClientRect === 'function') {
      rect = anchor.getBoundingClientRect();
    } else if (anchor && typeof anchor.left === 'number') {
      rect = anchor;
    }
    const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
    const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
    spawnFloat(text, kind,
      clamp(x + dx, 8, window.innerWidth - 100),
      clamp(y + dy, 8, window.innerHeight - 30));
  }

  function playHit(damage, name) {
    const dmg = num(damage, 0);
    const flash = $('#hit-flash');
    if (flash) {
      flash.classList.add('on');
      if (hitFlashTimer) window.clearTimeout(hitFlashTimer);
      hitFlashTimer = window.setTimeout(function () { flash.classList.remove('on'); }, 900);
    }
    const app = $('#app');
    if (app) {
      app.classList.add('shake');
      window.setTimeout(function () { app.classList.remove('shake'); }, 700);
    }
    floatFrom($('#avatar') || $('#hp-block'), '-' + fmt(dmg) + ' HP', 'damage', -18, 0);
    toast('💥 The bell caught you' + (name ? ' on ' + name : '') +
      ' — you took ' + fmt(dmg) + ' damage.', 'error');
  }

  /* ======================================================================
     SESSIONS: DOCK
     Visible on every tab while a session runs, so the clock can never be
     lost behind a view change.
     ====================================================================== */
  function ensureTicker() {
    const needed = !!(state && state.has_character && state.session);
    if (needed && !sessionTimer) sessionTimer = window.setInterval(tickDock, 200);
    if (!needed && sessionTimer) {
      window.clearInterval(sessionTimer);
      sessionTimer = null;
    }
  }

  function tickDock() {
    if (!state || !state.session) return;
    renderDock();
  }

  /* Live clocks on the quest cards, updated in place so the list never re-renders. */
  function updateLiveClocks() {
    const session = state && state.session;
    if (!session) return;
    const timing = sessionTiming(session);
    const text = (timing.over ? '+' : '') + clockText(timing.over ? timing.overtime : timing.remaining);
    $$('[data-live-for]').forEach(function (el) {
      if (num(el.getAttribute('data-live-for'), 0) === num(session.task_id, 0)) {
        el.textContent = text;
      }
    });
  }

  function seedAnnounced(session) {
    if (!session) return;
    // A session already past zero when we first see it (a page refreshed
    // mid-overtime) must not re-ring the bell.
    if (sessionTiming(session).over) announcedSessions[session.id] = true;
  }

  function renderDock() {
    const dock = $('#session-dock');
    if (!dock) return;
    const session = (state && state.has_character && state.session) || null;

    if (!session) {
      dock.classList.add('hidden');
      dock.classList.remove('beat_clock', 'endure', 'urgent', 'ready', 'overrun');
      ensureTicker();
      return;
    }

    const timing = sessionTiming(session);
    const endure = session.mode === 'endure';

    dock.classList.remove('hidden');
    dock.classList.toggle('beat_clock', session.mode === 'beat_clock');
    dock.classList.toggle('endure', endure);
    dock.classList.toggle('urgent', timing.urgent);
    dock.classList.toggle('ready', endure && timing.over);
    dock.classList.toggle('overrun', timing.over);

    const ring = $('#dock-ring');
    if (ring) ring.style.setProperty('--pct', String(Math.round(timing.pct)));
    const bar = $('#dock-bar-fill');
    if (bar) bar.style.width = timing.pct + '%';
    const time = $('#dock-time');
    if (time) {
      time.textContent = (timing.over ? '+' : '') +
        clockText(timing.over ? timing.overtime : timing.remaining);
    }

    const taskEl = $('#dock-task');
    if (taskEl) {
      taskEl.textContent = (session.task_icon ? session.task_icon + ' ' : '') + session.task_name;
    }
    const modeEl = $('#dock-mode');
    if (modeEl) {
      modeEl.textContent = (session.mode_icon ? session.mode_icon + ' ' : '') + session.mode_label;
    }

    const hint = $('#dock-hint');
    if (hint) {
      if (endure) {
        hint.textContent = timing.over
          ? 'Time served — keep going as long as you like, then finish.'
          : 'Stay with it for ' + minutesLabel(session.duration_minutes) + '. Finishing early will not count.';
      } else {
        hint.textContent = timing.over
          ? 'The bell has rung — finishing now counts as a miss.'
          : 'Finish before the bell to earn it. Let it ring and you take a hit.';
      }
    }

    const finish = $('#dock-finish');
    if (finish) finish.textContent = (endure && timing.over) ? '✓ Finish now' : '✓ Finished';

    // The zero moment: announce it exactly once per session.
    if (timing.over && !announcedSessions[session.id]) {
      announcedSessions[session.id] = true;
      if (endure) {
        ringBell('served');
        flashBanner('TIME SERVED', 'done');
      } else {
        ringBell('times-up');
        flashBanner("TIME'S UP", 'times-up');
      }
    }

    updateLiveClocks();
    ensureTicker();
  }

  /* ======================================================================
     SESSIONS: HEALTH
     ====================================================================== */
  function renderHealth() {
    const host = $('#hp-block');
    if (!host) return;  // see renderHero(): this is the only health readout
    const c = (state && state.character) || null;
    if (!c || !state.has_character) { host.innerHTML = ''; return; }

    const pct = clamp(num(c.hp_pct, 0) * 100, 0, 100);
    host.classList.toggle('downed', !!c.downed);
    host.innerHTML =
      '<div class="hp-head">' +
      '<span class="hp-label">❤️ Health</span>' +
      '<span class="hp-value">' + fmt(c.hp) + ' / ' + fmt(c.max_hp) + '</span>' +
      (c.downed ? '<span class="hp-chip wounded">WOUNDED</span>' : '') +
      '</div>' +
      // .hp-bar-track is the fixed-height groove and .hp-bar is the inner
      // full-height bar, which is the nesting the stylesheet expects.
      '<div class="hp-bar-track' + (c.downed ? ' downed' : '') +
      '" role="progressbar" aria-label="Health">' +
      '<div class="hp-bar"><div class="hp-bar-fill" style="width:' + pct + '%"></div></div>' +
      '</div>';
  }

  /* ======================================================================
     SESSIONS: ACTIONS
     ====================================================================== */
  async function startSession(id) {
    unlockAudio();   // this click is the gesture that lets the bell play later
    try {
      const res = await api('POST', '/api/tasks/' + id + '/session/start');
      applyState(res.state);
      const s = res.session || {};
      toast('⏱ ' + (s.task_name || 'Session') + ' — ' + minutesLabel(s.duration_minutes) +
        ' of ' + (s.mode_label || 'timed work') + '.', 'gold');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function finishSession() {
    const session = state && state.session;
    if (!session) return;
    // Measure the dock before the state lands and hides it.
    const anchorEl = $('#dock-finish');
    const anchor = anchorEl ? anchorEl.getBoundingClientRect() : null;
    unlockAudio();
    try {
      const res = await api('POST', '/api/tasks/' + session.task_id + '/session/finish');

      if (res.outcome === 'hit') {
        applyState(res.state);
        playHit(res.damage, session.task_name);
        return;
      }

      const r = res.rewards || {};
      pendingXpGain = num(r.xp, 0);
      applyState(res.state);

      floatFrom(anchor, '+' + fmt(r.xp) + ' XP', 'xp', -18, -6);
      floatFrom(anchor, '+' + fmt(r.coins) + ' gold', 'coin', 16, 20);

      let msg = 'Session complete · +' + fmt(r.xp) + ' XP · +' + fmt(r.coins) + ' gold';
      if (num(r.speed_bonus, 0) > 0) msg += ' · ' + Math.round(num(r.speed_bonus, 0) * 100) + '% time to spare';
      if (num(r.endure_bonus, 0) > 0) msg += ' · +' + Math.round(num(r.endure_bonus, 0) * 100) + '% endurance bonus';
      if (r.wounded) msg += ' · wounded (half gold)';
      toast(msg, 'success');

      const unlocked = res.unlocked || [];
      if (res.level_up) {
        showLevelUp(res.level_up, unlocked);
      } else {
        unlocked.forEach(function (a, i) {
          window.setTimeout(function () {
            toast('Achievement unlocked: ' + a.name, 'gold');
          }, 350 + i * 450);
        });
      }
    } catch (err) {
      // 'Not yet - N minutes still to serve.' Keep the session running.
      toast(err.message, 'error');
      refresh();
    }
  }

  async function giveUpSession() {
    const session = state && state.session;
    if (!session) return;
    try {
      const res = await api('POST', '/api/tasks/' + session.task_id + '/session/abandon');
      applyState(res.state);
      if (res.outcome === 'hit') playHit(res.damage, session.task_name);
      else toast('Session given up — no reward, no penalty.', 'info');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  /* ======================================================================
     MODAL
     ====================================================================== */
  function openModal(title, bodyHTML, onMount) {
    $('#modal-title').innerHTML = title;
    $('#modal-body').innerHTML = bodyHTML;
    $('#modal-backdrop').classList.remove('hidden');
    document.body.classList.add('modal-open');
    if (typeof onMount === 'function') onMount($('#modal-body'));
  }

  function closeModal() {
    $('#modal-backdrop').classList.add('hidden');
    $('#modal-body').innerHTML = '';
    document.body.classList.remove('modal-open');
  }

  /* ======================================================================
     AVATAR
     ====================================================================== */
  function avatarSVG(char, equipped) {
    const base = char.archetype_color || '#f59e0b';
    const gear = equipped || {};
    const colourFor = function (slot, fallback) {
      const item = gear[slot];
      return item ? (item.rarity_color || fallback) : fallback;
    };
    const bodyColour = colourFor('body', '#3b3663');
    const bootColour = colourFor('boots', '#2c2947');
    const weapon = gear.weapon;
    const head = gear.head;
    const accessory = gear.accessory;
    const skin = '#e9c6a4';
    const hair = '#3b2a20';

    const headGear = head
      ? (head.id === 'crown_of_ages' || head.id === 'mage_hood'
        ? '<path d="M72 46 l9 -20 l10 13 l9 -20 l9 20 l10 -13 l9 20 z" fill="' + esc(colourFor('head', base)) + '"/>'
        : '<path d="M71 62 q29 -36 58 0 v16 q-29 -15 -58 0 z" fill="' + esc(colourFor('head', base)) + '"/>' +
          '<rect x="74" y="70" width="52" height="5" rx="2" fill="#0d0b18" opacity=".55"/>')
      : '';

    const weaponGear = weapon
      ? '<g transform="translate(152,138)">' +
        '<rect x="-4" y="0" width="8" height="26" rx="3" fill="#3b2a20"/>' +
        '<rect x="-17" y="-7" width="34" height="8" rx="3" fill="#c9a227"/>' +
        '<path d="M-6 -9 L6 -9 L3 -78 L-3 -78 Z" fill="' + esc(colourFor('weapon', base)) + '" ' +
        'stroke="rgba(255,255,255,.45)" stroke-width="1.5"/>' +
        '</g>'
      : '';

    const accessoryGear = accessory
      ? '<circle cx="100" cy="132" r="8" fill="' + esc(colourFor('accessory', '#22d3ee')) + '"/>' +
        '<circle cx="100" cy="132" r="12" fill="none" stroke="' + esc(colourFor('accessory', '#22d3ee')) + '" stroke-opacity=".45" stroke-width="3"/>'
      : '<circle cx="100" cy="132" r="3.5" fill="' + esc(base) + '" opacity=".55"/>';

    const slots = ['weapon', 'head', 'body', 'boots', 'accessory'];
    const badges = slots.map(function (slot, i) {
      const item = gear[slot];
      const x = 40 + i * 30;
      if (!item) {
        return '<circle cx="' + x + '" cy="254" r="11" fill="rgba(0,0,0,.4)" stroke="rgba(255,255,255,.10)"/>' +
          '<text x="' + x + '" y="259" font-size="12" text-anchor="middle" fill="rgba(255,255,255,.25)">·</text>';
      }
      return '<circle cx="' + x + '" cy="254" r="11" fill="rgba(0,0,0,.55)" stroke="' + esc(item.rarity_color) + '" stroke-width="1.6"/>' +
        '<text x="' + x + '" y="259" font-size="12" text-anchor="middle">' + esc(item.icon) + '</text>';
    }).join('');

    return '' +
      '<svg class="hq-avatar" viewBox="0 0 200 272" width="100%" height="100%" role="img" ' +
      'aria-label="' + esc(char.name) + ' the ' + esc(char.archetype_name) + '">' +
      '<defs>' +
      '<linearGradient id="hqCape" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + esc(base) + '" stop-opacity=".95"/>' +
      '<stop offset="100%" stop-color="' + esc(base) + '" stop-opacity=".35"/>' +
      '</linearGradient>' +
      '</defs>' +
      '<ellipse cx="100" cy="248" rx="54" ry="9" fill="rgba(0,0,0,.45)"/>' +
      '<path d="M62 98 Q46 172 58 240 L142 240 Q154 172 138 98 Z" fill="url(#hqCape)"/>' +
      '<rect x="80" y="176" width="17" height="58" rx="7" fill="' + esc(bootColour) + '"/>' +
      '<rect x="103" y="176" width="17" height="58" rx="7" fill="' + esc(bootColour) + '"/>' +
      '<path d="M68 104 q32 -13 64 0 l6 68 q-38 13 -76 0 Z" fill="' + esc(bodyColour) + '" ' +
      'stroke="rgba(255,255,255,.14)" stroke-width="1.5"/>' +
      '<rect x="68" y="158" width="64" height="9" rx="4" fill="#141127"/>' +
      '<rect x="52" y="108" width="16" height="64" rx="8" fill="' + esc(bodyColour) + '"/>' +
      '<rect x="132" y="108" width="16" height="64" rx="8" fill="' + esc(bodyColour) + '"/>' +
      '<circle cx="60" cy="178" r="9" fill="' + skin + '"/>' +
      '<circle cx="140" cy="160" r="9" fill="' + skin + '"/>' +
      '<rect x="93" y="86" width="14" height="16" fill="' + skin + '"/>' +
      '<circle cx="100" cy="66" r="26" fill="' + skin + '"/>' +
      '<path d="M74 62 q6 -30 26 -30 q20 0 26 30 q-10 -12 -26 -12 q-16 0 -26 12 Z" fill="' + hair + '"/>' +
      '<circle cx="90" cy="69" r="3" fill="#20223a"/>' +
      '<circle cx="110" cy="69" r="3" fill="#20223a"/>' +
      headGear +
      weaponGear +
      accessoryGear +
      badges +
      '</svg>';
  }

  function renderAvatar() {
    const char = state.character;
    const host = $('#avatar');
    if (!host) return;
    host.innerHTML = avatarSVG(char, state.equipped || {});
    const glow = $('#avatar-glow');
    if (glow) {
      glow.style.setProperty('--glow', char.archetype_color || '#f5c451');
      glow.style.background =
        'radial-gradient(circle at 50% 42%, ' + hexA(char.archetype_color, 0.55) + ', transparent 68%)';
    }
  }

  /* ======================================================================
     RENDER: CHROME (always visible)
     ====================================================================== */
  function renderChrome() {
    const c = state.character;

    $('#top-level').textContent = 'Lv ' + c.level;
    $('#top-coins').textContent = '💰 ' + fmt(c.coins);
    $('#day-streak').textContent = fmt(c.day_streak);

    const percent = clamp(num(c.level_progress, 0), 0, 1) * 100;
    const fill = $('#xp-fill');
    fill.style.width = percent + '%';
    $('#xp-label').textContent =
      (c.max_level ? 'MAX LEVEL · ' : fmt(c.level_xp) + ' / ' + fmt(c.level_xp_needed) + ' XP');

    if (lastXpPercent !== null && percent > lastXpPercent + 0.75) {
      // Anchor to the whole bar (the fill can be near-zero width) and keep the
      // burst inside the viewport so it is never spawned off-screen.
      const bar = document.querySelector('.xp-bar') || fill;
      const rect = bar.getBoundingClientRect();
      const y = rect.top + rect.height / 2;
      const label = '+' + fmt(pendingXpGain || c.level_xp) + ' XP';
      for (let i = 0; i < 3; i++) {
        spawnFloat(label, 'xp',
          clamp(rect.right - 44 - i * 18, 8, window.innerWidth - 70),
          clamp(y - 10 - i * 6, 8, window.innerHeight - 30));
      }
    }
    pendingXpGain = 0;
    lastXpPercent = percent;
  }

  /* ======================================================================
     RENDER: ONBOARDING
     ====================================================================== */
  function renderOnboarding() {
    const meta = (state && state.meta) || {};
    const archetypes = meta.archetypes || [];
    if (!selectedArchetype && archetypes.length) selectedArchetype = archetypes[0].id;

    $('#arch-grid').innerHTML = archetypes.map(function (a) {
      const stats = a.stats || {};
      const chips = (meta.stats || []).map(function (s) {
        return '<span class="stat-abbr">' + esc(s.abbr) + ' ' + fmt(stats[s.key]) + '</span>';
      }).join('');
      return '<button type="button" class="arch-card' + (a.id === selectedArchetype ? ' selected' : '') +
        '" data-action="pick-arch" data-id="' + esc(a.id) + '">' +
        '<span class="arch-icon" style="--arch-color:' + esc(a.color) + '">' + esc(a.icon) + '</span>' +
        '<span class="arch-name">' + esc(a.name) + '</span>' +
        '<span class="arch-blurb">' + esc(a.blurb) + '</span>' +
        '<span class="arch-stats">' + chips + '</span>' +
        '</button>';
    }).join('');
  }

  /* ======================================================================
     RENDER: HERO
     ====================================================================== */
  function renderHero() {
    const c = state.character;

    $('#hero-name-display').textContent = c.name;
    $('#hero-class').textContent = (c.archetype_icon ? c.archetype_icon + ' ' : '') +
      c.archetype_name + ' · Level ' + c.level;

    // Health lives in #hp-block above (label, bar and WOUNDED chip), so it is
    // deliberately not repeated as a vitals tile here.
    $('#hero-vitals').innerHTML = [
      ['Power', fmt(c.power), ''],
      ['Gold', '💰 ' + fmt(c.coins), ''],
      ['Quests done', fmt(c.total_completions), ''],
      ['Best streak', fmt(c.best_day_streak) + 'd', ''],
    ].map(function (row) {
      return '<div class="vital' + (row[2] ? ' ' + row[2] : '') + '">' +
        '<span class="vital-label">' + row[0] + '</span>' +
        '<span class="vital-value">' + row[1] + '</span></div>';
    }).join('');

    renderAvatar();

    /* --- equipment tiles --- */
    const slots = (state.meta && state.meta.slots) || [];
    $('#equip-grid').innerHTML = slots.map(function (slot) {
      const item = state.equipped ? state.equipped[slot.id] : null;
      if (!item) {
        return '<div class="equip-slot empty"><span class="equip-slot-icon">' + esc(slot.icon) +
          '</span><span class="equip-slot-label">' + esc(slot.label) + '</span>' +
          '<span class="equip-slot-item">Empty</span></div>';
      }
      return '<button type="button" class="equip-slot rarity-' + esc(item.rarity) + '" ' +
        'data-action="unequip-slot" data-slot="' + esc(slot.id) + '" ' +
        'style="--rarity-color:' + esc(item.rarity_color) + '" title="Click to unequip">' +
        '<span class="equip-slot-icon">' + esc(item.icon) + '</span>' +
        '<span class="equip-slot-label">' + esc(slot.label) + '</span>' +
        '<span class="equip-slot-item">' + esc(item.name) + '</span>' +
        '<span class="hint">' + esc(itemBonusText(item)) + '</span>' +
        '</button>';
    }).join('');

    /* --- abilities --- */
    const total = c.total_stats || c.stats || {};
    const bonus = c.equip_bonus || {};
    const points = num(c.skill_points, 0);
    $('#skill-points-badge').textContent = points + ' point' + (points === 1 ? '' : 's') +
      (points > 0 ? ' to spend' : '');

    $('#stat-list').innerHTML = ((state.meta && state.meta.stats) || []).map(function (s) {
      const value = num(total[s.key], 0);
      const gear = num(bonus[s.key], 0);
      const colour = STAT_COLORS[s.key] || '#f5c451';
      return '<div class="stat-row">' +
        '<div class="stat-name"><span class="stat-abbr" style="color:' + colour + '">' +
        esc(s.abbr) + '</span> ' + esc(s.label) +
        (gear > 0 ? ' <span class="stat-bonus">+' + gear + ' gear</span>' : '') + '</div>' +
        '<span class="stat-value" style="color:' + colour + '">' + value + '</span>' +
        '<div class="stat-bar"><div class="stat-bar-fill" style="width:' +
        clamp(Math.round((value / 25) * 100), 2, 100) + '%;background:' + colour + '"></div></div>' +
        '<button type="button" class="btn btn-primary btn-sm stat-up" data-action="upgrade" ' +
        'data-stat="' + esc(s.key) + '"' + (points > 0 ? '' : ' disabled') +
        ' title="Spend 1 skill point on ' + esc(s.label) + '">＋</button>' +
        '</div>';
    }).join('');

    $('#skill-hint').textContent = points > 0
      ? points + ' skill point' + (points === 1 ? '' : 's') + ' ready. Spend them on any ability.'
      : 'Every level grants ' + num(state.meta.stats_per_level, 3) +
        ' skill points. Next level at ' + fmt(c.next_level_xp) + ' XP.';

    $('#hero-feed').innerHTML = feedHTML((state.activity || []).slice(0, 6));
  }

  /* ======================================================================
     RENDER: QUESTS
     ====================================================================== */
  function renderQuests() {
    const tasks = state.tasks || [];
    const today = (state.meta && state.meta.today) || '';
    const doneCount = tasks.filter(function (t) { return t.completed_today; }).length;

    let todayXp = 0;
    const series = (state.history && state.history.series) || [];
    for (let i = 0; i < series.length; i++) if (series[i].day === today) todayXp = num(series[i].xp, 0);

    $('#day-ring-value').textContent = doneCount + '/' + tasks.length;
    const timedCount = tasks.filter(function (t) { return t.is_timed; }).length;
    $('#task-summary').textContent = tasks.length
      ? doneCount + ' of ' + tasks.length + ' quests done today · +' + fmt(todayXp) + ' XP banked today' +
        (timedCount ? ' · ' + timedCount + ' timed' : '')
      : 'No quests yet — add your first habit and start earning.';

    if (!tasks.length) {
      $('#task-list').innerHTML =
        '<div class="empty-state card"><div class="onboarding-crest">🗺️</div>' +
        '<h3 class="panel-title">Your quest board is empty</h3>' +
        '<p class="hint">Add the habits you want to build. Give each one a point value — ' +
        'the harder it is for you, the more XP and gold it should be worth.</p>' +
        '<button class="btn btn-primary" data-action="new-task" type="button">＋ Create your first quest</button>' +
        '</div>';
      return;
    }

    $('#task-list').innerHTML = tasks.map(function (t) {
      const colour = t.color || '#f59e0b';
      const meta = [];
      meta.push('<span class="stat-tag" style="--stat-color:' + esc(colour) + '">' +
        esc(t.stat_abbr || statMeta(t.stat).abbr) + '</span>');
      if (num(t.streak, 0) >= 2) meta.push('<span class="task-streak">🔥 ' + fmt(t.streak) + ' days</span>');
      if (num(t.completions, 0) > 0) meta.push('<span class="hint">' + fmt(t.completions) + '× done</span>');
      if (num(t.difficulty_multiplier, 1) !== 1) {
        meta.push('<span class="hint">×' + num(t.difficulty_multiplier, 1) + ' difficulty</span>');
      }

      const running = !!(state.session && num(state.session.task_id, 0) === num(t.id, 0));
      if (t.is_timed) {
        meta.push('<span class="mode-tag ' + esc(t.mode) + '">' + esc(t.mode_icon) + ' ' +
          esc(t.mode_label) + '</span>');
        meta.push('<span class="duration-chip">⏱ ' + esc(t.duration_label) + '</span>');
      }
      if (running) {
        const live = sessionTiming(state.session);
        // Updated in place by the tick loop, so the list never re-renders.
        meta.push('<span class="duration-chip task-live" data-live-for="' + t.id + '">' +
          (live.over ? '+' : '') + clockText(live.over ? live.overtime : live.remaining) + '</span>');
      }
      if (num(t.sessions_lost, 0) > 0) {
        meta.push('<span class="hint">💥 ' + fmt(t.sessions_lost) + ' hit' +
          (num(t.sessions_lost, 0) === 1 ? '' : 's') + '</span>');
      }

      const actions = [];
      if (t.completed_today) {
        actions.push('<span class="task-done-badge">✓ Done today</span>');
        actions.push('<button type="button" class="btn btn-ghost btn-sm task-undo" ' +
          'data-action="undo" data-id="' + t.id + '" title="Undo today\'s completion">↩</button>');
      } else if (running) {
        actions.push('<span class="task-done-badge">⏱ In progress</span>');
      } else if (t.is_timed) {
        actions.push('<button type="button" class="btn btn-primary btn-sm task-start ' +
          esc(t.mode) + '" data-action="start-session" data-id="' + t.id + '" title="' +
          esc(t.mode_blurb || '') + '">▶ Start ' + esc(t.duration_label) + '</button>');
      } else {
        actions.push('<button type="button" class="btn btn-primary btn-sm task-check" ' +
          'data-action="complete" data-id="' + t.id + '">✓ Complete</button>');
      }
      actions.push('<button type="button" class="btn btn-ghost btn-sm task-edit" ' +
        'data-action="edit" data-id="' + t.id + '">Edit</button>');
      actions.push('<button type="button" class="btn btn-ghost btn-sm task-del" ' +
        'data-action="delete" data-id="' + t.id + '" title="Delete quest">🗑</button>');

      return '<article class="task-card' + (t.completed_today ? ' done' : '') +
        (running ? ' session-running' : '') +
        '" data-id="' + t.id + '" style="--task-color:' + esc(colour) + '">' +
        '<div class="task-icon" style="color:' + esc(colour) + '">' + esc(t.icon) + '</div>' +
        '<div class="task-body">' +
        '<h4 class="task-name">' + esc(t.name) + '</h4>' +
        (t.description ? '<p class="task-desc">' + esc(t.description) + '</p>' : '') +
        '<div class="task-meta">' + meta.join('') + '</div>' +
        '</div>' +
        '<div class="task-rewards">' +
        '<span class="reward reward-xp">+' + fmt(t.reward_xp) + ' XP</span>' +
        '<span class="reward reward-coin">+' + fmt(t.reward_coins) + ' gold</span>' +
        '</div>' +
        '<div class="task-actions">' + actions.join('') + '</div>' +
        '</article>';
    }).join('');
  }

  /* ======================================================================
     RENDER: SHOP
     ====================================================================== */
  function renderShop() {
    const c = state.character;
    const shop = state.shop || [];
    const ownedCount = shop.filter(function (i) { return i.owned; }).length;

    $('#wallet').textContent = '💰 ' + fmt(c.coins);
    $('#shop-summary').textContent = ownedCount + ' of ' + shop.length +
      ' pieces collected · level ' + c.level + ' hero';

    const slots = (state.meta && state.meta.slots) || [];
    const filters = [{ id: 'all', label: 'All' }, { id: 'owned', label: 'Owned' }]
      .concat(slots.map(function (s) { return { id: s.id, label: s.icon + ' ' + s.label }; }));

    $('#shop-filters').innerHTML = filters.map(function (f) {
      return '<button type="button" class="filter-btn' + (shopFilter === f.id ? ' active' : '') +
        '" data-action="filter-shop" data-filter="' + esc(f.id) + '">' + esc(f.label) + '</button>';
    }).join('');

    let items = shop;
    if (shopFilter === 'owned') items = shop.filter(function (i) { return i.owned; });
    else if (shopFilter !== 'all') items = shop.filter(function (i) { return i.slot === shopFilter; });

    if (!items.length) {
      $('#shop-grid').innerHTML = '<div class="empty-state card"><h3 class="panel-title">Nothing here yet</h3>' +
        '<p class="hint">Change the filter, or complete quests to earn more gold.</p></div>';
    } else {
      $('#shop-grid').innerHTML = items.map(function (it) {
        const classes = ['shop-card', 'rarity-' + it.rarity];
        if (it.owned) classes.push('owned');
        if (it.equipped) classes.push('equipped');
        if (!it.level_ok) classes.push('locked');
        if (!it.affordable && !it.owned) classes.push('unaffordable');

        let action;
        if (it.equipped) {
          action = '<button type="button" class="btn btn-ghost btn-sm" data-action="unequip" ' +
            'data-item="' + esc(it.id) + '">Unequip</button>';
        } else if (it.owned) {
          action = '<button type="button" class="btn btn-primary btn-sm" data-action="equip" ' +
            'data-item="' + esc(it.id) + '">Equip</button>';
        } else {
          const blocked = !it.affordable || !it.level_ok;
          action = '<button type="button" class="btn btn-primary btn-sm" data-action="buy" ' +
            'data-item="' + esc(it.id) + '"' + (blocked ? ' disabled' : '') + '>' +
            (!it.level_ok ? 'Locked' : 'Buy') + '</button>';
        }

        return '<article class="' + classes.join(' ') + '" style="--rarity-color:' + esc(it.rarity_color) + '">' +
          '<div class="shop-icon">' + esc(it.icon) + '</div>' +
          '<div class="shop-head">' +
          '<h4 class="shop-name">' + esc(it.name) + '</h4>' +
          '<span class="slot-label">' + esc(it.slot_label) + '</span>' +
          '</div>' +
          '<span class="rarity-tag rarity-' + esc(it.rarity) + '">' + esc(it.rarity_label) + '</span>' +
          '<p class="shop-desc">' + esc(it.desc) + '</p>' +
          '<p class="shop-bonus">' + esc(it.bonus_text || itemBonusText(it)) + '</p>' +
          '<div class="shop-foot">' +
          '<span class="price-tag' + (it.affordable ? '' : ' cant') + '">💰 ' + fmt(it.price) + '</span>' +
          (!it.level_ok ? '<span class="hint">Requires Lv ' + it.level_req + '</span>' : '') +
          '</div>' +
          '<div class="shop-actions">' + action + '</div>' +
          '</article>';
      }).join('');
    }

    const inv = state.inventory || [];
    $('#inventory-grid').innerHTML = inv.length ? inv.map(function (it) {
      return '<div class="inv-item rarity-' + esc(it.rarity) + (it.equipped ? ' equipped' : '') +
        '" style="--rarity-color:' + esc(it.rarity_color) + '">' +
        '<span class="equip-slot-icon">' + esc(it.icon) + '</span>' +
        '<span class="equip-slot-label">' + esc(it.name) + '</span>' +
        '<span class="rarity-tag rarity-' + esc(it.rarity) + '">' + esc(it.slot_label) + '</span>' +
        '<span class="equip-slot-item">' + esc(itemBonusText(it)) + '</span>' +
        (it.equipped
          ? '<button type="button" class="btn btn-ghost btn-sm" data-action="unequip" ' +
            'data-item="' + esc(it.id) + '">Unequip</button>'
          : '<button type="button" class="btn btn-primary btn-sm" data-action="equip" ' +
            'data-item="' + esc(it.id) + '">Equip</button>') +
        '</div>';
    }).join('') : '<div class="empty-state card"><p class="hint">No gear yet. Buy something shiny!</p></div>';
  }

  /* ======================================================================
     RENDER: JOURNAL
     ====================================================================== */
  function feedHTML(entries, compact) {
    if (!entries || !entries.length) {
      return '<div class="empty-state"><p class="hint">Nothing logged yet.</p></div>';
    }
    return entries.map(function (a) {
      return '<div class="feed-item' + (compact ? ' feed-compact' : '') + '">' +
        '<span class="feed-icon">' + esc(a.icon) + '</span>' +
        '<span class="feed-text">' + esc(a.text) + '</span>' +
        (compact ? '' : '<span class="feed-kind">' + esc(a.kind) + '</span>') +
        '<span class="feed-time">' + esc(relTime(a.ts)) + '</span>' +
        '</div>';
    }).join('');
  }

  function renderJournal() {
    const history = state.history || {};
    const series = history.series || [];
    const today = (state.meta && state.meta.today) || '';
    const c = state.character;

    $('#heatmap').innerHTML = series.map(function (s, i) {
      const label = fmt(s.count) + ' quest' + (s.count === 1 ? '' : 's') + ' on ' + s.day;
      return '<div class="heat-cell l' + clamp(num(s.level, 0), 0, 4) +
        (s.day === today ? ' today' : '') + '" data-action="heat" title="' + esc(label) + '" ' +
        'style="animation-delay:' + (i * 16) + 'ms"></div>';
    }).join('');

    const tiles = [
      ['Quests (30d)', fmt(history.total_completions)],
      ['XP earned', fmt(history.total_xp)],
      ['Active days', fmt(history.active_days) + '/30'],
      ['Day streak', fmt(c.day_streak)],
      ['Best streak', fmt(c.best_day_streak)],
    ];
    $('#journal-stats').innerHTML = tiles.map(function (t) {
      return '<div class="jstat"><span class="jstat-value">' + t[1] + '</span>' +
        '<span class="jstat-label">' + t[0] + '</span></div>';
    }).join('');

    const top = history.top_tasks || [];
    const max = top.reduce(function (m, t) { return Math.max(m, num(t.count, 0)); }, 0) || 1;
    $('#top-tasks').innerHTML = top.length ? top.map(function (t) {
      const colour = t.color || '#f59e0b';
      const pct = clamp(Math.round((num(t.count, 0) / max) * 100), 4, 100);
      return '<div class="top-task">' +
        '<span class="top-task-name"><span style="color:' + esc(colour) + '">' + esc(t.icon) + '</span> ' +
        esc(t.name) + '</span>' +
        // .top-task-bar is the dark track; the <i> inside it is the coloured fill,
        // so the bar's length still carries the ranking information.
        '<span class="top-task-bar" style="--bar-color:' + esc(colour) + '">' +
        '<i style="width:' + pct + '%"></i></span>' +
        '<span class="jstat-value">' + fmt(t.count) + '</span>' +
        '</div>';
    }).join('') : '<div class="empty-state"><p class="hint">Complete a few quests to rank them here.</p></div>';

    $('#achievement-grid').innerHTML = (state.achievements || []).map(function (a) {
      return '<div class="achievement' + (a.unlocked ? '' : ' locked') + '" title="' + esc(a.desc) + '">' +
        '<span class="ach-icon">' + esc(a.icon) + '</span>' +
        '<span class="ach-name">' + esc(a.name) + '</span>' +
        '<span class="ach-desc">' + esc(a.desc) + '</span>' +
        '<span class="ach-bar"><span class="ach-bar-fill" style="width:' + clamp(num(a.percent, 0), 0, 100) + '%"></span></span>' +
        '<span class="ach-progress">' + fmt(a.progress) + '/' + fmt(a.goal) + '</span>' +
        '</div>';
    }).join('');

    $('#activity-feed').innerHTML = feedHTML(state.activity || []);
  }

  /* ======================================================================
     RENDER DISPATCH
     ====================================================================== */
  function renderActiveView() {
    if (!state || !state.has_character) return;
    if (activeTab === 'character') renderHero();
    else if (activeTab === 'tasks') renderQuests();
    else if (activeTab === 'shop') renderShop();
    else if (activeTab === 'journal') renderJournal();
  }

  function refresh() {
    renderChrome();
    renderActiveView();
    renderDock();
    renderHealth();
  }

  function setTab(tab) {
    if (!TAB_LABEL[tab]) return;
    activeTab = tab;
    $$('#nav .nav-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    ['character', 'tasks', 'shop', 'journal'].forEach(function (name) {
      const view = $('#view-' + name);
      if (view) view.classList.toggle('active', name === tab);
    });
    renderActiveView();
  }

  function applyState(next) {
    state = next || {};
    if (state.server_now) syncClock(state.server_now);

    if (!state.has_character) {
      $('#onboarding').classList.remove('hidden');
      $('#app').classList.add('hidden');
      renderOnboarding();
      renderDock();          // hides the dock and stops the tick loop
      return;
    }
    $('#onboarding').classList.add('hidden');
    $('#app').classList.remove('hidden');
    if (!selectedArchetype) selectedArchetype = state.character.archetype;

    seedAnnounced(state.session);
    refresh();

    // Hits the server resolved while we were away are replayed here.
    (state.settled || []).forEach(function (item) {
      const task = (state.tasks || []).filter(function (t) { return t.id === item.task_id; })[0];
      playHit(item.damage, task ? task.name : '');
    });
  }

  /* ======================================================================
     QUEST FORM MODAL
     ====================================================================== */
  function openTaskModal(task) {
    const editing = !!task;
    const meta = state.meta || {};
    const icons = meta.icons || ['📚'];
    const colors = meta.colors || ['#f59e0b'];
    const difficulties = meta.difficulties || [{ id: 'easy', label: 'Easy', multiplier: 1 }];
    const modes = meta.session_modes ||
      [{ id: 'instant', label: 'Instant', icon: '⚡', timed: false, blurb: 'No timer.' }];
    const presets = meta.duration_presets || [5, 10, 15, 20, 30, 45, 60];
    const minMinutes = num(meta.session_min_minutes, 1) || 1;
    const maxMinutes = num(meta.session_max_minutes, 240) || 240;

    const icon = (task && task.icon) || icons[0];
    const color = (task && task.color) || colors[0];
    const mode = (task && task.mode) || 'instant';
    const duration = clamp(num(task && task.duration_minutes, 0) || 20, minMinutes, maxMinutes);

    const body = '' +
      '<form id="hq-task-form" class="form-grid" autocomplete="off">' +
      '<div class="form-row"><label class="field"><span class="field-label">Quest name</span>' +
      '<input id="hq-task-name" class="input" type="text" maxlength="60" required ' +
      'placeholder="Read 10 pages" value="' + esc(task ? task.name : '') + '"></label></div>' +

      '<div class="form-row"><label class="field"><span class="field-label">Notes (optional)</span>' +
      '<input id="hq-task-desc" class="input" type="text" maxlength="160" ' +
      'placeholder="Why this matters" value="' + esc(task ? task.description : '') + '"></label></div>' +

      '<div class="form-row">' +
      '<label class="field"><span class="field-label">Trains</span>' +
      '<select id="hq-task-stat" class="input">' +
      (meta.stats || []).map(function (s) {
        return '<option value="' + esc(s.key) + '"' +
          (task && task.stat === s.key ? ' selected' : '') + '>' +
          esc(s.label) + ' (' + esc(s.abbr) + ')</option>';
      }).join('') + '</select></label>' +

      '<label class="field"><span class="field-label">Difficulty</span>' +
      '<select id="hq-task-diff" class="input">' +
      difficulties.map(function (d) {
        return '<option value="' + esc(d.id) + '"' +
          (task && task.difficulty === d.id ? ' selected' : '') + '>' +
          esc(d.label) + ' · ×' + d.multiplier + '</option>';
      }).join('') + '</select></label>' +
      '</div>' +

      '<div class="form-row">' +
      '<label class="field"><span class="field-label">Base XP</span>' +
      '<input id="hq-task-xp" class="input" type="number" min="0" max="500" step="1" value="' +
      num(task ? task.xp : 10, 10) + '"></label>' +
      '<label class="field"><span class="field-label">Base gold</span>' +
      '<input id="hq-task-coins" class="input" type="number" min="0" max="500" step="1" value="' +
      num(task ? task.coins : 8, 8) + '"></label>' +
      '</div>' +

      '<div class="form-row"><div class="field"><span class="field-label">Session type</span>' +
      '<div class="mode-picker" id="hq-mode-picker">' +
      modes.map(function (m) {
        return '<button type="button" class="mode-card' + (m.id === mode ? ' selected' : '') +
          '" data-action="pick-mode" data-mode="' + esc(m.id) + '">' +
          '<span class="mode-icon">' + esc(m.icon) + '</span>' +
          '<span class="mode-name">' + esc(m.label) + '</span>' +
          '<span class="mode-blurb">' + esc(m.blurb) + '</span>' +
          (m.example ? '<span class="mode-example">e.g. ' + esc(m.example) + '</span>' : '') +
          '</button>';
      }).join('') + '</div></div></div>' +

      '<div class="form-row"><div class="field duration-wrap' +
      (mode === 'instant' ? ' hidden' : '') + '" id="hq-duration-wrap">' +
      '<span class="field-label">Session length</span>' +
      '<div class="duration-row" id="hq-duration-presets">' +
      presets.map(function (m) {
        return '<button type="button" class="duration-preset' +
          (num(m, 0) === duration ? ' active' : '') + '" data-action="pick-duration" ' +
          'data-minutes="' + num(m, 0) + '">' + esc(presetLabel(m)) + '</button>';
      }).join('') + '</div>' +
      '<input id="hq-task-duration" class="input duration-input" type="number" min="' +
      minMinutes + '" max="' + maxMinutes + '" step="1" value="' + duration + '" ' +
      'aria-label="Session length in minutes">' +
      '</div></div>' +

      '<div class="form-row"><div class="field"><span class="field-label">Icon</span>' +
      '<div class="icon-picker" id="hq-icon-picker">' +
      icons.map(function (i) {
        return '<button type="button" class="icon-choice' + (i === icon ? ' selected' : '') +
          '" data-action="pick-icon" data-icon="' + esc(i) + '">' + esc(i) + '</button>';
      }).join('') + '</div></div></div>' +

      '<div class="form-row"><div class="field"><span class="field-label">Colour</span>' +
      '<div class="chip-row" id="hq-color-picker">' +
      colors.map(function (c) {
        return '<button type="button" class="color-choice' + (c === color ? ' selected' : '') +
          '" data-action="pick-color" data-color="' + esc(c) + '" ' +
          'style="background:' + esc(c) + '" aria-label="' + esc(c) + '"></button>';
      }).join('') + '</div></div></div>' +

      '<p class="hint" id="hq-reward-preview"></p>' +

      '<div class="form-actions">' +
      '<button type="submit" class="btn btn-primary">' +
      (editing ? 'Save changes' : 'Create quest') + '</button>' +
      '<button type="button" class="btn btn-ghost" data-action="close-modal">Cancel</button>' +
      '</div>' +
      '</form>';

    openModal(editing ? 'Edit quest' : 'New quest', body, function () {
      const form = $('#hq-task-form');
      form._icon = icon;
      form._color = color;
      form._mode = mode;
      form._duration = duration;

      function modeInfo() {
        for (let i = 0; i < modes.length; i++) {
          if (modes[i].id === form._mode) return modes[i];
        }
        return modes[0] || { id: 'instant', label: 'Instant', timed: false };
      }

      function preview() {
        const diff = $('#hq-task-diff').value;
        let mult = 1;
        for (let i = 0; i < difficulties.length; i++) {
          if (difficulties[i].id === diff) mult = num(difficulties[i].multiplier, 1);
        }
        const xp = num($('#hq-task-xp').value, 0) * mult;
        const gold = num($('#hq-task-coins').value, 0) * mult;
        let line = 'Worth about ' + fmt(xp) + ' XP and ' + fmt(gold) +
          ' gold per completion, before streak and daily bonuses.';
        const info = modeInfo();
        if (info.id === 'beat_clock') {
          line += ' Beat the Clock pays a bonus for finishing early — miss the bell and you take a hit.';
        } else if (info.id === 'endure') {
          line += ' Stay the Course pays +15% for sitting the whole ' +
            minutesLabel(form._duration) + '.';
        }
        $('#hq-reward-preview').textContent = line;
      }

      function markPresets() {
        $$('#hq-duration-presets .duration-preset').forEach(function (b) {
          b.classList.toggle('active', num(b.dataset.minutes, 0) === num(form._duration, 0));
        });
      }

      function syncMode() {
        const wrap = $('#hq-duration-wrap');
        if (wrap) wrap.classList.toggle('hidden', (form._mode || 'instant') === 'instant');
        markPresets();
        preview();
      }

      // The delegated click handler lives outside this closure, so the form
      // carries the bits it needs - same pattern as _icon / _color above.
      form._preview = preview;
      form._syncMode = syncMode;

      preview();
      markPresets();
      $('#hq-task-diff').addEventListener('change', preview);
      $('#hq-task-xp').addEventListener('input', preview);
      $('#hq-task-coins').addEventListener('input', preview);
      const durationInput = $('#hq-task-duration');
      if (durationInput) {
        durationInput.addEventListener('input', function () {
          form._duration = clamp(num(durationInput.value, 20), minMinutes, maxMinutes);
          markPresets();
          preview();
        });
      }

      form.addEventListener('submit', async function (ev) {
        ev.preventDefault();
        const durationField = $('#hq-task-duration');
        const payload = {
          name: $('#hq-task-name').value.trim(),
          description: $('#hq-task-desc').value.trim(),
          stat: $('#hq-task-stat').value,
          difficulty: $('#hq-task-diff').value,
          xp: num($('#hq-task-xp').value, 0),
          coins: num($('#hq-task-coins').value, 0),
          icon: form._icon,
          color: form._color,
          mode: form._mode || 'instant',
          duration_minutes: (form._mode || 'instant') === 'instant' ? 0
            : clamp(num(durationField && durationField.value, form._duration || 20),
                    minMinutes, maxMinutes),
        };
        if (!payload.name) { toast('Give your quest a name.', 'error'); return; }
        try {
          const res = editing
            ? await api('PUT', '/api/tasks/' + task.id, payload)
            : await api('POST', '/api/tasks', payload);
          closeModal();
          applyState(res.state);
          setTab('tasks');
          toast(editing ? 'Quest updated.' : 'New quest added to your board.', 'success');
        } catch (err) {
          toast(err.message, 'error');
        }
      });

      window.setTimeout(function () { $('#hq-task-name').focus(); }, 40);
    });
  }

  function confirmModal(title, message, confirmLabel, actionName, payload) {
    const dataAttrs = Object.keys(payload || {}).map(function (k) {
      return ' data-' + k + '="' + esc(payload[k]) + '"';
    }).join('');
    openModal(title,
      '<p class="onboarding-sub">' + esc(message) + '</p>' +
      '<div class="form-actions">' +
      '<button type="button" class="btn btn-danger" data-action="' + esc(actionName) + '"' +
      dataAttrs + '>' + esc(confirmLabel) + '</button>' +
      '<button type="button" class="btn btn-ghost" data-action="close-modal">Cancel</button>' +
      '</div>');
  }

  /* ======================================================================
     ACTIONS
     ====================================================================== */
  async function doComplete(id, btn) {
    let rect = null;
    if (btn && btn.getBoundingClientRect) rect = btn.getBoundingClientRect();
    try {
      const res = await api('POST', '/api/tasks/' + id + '/complete');
      const r = res.rewards || {};
      const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
      const y = rect ? rect.top : window.innerHeight / 3;

      spawnFloat('+' + fmt(r.xp) + ' XP', 'xp',
        clamp(x - 24, 8, window.innerWidth - 80), clamp(y - 6, 8, window.innerHeight - 30));
      spawnFloat('+' + fmt(r.coins) + ' gold', 'coin',
        clamp(x + 14, 8, window.innerWidth - 100), clamp(y + 20, 8, window.innerHeight - 30));

      pendingXpGain = num(r.xp, 0);
      applyState(res.state);

      let msg = '+' + fmt(r.xp) + ' XP · +' + fmt(r.coins) + ' gold';
      if (num(r.streak, 1) > 1) msg += ' · 🔥 ' + r.streak + ' day streak';
      if (r.daily_bonus) msg += ' · first quest today';
      toast(msg, 'success');

      const unlocked = res.unlocked || [];
      if (res.level_up) showLevelUp(res.level_up, unlocked);
      else unlocked.forEach(function (a, i) {
        window.setTimeout(function () {
          toast('Achievement unlocked: ' + a.name, 'gold');
        }, 350 + i * 450);
      });
    } catch (err) {
      toast(err.message, 'error');
      refresh();
    }
  }

  function showLevelUp(levelUp, unlocked) {
    let body = '<p class="onboarding-sub">You grew from level ' + fmt(levelUp.from_level) +
      ' to <b>level ' + fmt(levelUp.to_level) + '</b>.</p>' +
      '<div class="modal-xp-list">' +
      '<div class="unlock-row"><span class="feed-icon">✨</span>' +
      '<span class="feed-text">+' + fmt(levelUp.points) + ' skill points to spend</span></div>' +
      '</div>';

    if (unlocked.length) {
      body += '<h4 class="panel-title mt">Achievements unlocked</h4><div class="modal-unlock-list">' +
        unlocked.map(function (a) {
          return '<div class="unlock-row"><span class="ach-icon">' + esc(a.icon) + '</span>' +
            '<span><span class="ach-name">' + esc(a.name) + '</span>' +
            '<span class="ach-desc">' + esc(a.desc) + '</span></span></div>';
        }).join('') + '</div>';
    }
    body += '<div class="form-actions">' +
      '<button type="button" class="btn btn-primary" data-action="close-modal">Onward!</button>' +
      '<button type="button" class="btn btn-ghost" data-action="goto-tab" data-tab="character">Spend points</button>' +
      '</div>';

    openModal('Level ' + fmt(levelUp.to_level) + '!', body);
    burst($('#modal'));
  }

  async function act(path, body, successMessage, tab) {
    try {
      const res = await api('POST', path, body);
      applyState(res.state);
      if (tab) setTab(tab);
      if (successMessage) toast(successMessage, 'success');
      (res.unlocked || []).forEach(function (a) {
        window.setTimeout(function () { toast('Achievement unlocked: ' + a.name, 'gold'); }, 400);
      });
      return res;
    } catch (err) {
      toast(err.message, 'error');
      return null;
    }
  }

  /* ======================================================================
     EVENT WIRING
     ====================================================================== */
  function bindEvents() {
    document.addEventListener('click', function (ev) {
      const el = ev.target.closest('[data-action], [data-tab], [data-goto]');
      if (!el) return;

      if (el.dataset.goto) { setTab(el.dataset.goto); return; }

      const action = el.dataset.action;
      if (!action) {
        if (el.dataset.tab) setTab(el.dataset.tab);
        return;
      }

      switch (action) {
        case 'pick-arch':
          selectedArchetype = el.dataset.id;
          $$('#arch-grid .arch-card').forEach(function (c) {
            c.classList.toggle('selected', c.dataset.id === selectedArchetype);
          });
          break;

        case 'start':
          startGame();
          break;

        case 'demo':
          loadDemo();
          break;

        case 'new-task':
          openTaskModal(null);
          break;

        case 'complete':
          doComplete(el.dataset.id, el);
          break;

        case 'start-session':
          startSession(num(el.dataset.id, 0));
          break;

        case 'undo':
          act('/api/tasks/' + el.dataset.id + '/undo', undefined, 'Completion undone.', 'tasks');
          break;

        case 'edit': {
          const id = num(el.dataset.id, 0);
          const task = (state.tasks || []).filter(function (t) { return t.id === id; })[0];
          if (task) openTaskModal(task);
          break;
        }

        case 'delete': {
          const id = num(el.dataset.id, 0);
          const task = (state.tasks || []).filter(function (t) { return t.id === id; })[0];
          if (task) {
            confirmModal('Abandon this quest?',
              '"' + task.name + '" and its entire history will be removed permanently.',
              'Delete forever', 'confirm-delete', { id: id });
          }
          break;
        }

        case 'confirm-delete':
          (async function () {
            try {
              const res = await api('DELETE', '/api/tasks/' + el.dataset.id);
              closeModal();
              applyState(res.state);
              toast('Quest deleted.', 'info');
            } catch (err) { toast(err.message, 'error'); }
          })();
          break;

        case 'upgrade':
          act('/api/skills/upgrade', { stat: el.dataset.stat, amount: 1 }, null, null);
          break;

        case 'filter-shop':
          shopFilter = el.dataset.filter;
          renderShop();
          break;

        case 'buy': {
          const item = el.dataset.item;
          const found = (state.shop || []).filter(function (i) { return i.id === item; })[0];
          act('/api/shop/buy', { item_id: item },
            found ? found.name + ' is yours!' : 'Purchased.', 'shop');
          break;
        }

        case 'equip': {
          const item = el.dataset.item;
          const found = (state.shop || []).filter(function (i) { return i.id === item; })[0];
          act('/api/shop/equip', { item_id: item },
            found ? found.name + ' equipped.' : 'Equipped.', null);
          break;
        }

        case 'unequip': {
          const item = el.dataset.item;
          const found = (state.shop || []).filter(function (i) { return i.id === item; })[0];
          if (found) {
            act('/api/shop/unequip', { slot: found.slot }, found.name + ' stowed.', null);
          } else {
            act('/api/shop/unequip', { slot: el.dataset.slot || '' }, 'Unequipped.', null);
          }
          break;
        }

        case 'unequip-slot':
          act('/api/shop/unequip', { slot: el.dataset.slot }, 'Unequipped.', null);
          break;

        case 'reset':
          confirmModal('Reset your save?',
            'This erases your hero, every quest, all gold and gear. There is no undo.',
            'Wipe the save', 'confirm-reset', {});
          break;

        case 'confirm-reset':
          (async function () {
            try {
              const res = await api('POST', '/api/reset');
              closeModal();
              lastXpPercent = null;
              applyState(res.state);
              toast('A new legend begins.', 'info');
            } catch (err) { toast(err.message, 'error'); }
          })();
          break;

        case 'close-modal':
          closeModal();
          break;

        case 'goto-tab':
          closeModal();
          setTab(el.dataset.tab);
          break;

        case 'pick-mode': {
          const form = el.closest('#hq-task-form');
          if (!form) break;
          form._mode = el.dataset.mode;
          $$('#hq-mode-picker .mode-card').forEach(function (b) {
            b.classList.toggle('selected', b.dataset.mode === form._mode);
          });
          if (typeof form._syncMode === 'function') form._syncMode();
          break;
        }

        case 'pick-duration': {
          const form = el.closest('#hq-task-form');
          if (!form) break;
          const minutes = num(el.dataset.minutes, 20);
          form._duration = minutes;
          const input = $('#hq-task-duration');
          if (input) input.value = minutes;
          $$('#hq-duration-presets .duration-preset').forEach(function (b) {
            b.classList.toggle('active', num(b.dataset.minutes, 0) === minutes);
          });
          if (typeof form._preview === 'function') form._preview();
          break;
        }

        case 'pick-icon': {
          const form = el.closest('#hq-task-form');
          if (form) form._icon = el.dataset.icon;
          $$('#hq-icon-picker .icon-choice').forEach(function (b) {
            b.classList.toggle('selected', b.dataset.icon === (form ? form._icon : null));
          });
          break;
        }

        case 'pick-color': {
          const form = el.closest('#hq-task-form');
          if (form) form._color = el.dataset.color;
          $$('#hq-color-picker .color-choice').forEach(function (b) {
            b.classList.toggle('selected', b.dataset.color === (form ? form._color : null));
          });
          break;
        }

        default:
          break;
      }
    });

    /* modal backdrop + close button + escape */
    $('#modal-backdrop').addEventListener('click', function (ev) {
      if (ev.target === $('#modal-backdrop')) closeModal();
    });
    const modalClose = $('#modal-close');
    if (modalClose) modalClose.addEventListener('click', function () { closeModal(); });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeModal();
      if (ev.key === 'Enter' && ev.target && ev.target.id === 'hero-name') {
        ev.preventDefault();
        startGame();
      }
      if (ev.key >= '1' && ev.key <= '4' && !ev.target.closest('input, select, textarea') &&
          $('#modal-backdrop').classList.contains('hidden') && state && state.has_character) {
        setTab(['character', 'tasks', 'shop', 'journal'][num(ev.key, 1) - 1]);
      }
    });

    /* onboarding buttons (the shell does not tag them with data-action) */
    const startBtn = $('#start-btn');
    if (startBtn) startBtn.addEventListener('click', function () { startGame(); });
    const demoBtn = $('#demo-btn');
    if (demoBtn) demoBtn.addEventListener('click', function () { loadDemo(); });

    /* session dock controls: static markup, so they carry no data-action */
    const dockFinish = $('#dock-finish');
    if (dockFinish) dockFinish.addEventListener('click', function () { finishSession(); });

    const dockAbandon = $('#dock-abandon');
    if (dockAbandon) dockAbandon.addEventListener('click', function () { giveUpSession(); });

    const dockBell = $('#dock-bell');
    if (dockBell) {
      dockBell.addEventListener('click', function () {
        unlockAudio();
        setBellMuted(!bellMuted);
        dockBell.textContent = bellMuted ? '🔕' : '🔔';
        if (!bellMuted) ringBell('served');   // a confirmation chime you can actually hear
      });
    }

    $('#new-task-btn').addEventListener('click', function () { openTaskModal(null); });
    $('#reset-btn').addEventListener('click', function () {
      confirmModal('Reset your save?',
        'This erases your hero, every quest, all gold and gear. There is no undo.',
        'Wipe the save', 'confirm-reset', {});
    });
  }

  async function loadDemo() {
    try {
      const res = await api('POST', '/api/demo', { force: false });
      applyState(res.state);
      setTab('character');
      toast('Demo save loaded — a month of quests awaits.', 'gold');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function startGame() {
    const input = $('#hero-name');
    const name = (input && input.value ? input.value : '').trim() || 'Adventurer';
    try { window.localStorage.setItem('hq.heroName', name); } catch (e) { /* ignore */ }
    try {
      const res = await api('POST', '/api/character',
        { name: name, archetype: selectedArchetype || 'warrior' });
      applyState(res.state);
      setTab('tasks');
      toast('Welcome, ' + name + '! Your quest board is ready.', 'gold');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  /* ======================================================================
     BOOT
     ====================================================================== */
  async function boot() {
    bindEvents();
    readBellPref();

    try {
      const remembered = window.localStorage.getItem('hq.heroName');
      if (remembered && $('#hero-name')) $('#hero-name').value = remembered;
    } catch (e) { /* ignore */ }

    try {
      const initial = await api('GET', '/api/state');
      applyState(initial);        // restores the dock if a session is mid-countdown
      ensureTicker();
    } catch (err) {
      toast(err.message || 'Could not load your save.', 'error');
      const meta = { archetypes: [], stats: [], icons: [], colors: [], difficulties: [] };
      applyState({ has_character: false, meta: meta });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
