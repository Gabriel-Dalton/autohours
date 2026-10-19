// The hero demo and the How it works walkthrough. Both show their finished state without JavaScript or with reduced motion.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Stagger positions live in data-i, because the security policy blocks inline style attributes.
  document.querySelectorAll("[data-i]").forEach(el => el.style.setProperty("--i", el.dataset.i));
  document.documentElement.classList.add("js");
  const minutes = value => { const m = Math.round(value); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; };

  // Hero: activity appears, gets a client, becomes timesheet entries, and the totals count up.
  const demo = document.getElementById("hero-demo");
  const replay = demo.querySelector(".replay");
  const counters = [...demo.querySelectorAll(".count")];
  const show = (value, el) => { el.textContent = el.dataset.amount ? `${value.toFixed(2)} CAD` : minutes(value); };
  const countUp = () => {
    const start = performance.now(), length = 900;
    const frame = now => {
      const t = Math.min(1, (now - start) / length), eased = 1 - Math.pow(1 - t, 3);
      for (const el of counters) show(eased * Number(el.dataset.minutes || el.dataset.amount), el);
      if (t < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  };
  let timers = [];
  const play = () => {
    timers.forEach(clearTimeout); timers = [];
    demo.className = "demo ready"; replay.hidden = true;
    for (const el of counters) show(0, el);
    const at = (ms, fn) => timers.push(setTimeout(fn, ms));
    at(150, () => demo.classList.add("s1"));
    at(1400, () => demo.classList.add("s2"));
    at(2700, () => { demo.classList.add("s3"); countUp(); });
    at(3500, () => demo.classList.add("s4"));
    at(4300, () => { demo.classList.add("s5"); replay.hidden = false; });
  };
  if (!reduce) {
    const seen = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { seen.disconnect(); play(); }
    }, {threshold: 0.35});
    demo.classList.add("ready");
    seen.observe(demo);
    replay.addEventListener("click", play);
  }

  // Walkthrough: on wide screens one window stays beside the steps; on narrow screens each step shows its own scene.
  const steps = [...document.querySelectorAll(".walk-step")];
  const stage = document.querySelector(".walk-stage .scene-frame");
  const scenes = [...stage.querySelectorAll(".scene")];
  const wide = matchMedia("(min-width: 56rem)");
  const bar = stage.querySelector(".app-bar");
  const place = () => {
    scenes.forEach((scene, i) => {
      if (wide.matches) { stage.append(scene); }
      else {
        const slot = steps[i].querySelector(".scene-slot");
        let frame = slot.querySelector(".scene-frame");
        if (!frame) { frame = document.createElement("div"); frame.className = "scene-frame"; frame.append(bar.cloneNode(true)); slot.append(frame); }
        frame.append(scene);
      }
    });
  };
  const activate = n => {
    steps.forEach(s => s.classList.toggle("active", s.dataset.scene === n));
    scenes.forEach(scene => {
      const on = scene.dataset.scene === n;
      if (wide.matches) scene.classList.toggle("active", on);
      if (on && !reduce) { scene.classList.remove("play"); void scene.offsetWidth; scene.classList.add("play"); }
    });
    countMinutes(n);
  };
  let ticker;
  const countMinutes = n => {
    clearInterval(ticker);
    const live = [...document.querySelectorAll(`.scene[data-scene="${n}"] .tick-up`)];
    live.forEach(el => { el.dataset.now = el.dataset.from; el.textContent = minutes(Number(el.dataset.from)); });
    if (reduce || !live.length) return;
    ticker = setInterval(() => live.forEach(el => { el.dataset.now = Number(el.dataset.now) + 1; el.textContent = minutes(Number(el.dataset.now)); }), 1200);
  };
  place();
  wide.addEventListener("change", () => { place(); activate(document.querySelector(".walk-step.active")?.dataset.scene || "1"); });
  const watch = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) activate(e.target.dataset.scene);
  }, {rootMargin: "-45% 0px -45% 0px"});
  steps.forEach(s => watch.observe(s));
  if (!reduce) {
    // On narrow screens, play each scene when it scrolls into view.
    const inline = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting && !wide.matches) {
        const scene = e.target.querySelector(".scene");
        if (scene) { scene.classList.remove("play"); void scene.offsetWidth; scene.classList.add("play"); countMinutes(scene.dataset.scene); }
      }
    }, {threshold: 0.4});
    document.querySelectorAll(".scene-slot").forEach(slot => inline.observe(slot));
  }
  activate("1");

  // Watch the video: scroll to the video section, then play it in a pop-up.
  const player = document.getElementById("player");
  const film = player.querySelector("video");
  const close = () => { film.pause(); if (player.open) player.close(); };
  document.querySelectorAll("[data-play-video]").forEach(link => link.addEventListener("click", event => {
    if (typeof player.showModal !== "function") return;
    event.preventDefault();
    document.getElementById("video").scrollIntoView({behavior: reduce ? "auto" : "smooth"});
    setTimeout(() => {
      player.showModal();
      film.play().catch(() => {});
    }, reduce ? 0 : 650);
  }));
  player.querySelector(".player-close").addEventListener("click", close);
  player.addEventListener("click", event => { if (event.target === player) close(); });
  player.addEventListener("close", () => film.pause());
})();
