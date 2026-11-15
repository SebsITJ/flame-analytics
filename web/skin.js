/* FLAME ANALYTICS visual motion layer. Decorative only; does not touch app state or API behavior. */
(() => {
  "use strict";
  const scene = document.querySelector('.ff-orb-scene');
  const stage = document.getElementById('stage-ask');
  const shape = document.querySelector('.ff-orb-shape');
  const glow = document.querySelector('.ff-orb-glow');
  if (!scene || !stage || !shape || !glow) return;

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const N = 64, CX = 300, CY = 300, TAU = Math.PI * 2;
  let pointerX = 0, pointerY = 0, currentX = 0, currentY = 0;
  let pressure = 0, targetPressure = 0, ripple = 0, targetRipple = 0;
  let phase = 0, direction = 1, lastWheel = 0, lastTime = performance.now();
  const points = Array.from({ length: N }, (_, i) => {
    const a = i * TAU / N;
    return { a, radius: 233 + 12 * Math.sin(a * 3 + .5) + 8 * Math.cos(a * 5 - 1.2) + 5 * Math.sin(a * 2 + 1.7) };
  });

  function pathFrom(coords) {
    let d = '';
    for (let i = 0; i < N; i++) {
      const p0 = coords[(i - 1 + N) % N], p1 = coords[i], p2 = coords[(i + 1) % N], p3 = coords[(i + 2) % N];
      if (i === 0) d = `M${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`;
      const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
    }
    return d + ' Z';
  }

  function tick(now) {
    const dt = Math.min(2.5, Math.max(.25, (now - lastTime) / 16.67));
    lastTime = now;
    const follow = 1 - Math.pow(.978, dt);
    currentX += (pointerX - currentX) * follow;
    currentY += (pointerY - currentY) * follow;
    pressure += (targetPressure - pressure) * (1 - Math.pow(.984, dt));
    ripple += (targetRipple - ripple) * (1 - Math.pow(.982, dt));
    targetRipple *= Math.pow(.992, dt);
    if (!reduce.matches) phase += .008 * dt;

    const driftX = reduce.matches ? 0 : 8 * Math.sin(phase * .42) + 3 * Math.sin(phase * .2 + 1.2);
    const driftY = reduce.matches ? 0 : 9 * Math.cos(phase * .36) + 3 * Math.sin(phase * .18);
    const angle = Math.atan2(currentY, currentX);
    const coords = points.map(({ a, radius }) => {
      const delta = Math.atan2(Math.sin(a - angle), Math.cos(a - angle));
      const local = Math.exp(-(delta * delta) / .78);
      const opposite = Math.exp(-Math.pow(Math.abs(delta) - Math.PI, 2) / 1.15);
      const breathe = reduce.matches ? 0 : 10 * Math.sin(a * 2 + phase) + 7 * Math.sin(a * 3 - phase * .62) + 4.5 * Math.cos(a * 5 + phase * .4);
      const scrollWave = reduce.matches ? 0 : ripple * (7 * Math.sin(a * 2 - phase * direction) + 3.5 * Math.cos(a * 3 + phase * .5));
      const touch = pressure * (10 * local - 3.5 * opposite + 2 * Math.sin(a * 2 + phase));
      const r = radius + breathe + scrollWave + touch;
      return { x: CX + Math.cos(a) * r + pressure * currentX * 2 + driftX, y: CY + Math.sin(a) * r + pressure * currentY * 2 + driftY };
    });
    const d = pathFrom(coords);
    shape.setAttribute('d', d);
    glow.setAttribute('d', d);
    if (!reduce.matches) {
      scene.style.setProperty('--ff-hx', `${50 + 20 * Math.sin(phase * .37)}%`);
      scene.style.setProperty('--ff-hy', `${48 + 18 * Math.cos(phase * .3)}%`);
    }
    requestAnimationFrame(tick);
  }

  stage.addEventListener('pointermove', (event) => {
    if (reduce.matches || event.pointerType === 'touch') return;
    const rect = scene.getBoundingClientRect();
    const nx = (event.clientX - (rect.left + rect.width / 2)) / (rect.width * .48);
    const ny = (event.clientY - (rect.top + rect.height / 2)) / (rect.height * .48);
    const distance = Math.hypot(nx, ny);
    pointerX = Math.max(-1, Math.min(1, nx));
    pointerY = Math.max(-1, Math.min(1, ny));
    targetPressure = distance < 1.35 ? .68 : 0;
  }, { passive: true });
  stage.addEventListener('pointerleave', () => { pointerX = pointerY = targetPressure = 0; }, { passive: true });
  window.addEventListener('wheel', (event) => {
    if (reduce.matches || performance.now() - lastWheel < 120) return;
    targetRipple = Math.max(targetRipple, .55);
    direction = event.deltaY >= 0 ? 1 : -1;
    lastWheel = performance.now();
  }, { passive: true });
  reduce.addEventListener?.('change', () => { pointerX = pointerY = targetPressure = targetRipple = ripple = 0; });
  requestAnimationFrame(tick);
})();
