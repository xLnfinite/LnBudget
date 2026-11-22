"use strict";
/* 轻量 Canvas 图表库：环形图 / 分组柱状图 / 折线图（带动画、悬浮提示、DPR 适配）。
   用法：const destroy = Charts.donut(canvas, items, opts)；返回的 destroy 用于清理。 */

const Charts = (() => {
  const fmt = (n) => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n) || 0);
  const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function moneyShort(n) {
    const v = Math.abs(Number(n) || 0);
    if (v >= 1e8) return (n / 1e8).toFixed(1) + "亿";
    if (v >= 1e4) return (n / 1e4).toFixed(1) + "万";
    if (v >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(Math.round(v * 100) / 100);
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const pow = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) {
      if (m * pow >= v) return m * pow;
    }
    return 10 * pow;
  }

  function setup(canvas, height) {
    const parent = canvas.parentElement;
    const w = Math.max(parent.clientWidth - 20, 220);
    const h = height || Math.round(w * 0.52);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h, canvas };
  }

  function tipFor(canvas) {
    let tip = canvas.parentElement.querySelector(".chart-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      canvas.parentElement.appendChild(tip);
    }
    return tip;
  }
  function showTip(canvas, x, y, html) {
    const tip = tipFor(canvas);
    tip.innerHTML = html;
    tip.style.left = Math.max(6, Math.min(x + 14, canvas.parentElement.clientWidth - tip.offsetWidth - 6)) + "px";
    tip.style.top = Math.max(6, y - tip.offsetHeight - 12) + "px";
    tip.classList.add("show");
  }
  function hideTip(canvas) {
    const tip = tipFor(canvas);
    if (tip) tip.classList.remove("show");
  }

  function animate(duration, draw) {
    let raf = 0;
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min((t - t0) / duration, 1);
      draw(1 - Math.pow(1 - p, 3));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }

  /* ================= 环形图 ================= */
  function donut(canvas, items, opts = {}) {
    const { ctx, w, h } = setup(canvas, opts.height);
    const cx = w / 2, cy = h / 2;
    // 环外沿（r + thick/2）必须落在画布内：maxR 留 6px 边距，容纳悬浮外移 5px
    const maxR = Math.min(w, h) / 2 - 6;
    let r = Math.max(maxR / 1.17, 20);   // 默认 thick = 0.34r 时，r + thick/2 = 1.17r <= maxR
    let thick = Math.max(20, r * 0.34);
    if (r + thick / 2 > maxR) r = maxR - thick / 2;   // 小画布兜底（thick 触发 20px 下限时）
    const total = items.reduce((a, b) => a + Number(b.value || 0), 0) || 1;
    let hover = -1;
    const bounds = [];
    let acc = 0;
    items.forEach((it) => {
      const f = Number(it.value || 0) / total;
      bounds.push([acc, acc + f]);
      acc += f;
    });

    function draw(prog) {
      ctx.clearRect(0, 0, w, h);
      if (!items.length) return;
      const sweep = Math.PI * 2 * prog;
      bounds.forEach(([a0, a1], i) => {
        const s = -Math.PI / 2 + a0 * Math.PI * 2;
        const e = -Math.PI / 2 + Math.min(a1 * Math.PI * 2, sweep);
        if (e <= s) return;
        const mid = (s + e) / 2;
        const off = hover === i ? 5 : 0;
        const ox = Math.cos(mid) * off, oy = Math.sin(mid) * off;
        ctx.beginPath();
        ctx.moveTo(cx + ox, cy + oy);
        ctx.arc(cx + ox, cy + oy, r - thick / 2, s, e);
        ctx.arc(cx + ox, cy + oy, r - thick / 2 + thick, e, s, true);
        ctx.closePath();
        ctx.fillStyle = items[i].color;
        ctx.fill();
      });
      const t = opts.centerText || [];
      if (t[0]) {
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.font = "600 12px system-ui, sans-serif";
        ctx.fillStyle = "#8a94a6";
        ctx.fillText(t[0], cx, cy - 10);
        ctx.font = "700 19px system-ui, sans-serif";
        ctx.fillStyle = "#111827";
        ctx.fillText(t[1] || "", cx, cy + 10);
      }
    }

    let cancel = animate(opts.duration || 700, draw);

    function onMove(e) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      const dx = x - cx, dy = y - cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < r - thick / 2 - 2 || dist > r - thick / 2 + thick + 6) {
        if (hover !== -1) { hover = -1; draw(1); hideTip(canvas); }
        return;
      }
      let ang = Math.atan2(dy, dx) + Math.PI / 2;
      if (ang < 0) ang += Math.PI * 2;
      let idx = -1;
      bounds.forEach(([a0, a1], i) => { if (ang >= a0 * Math.PI * 2 && ang <= a1 * Math.PI * 2) idx = i; });
      if (idx !== hover) { hover = idx; draw(1); }
      if (idx >= 0) {
        const it = items[idx];
        showTip(canvas, x, y, "<b>" + escHtml(it.label) + "</b><span>¥" + fmt(it.value) + " · " + (Number(it.value || 0) / total * 100).toFixed(1) + "%</span>");
      } else {
        hideTip(canvas);
      }
    }
    function onLeave() { hover = -1; draw(1); hideTip(canvas); }
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    return () => { cancel(); canvas.removeEventListener("mousemove", onMove); canvas.removeEventListener("mouseleave", onLeave); hideTip(canvas); };
  }

  /* ================= 分组柱状图 ================= */
  function bar(canvas, labels, series, opts = {}) {
    const { ctx, w, h } = setup(canvas, opts.height);
    const padL = 52, padR = 12, padT = 16, padB = 32;
    const plotW = w - padL - padR, plotH = h - padT - padB;
    const maxV = niceMax(Math.max(1, ...series.flatMap((s) => s.values.map((v) => Number(v) || 0))));
    const n = labels.length, g = series.length;
    const slot = n > 0 ? plotW / n : plotW;
    const barW = Math.min(26, (slot * 0.72) / g);
    let hover = -1;
    const yFmt = opts.yFmt || moneyShort;

    function draw(prog) {
      ctx.clearRect(0, 0, w, h);
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      const steps = 4;
      for (let i = 0; i <= steps; i++) {
        const v = maxV / steps * i;
        const y = padT + plotH - plotH * i / steps;
        ctx.strokeStyle = i === 0 ? "#d1d5db" : "#eef1f6";
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
        ctx.fillStyle = "#8a94a6";
        ctx.fillText(yFmt(v), padL - 8, y);
      }
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillStyle = "#8a94a6";
      const stepX = n > 10 ? 3 : (n > 7 ? 2 : 1);
      labels.forEach((lb, i) => { if (i % stepX === 0) ctx.fillText(lb, padL + slot * i + slot / 2, padT + plotH + 10); });
      series.forEach((s, gi) => {
        s.values.forEach((v, i) => {
          const val = Number(v) || 0;
          const bh = Math.max(val > 0 ? 1.5 : 0, plotH * (val / maxV) * prog);
          const x = padL + slot * i + (slot - barW * g) / 2 + gi * barW;
          const y = padT + plotH - bh;
          ctx.globalAlpha = (hover === -1 || hover === i) ? 1 : 0.45;
          rr(ctx, x, y, barW, Math.max(bh, 0), 3);
          ctx.fillStyle = s.color;
          ctx.fill();
        });
      });
      ctx.globalAlpha = 1;
    }

    let cancel = animate(opts.duration || 700, draw);

    function onMove(e) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      if (x < padL || x > w - padR || y < padT || y > padT + plotH) { if (hover !== -1) { hover = -1; draw(1); hideTip(canvas); } return; }
      const idx = Math.min(n - 1, Math.max(0, Math.floor((x - padL) / slot)));
      if (idx !== hover) { hover = idx; draw(1); }
      const rows = series.map((s) => "<span style=\"color:" + s.color + "\">● " + escHtml(s.name) + "：¥" + fmt(s.values[idx]) + "</span>").join("");
      showTip(canvas, x, y, "<b>" + escHtml(labels[idx] || "") + "</b>" + rows);
    }
    function onLeave() { hover = -1; draw(1); hideTip(canvas); }
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    return () => { cancel(); canvas.removeEventListener("mousemove", onMove); canvas.removeEventListener("mouseleave", onLeave); hideTip(canvas); };
  }

  /* ================= 折线图 ================= */
  function line(canvas, labels, series, opts = {}) {
    const { ctx, w, h } = setup(canvas, opts.height);
    const padL = 52, padR = 16, padT = 16, padB = 32;
    const plotW = w - padL - padR, plotH = h - padT - padB;
    const maxV = niceMax(Math.max(1, ...series.flatMap((s) => s.values.map((v) => Math.abs(Number(v) || 0)))));
    const n = labels.length;
    const xs = (i) => padL + (n <= 1 ? plotW / 2 : plotW * i / (n - 1));
    const ys = (v) => padT + plotH - plotH * (Number(v) || 0) / (maxV * 1.1);
    let hover = -1;
    const yFmt = opts.yFmt || moneyShort;

    function draw(prog) {
      ctx.clearRect(0, 0, w, h);
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      const steps = 4;
      for (let i = 0; i <= steps; i++) {
        const v = maxV * 1.1 / steps * i;
        const y = padT + plotH - plotH * i / steps;
        ctx.strokeStyle = i === 0 ? "#d1d5db" : "#eef1f6";
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
        ctx.fillStyle = "#8a94a6";
        ctx.fillText(yFmt(v), padL - 8, y);
      }
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillStyle = "#8a94a6";
      const stepX = n > 10 ? 3 : (n > 7 ? 2 : 1);
      labels.forEach((lb, i) => { if (i % stepX === 0) ctx.fillText(lb, xs(i), padT + plotH + 10); });
      series.forEach((s, si) => {
        const pts = s.values.map((v, i) => ({ x: xs(i), y: ys(v) }));
        if (si === 0 && opts.fill) {
          ctx.beginPath();
          ctx.moveTo(pts[0].x, padT + plotH);
          pts.forEach((p) => ctx.lineTo(p.x, p.y));
          ctx.lineTo(pts[pts.length - 1].x, padT + plotH);
          ctx.closePath();
          ctx.fillStyle = s.color + "18";
          ctx.fill();
        }
        ctx.beginPath();
        ctx.save();
        ctx.rect(padL, padT, plotW * prog, plotH);
        ctx.clip();
        pts.forEach((p, i) => { if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y); });
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 2.2;
        ctx.lineJoin = "round";
        ctx.stroke();
        ctx.restore();
        if (pts.length <= 16) {
          pts.forEach((p) => {
            ctx.beginPath(); ctx.arc(p.x, p.y, 3.4, 0, Math.PI * 2);
            ctx.fillStyle = "#fff"; ctx.fill();
            ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.stroke();
          });
        }
      });
      if (hover >= 0 && hover < n) {
        ctx.strokeStyle = "#cbd5e1";
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(xs(hover), padT); ctx.lineTo(xs(hover), padT + plotH); ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    let cancel = animate(opts.duration || 700, draw);

    function onMove(e) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      if (x < padL || x > w - padR || y < padT || y > padT + plotH) { if (hover !== -1) { hover = -1; draw(1); hideTip(canvas); } return; }
      const idx = Math.min(n - 1, Math.max(0, Math.round((x - padL) / (plotW / Math.max(n - 1, 1)))));
      if (idx !== hover) { hover = idx; draw(1); }
      const rows = series.map((s) => "<span style=\"color:" + s.color + "\">● " + escHtml(s.name) + "：¥" + fmt(s.values[idx]) + "</span>").join("");
      showTip(canvas, x, y, "<b>" + escHtml(labels[idx] || "") + "</b>" + rows);
    }
    function onLeave() { hover = -1; draw(1); hideTip(canvas); }
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    return () => { cancel(); canvas.removeEventListener("mousemove", onMove); canvas.removeEventListener("mouseleave", onLeave); hideTip(canvas); };
  }

  function rr(ctx, x, y, w, h, r) {
    const rad = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rad, y);
    ctx.arcTo(x + w, y, x + w, y + h, rad);
    ctx.arcTo(x + w, y + h, x, y + h, rad);
    ctx.arcTo(x, y + h, x, y, rad);
    ctx.arcTo(x, y, x + w, y, rad);
    ctx.closePath();
  }

  return { donut, bar, line, fmt, moneyShort };
})();