/* StockSentry front-end: theme, modal, live filtering, sorting, quick stock adjust, donut chart. */
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const LABEL = { ok: 'In stock', low: 'Low', out: 'Out' };

  /* theme */
  const themeBtn = $('#themeBtn');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('ss-theme', next); } catch (e) {}
    drawDonut();
  });

  /* toasts */
  function toast(msg, kind = '') {
    const box = $('#toasts'); if (!box) return;
    const t = document.createElement('div');
    t.className = 'toast ' + kind; t.textContent = msg; box.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = '.3s'; setTimeout(() => t.remove(), 300); }, 2800);
  }

  /* auto-dismiss flashes */
  $$('.flashes .flash').forEach(f => setTimeout(() => { f.style.transition = '.4s'; f.style.opacity = '0'; setTimeout(() => f.remove(), 400); }, 5000));

  /* confirm on delete */
  $$('form[data-confirm]').forEach(f => f.addEventListener('submit', e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

  /* modals (product form + team dialogs) */
  const modal = $('#productModal');
  const form = $('#productForm');
  const closeAll = () => $$('.modal').forEach(m => { m.hidden = true; });
  function openModalEl(m) { closeAll(); m.hidden = false; setTimeout(() => { const f = $('input:not([type=hidden]), select', m); if (f) f.focus(); }, 30); }
  function openModal(data) {
    if (!modal) return;
    form.reset();
    if (data) {
      $('#modalTitle').textContent = 'Edit product';
      form.action = `/products/${data.id}/edit`;
      ['name', 'sku', 'category', 'supplier', 'unit', 'quantity', 'min_level', 'price'].forEach(k => { form.elements[k].value = data[k] ?? ''; });
    } else {
      $('#modalTitle').textContent = 'Add product';
      form.action = form.dataset.add;
    }
    openModalEl(modal);
  }
  const closeModal = closeAll;
  $$('[data-open]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.open === 'productModal') return openModal();
    const m = document.getElementById(b.dataset.open); if (!m) return;
    if (b.dataset.pwAction) { $('#pwForm').action = b.dataset.pwAction; $('#pwUser').textContent = b.dataset.pwUser; }
    openModalEl(m);
  }));
  $$('[data-close]').forEach(b => b.addEventListener('click', closeAll));
  $$('.modal').forEach(m => m.addEventListener('mousedown', e => { if (e.target === m) closeAll(); }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });
  $$('[data-edit]').forEach(b => b.addEventListener('click', () => openModal(JSON.parse(b.dataset.edit))));
  if (new URLSearchParams(location.search).get('new') === '1' && modal) openModal();
  $$('select[data-autosubmit]').forEach(s => s.addEventListener('change', () => s.form.submit()));

  /* import */
  const importBtn = $('#importBtn'), importFile = $('#importFile');
  if (importBtn) {
    importBtn.addEventListener('click', () => importFile.click());
    importFile.addEventListener('change', () => { if (importFile.files.length) $('#importForm').submit(); });
  }

  /* inventory filtering */
  const tbl = $('#tbl');
  if (tbl) {
    const rows = $$('tbody tr', tbl);
    const q = $('#q'), cat = $('#catFilter');
    let status = 'all';
    function apply() {
      const needle = q.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach(r => {
        const ok = (!needle || r.dataset.name.includes(needle)) &&
          (status === 'all' || r.dataset.status === status) &&
          (!cat.value || r.dataset.category === cat.value);
        r.classList.toggle('is-hidden', !ok); if (ok) shown++;
      });
      $('#noMatch').classList.toggle('hidden', shown > 0);
    }
    q.addEventListener('input', apply); cat.addEventListener('change', apply);
    $$('#statusChips .chip').forEach(c => c.addEventListener('click', () => {
      $$('#statusChips .chip').forEach(x => x.classList.remove('active')); c.classList.add('active');
      status = c.dataset.status; apply();
    }));
    document.addEventListener('keydown', e => {
      if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); q.focus(); }
    });

    /* sorting */
    let sortKey = null, desc = false;
    $$('th[data-sort]', tbl).forEach(th => th.addEventListener('click', () => {
      const key = th.dataset.sort;
      desc = sortKey === key ? !desc : false; sortKey = key;
      $$('th', tbl).forEach(x => x.classList.remove('sorted', 'desc')); th.classList.add('sorted'); if (desc) th.classList.add('desc');
      const body = tbl.tBodies[0];
      const val = r => { const v = r.dataset['sort' + key]; return isNaN(v) ? v : parseFloat(v); };
      [...rows].sort((a, b) => { const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * (desc ? -1 : 1); }).forEach(r => body.appendChild(r));
    }));

    /* quick stock adjust */
    tbl.addEventListener('click', async e => {
      const btn = e.target.closest('.qbtn'); if (!btn) return;
      const row = btn.closest('tr'); btn.disabled = true;
      try {
        const res = await fetch(`/products/${row.dataset.id}/adjust`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
          body: JSON.stringify({ delta: parseInt(btn.dataset.delta, 10) })
        });
        if (!res.ok) throw new Error('request failed');
        const d = await res.json();
        const was = row.dataset.status;
        $('[data-role="qty"]', row).textContent = d.quantity;
        const pill = $('[data-role="pill"]', row); pill.className = 'pill ' + d.status; pill.textContent = LABEL[d.status];
        const m = $('[data-role="meter"]', row); m.className = d.status; m.style.width = d.pct + '%';
        row.dataset.status = d.status; row.dataset.sortqty = d.quantity;
        row.dataset.sortstatus = { out: 0, low: 1, ok: 2 }[d.status];
        row.classList.remove('flash-row'); void row.offsetWidth; row.classList.add('flash-row');
        if (was !== d.status) {
          const name = $('.prod b', row).textContent;
          if (d.status === 'out') toast(`${name} is out of stock`, 'bad');
          else if (d.status === 'low') toast(`${name} is running low`, 'warn');
          else toast(`${name} is back in stock`);
        }
        apply();
      } catch (err) { toast('Could not update stock. Please retry.', 'bad'); }
      btn.disabled = false;
    });
  }

  /* dashboard donut + count-up */
  function drawDonut() {
    const c = $('#donut'); if (!c || !window.SS_DONUT) return;
    const css = getComputedStyle(document.documentElement);
    const d = window.SS_DONUT, total = d.ok + d.low + d.out || 1;
    const dpr = window.devicePixelRatio || 1, size = 220;
    c.width = size * dpr; c.height = size * dpr;
    const x = c.getContext('2d'); x.scale(dpr, dpr); x.clearRect(0, 0, size, size);
    const cx = size / 2, r = 86, lw = 20;
    x.lineWidth = lw; x.lineCap = 'round';
    x.strokeStyle = css.getPropertyValue('--panel2').trim(); x.beginPath(); x.arc(cx, cx, r, 0, Math.PI * 2); x.stroke();
    let start = -Math.PI / 2; const gap = 0.09;
    [['ok', '--ok'], ['low', '--warn'], ['out', '--bad']].forEach(([k, v]) => {
      if (!d[k]) return;
      const ang = (d[k] / total) * Math.PI * 2;
      const single = d[k] === total;
      x.strokeStyle = css.getPropertyValue(v).trim(); x.beginPath();
      x.arc(cx, cx, r, start + (single ? 0 : gap / 2), start + ang - (single ? 0 : gap / 2)); x.stroke();
      start += ang;
    });
  }
  drawDonut();

  $$('[data-count]').forEach(el => {
    const end = parseInt(el.dataset.count, 10); if (!end || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const t0 = performance.now(), dur = 700;
    (function tick(t) { const p = Math.min((t - t0) / dur, 1); el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); })(t0);
  });
})();
