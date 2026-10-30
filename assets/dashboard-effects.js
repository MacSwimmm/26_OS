(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const canvas = $("#pixelField");
  const hero = $("#overview");
  const context = canvas?.getContext("2d", { alpha: true });
  if (!canvas || !hero || !context) return;

  const configKey = "teaflow-motion";
  let preferences = { enabled: true, speed: 1, spacing: 7 };
  try { preferences = { ...preferences, ...JSON.parse(localStorage.getItem(configKey) || "{}") }; } catch {}
  let width = 0, height = 0, dpr = 1, frame = 0;
  let lastDraw = 0;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)"),
    color = () => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#32f08c";

  function resize() {
    const box = hero.getBoundingClientRect();
    width = box.width;
    height = box.height;
    dpr = Math.min(devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function field(x, y, time) {
    const u = x / width, v = y / height;
    const warp = .1 * Math.sin(u * 8 + v * 5 + time * .3) + .06 * Math.sin(v * 14 - u * 7 - time * .24);
    const ridge = .64 + .17 * Math.sin(u * 6 - .9 + time * .35) + warp;
    const band = Math.exp(-(((v - ridge) / .19) ** 2));
    const leftCloud = Math.exp(-(((u + .03 + .06 * Math.sin(v * 8 + time * .2)) / .32) ** 2) - ((v - .38) / .43) ** 2);
    const rightCloud = .6 * Math.exp(-(((u - 1.02) / .16) ** 2) - ((v - .08 - .07 * Math.sin(time * .3)) / .18) ** 2);
    const grain = .62 + .38 * Math.sin(x * .019 + y * .025 + Math.sin(y * .013 - time * .4) * 2);
    const hollow = 1 - .9 * Math.exp(-(((u - .64) / .29) ** 2) - ((v - .28) / .24) ** 2);
    return Math.max(band, leftCloud, rightCloud) * (.6 + .4 * grain) * hollow;
  }

  function draw(now) {
    frame = 0;
    if (!preferences.enabled || document.hidden || hero.getBoundingClientRect().bottom < 0 || hero.getBoundingClientRect().top > innerHeight) return;
    if (now - lastDraw < 32) { frame = requestAnimationFrame(draw); return; }
    lastDraw = now;
    const time = reducedMotion.matches ? 0 : now * .0003 * preferences.speed;
    const accent = color();
    const rgb = /^#[a-f0-9]{6}$/i.test(accent) ? [1, 3, 5].map(i => parseInt(accent.slice(i, i + 2), 16)) : [50, 240, 140];
    const spacing = Number(preferences.spacing) || 7;
    const cell = spacing * (width > 1000 ? 1 : 1.1);
    context.clearRect(0, 0, width, height);
    for (let y = 12; y < height; y += cell) {
      for (let x = 3; x < width; x += cell) {
        const amount = field(x, y, time);
        const flicker = .65 + .35 * Math.sin((x * .021) + (y * .057) + time * 2.1);
        const grain = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
        const scatter = grain - Math.floor(grain);
        const opacity = Math.min(.82, Math.max(0, (amount - .16 - scatter * .25) * 1.3 * flicker));
        if (opacity < .035) continue;
        const green = Math.sin(x * .014 + y * .023 + time * .4) > .35 && scatter > .35;
        context.fillStyle = green ? `rgba(${rgb.map(c => Math.round(c * .65)).join(",")},${opacity * .7})` : `rgba(183,190,186,${opacity * .8})`;
        context.fillRect(Math.round(x), Math.round(y), Math.max(2, cell - 2), Math.max(2, cell - 2));
      }
    }
    if (!reducedMotion.matches) frame = requestAnimationFrame(draw);
  }

  function requestDraw() {
    if (!frame) frame = requestAnimationFrame(draw);
  }

  const resizeObserver = new ResizeObserver(() => { resize(); requestDraw(); });
  resizeObserver.observe(hero);
  resize();
  requestDraw();

  const scenarioNames = [
    ["baseline", "完整调度", "动态优先级与抢占", "↗"],
    ["no_dynamic", "静态调度", "固定顺序完成任务", "01"],
    ["no_deadlock", "关闭死锁保护", "观察资源冲突处理", "◇"],
    ["non_preemptive", "非抢占调度", "任务开始后连续执行", "Ⅱ"],
    ["compare", "调度策略对比", "并排查看实验结果", "⇄"],
    ["deadlock", "死锁避免与恢复", "比较三种处理策略", "⌘"],
  ];
  const menu = $("#scenarioMenu");
  const trigger = $("#scenarioTrigger");
  menu.innerHTML = scenarioNames.map(([id, label, description, icon], index) =>
    `<button class="scenario-choice" type="button" data-scenario="${id}"><span class="scenario-choice-icon">${icon}</span><span><strong>${label}</strong><small>${description}</small></span><kbd>0${index + 1}</kbd></button>`).join("");

  function closeMenu(focus = false) {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (focus) trigger.focus();
  }
  function openMenu() {
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    $(".scenario-choice", menu)?.focus();
  }
  trigger.addEventListener("click", openMenu);
  let menuCloseTimer;
  trigger.parentElement.addEventListener("pointerenter", event => {
    if (event.pointerType !== "mouse") return;
    clearTimeout(menuCloseTimer);
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  });
  trigger.parentElement.addEventListener("pointerleave", event => {
    if (event.pointerType === "mouse") menuCloseTimer = setTimeout(() => closeMenu(), 180);
  });
  trigger.addEventListener("keydown", event => { if (event.key === "ArrowDown") { event.preventDefault(); openMenu(); } });
  document.addEventListener("click", event => { if (!event.target.closest(".scenario-menu")) closeMenu(); });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !menu.hidden) closeMenu(true);
    if (menu.hidden || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
    const options = [...menu.querySelectorAll(".scenario-choice")], index = options.indexOf(document.activeElement);
    if (index >= 0) { event.preventDefault(); options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length].focus(); }
  });
  menu.addEventListener("click", event => {
    const choice = event.target.closest("[data-scenario]");
    if (!choice) return;
    const select = $("#scenario");
    select.value = choice.dataset.scenario;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    closeMenu();
    $("#runButton")?.click();
  });
  menu.addEventListener("keydown", event => {
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const options = [...menu.querySelectorAll(".scenario-choice")];
      options[event.key === "Home" ? 0 : options.length - 1].focus();
    }
  });

  $("#closeAnnouncement")?.addEventListener("click", () => {
    $(".announcement")?.classList.add("is-dismissed");
    setTimeout(() => $(".announcement")?.remove(), 220);
  });
  $("#backToScene")?.addEventListener("click", () => hero.scrollIntoView({ behavior: "smooth", block: "start" }));
  const topButton = $("#backToTop"), progress = $(".scroll-progress");
  function scrollUpdate() {
    const scrollY = window.scrollY;
    const maxScroll = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = `${maxScroll > 0 ? (scrollY / maxScroll) * 100 : 0}%`;
    if (scrollY > 500) topButton.hidden = false;
    else topButton.hidden = true;
    requestDraw();
  }
  addEventListener("scroll", scrollUpdate, { passive: true });
  topButton.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  document.addEventListener("visibilitychange", requestDraw);
  reducedMotion.addEventListener?.("change", requestDraw);
  $("#closeSettings")?.addEventListener("click", requestDraw);

  function syncMotionInputs() {
    const enabled = $("#motionEnabled"), speed = $("#motionSpeed"), density = $("#pixelDensity");
    if (!enabled || !speed || !density) return;
    enabled.checked = preferences.enabled;
    speed.value = preferences.speed;
    density.value = preferences.spacing;
    $("#motionSpeedValue").textContent = `${Number(preferences.speed).toFixed(1)}×`;
    $("#pixelDensityValue").textContent = preferences.spacing <= 6 ? "细密" : preferences.spacing >= 10 ? "舒展" : "标准";
  }
  function saveMotion() {
    localStorage.setItem(configKey, JSON.stringify(preferences));
    requestDraw();
  }
  $("#openSettings")?.addEventListener("click", syncMotionInputs);
  $("#motionEnabled")?.addEventListener("change", event => { preferences.enabled = event.target.checked; saveMotion(); });
  $("#motionSpeed")?.addEventListener("input", event => {
    preferences.speed = Number(event.target.value);
    $("#motionSpeedValue").textContent = `${preferences.speed.toFixed(1)}×`;
    saveMotion();
  });
  $("#pixelDensity")?.addEventListener("input", event => {
    preferences.spacing = Number(event.target.value);
    $("#pixelDensityValue").textContent = preferences.spacing <= 6 ? "细密" : preferences.spacing >= 10 ? "舒展" : "标准";
    saveMotion();
  });
})();

// Measured reference interaction: centered slide, adjacent previews and bounded arrows.
(() => {
  const $ = selector => document.querySelector(selector);
  const track = $('#monitorTrack'), viewport = $('#monitorViewport'), tabs = $('.monitor-tabs');
  if (!track || !viewport || !tabs) return;
  let selected = 'timeline';
  const visibleSlides = () => [...track.querySelectorAll('.monitor-slide')].filter(slide => !slide.hidden);
  function show(widget, focusTab = false) {
    const slides = visibleSlides();
    selected = slides.some(slide => slide.dataset.widget === widget) ? widget : slides[0]?.dataset.widget;
    const index = slides.findIndex(slide => slide.dataset.widget === selected);
    tabs.innerHTML = slides.map((slide, i) => `<button class="monitor-tab" id="tab-${slide.dataset.widget}" role="tab" aria-controls="${slide.id}" aria-selected="${i === index}" tabindex="${i === index ? 0 : -1}" data-slide="${slide.dataset.widget}"><span>[${String(i).padStart(2,'0')}]</span>${slide.dataset.label}</button>`).join('');
    [...track.children].forEach(slide => {
      const active = slide.dataset.widget === selected && !slide.hidden;
      slide.classList.toggle('is-active', active);
      slide.setAttribute('aria-labelledby', `tab-${slide.dataset.widget}`);
      slide.setAttribute('aria-hidden', String(!active));
      // Inactive preview controls must not enter the keyboard focus order.
      slide.querySelector('.monitor-surface').inert = !active;
    });
    $('#monitorPrev').disabled = index <= 0;
    $('#monitorNext').disabled = index < 0 || index >= slides.length - 1;
    $('.monitor-empty').hidden = slides.length > 0;
    if (slides[index]) {
      const slide = slides[index];
      track.style.transform = `translate3d(${(viewport.clientWidth - slide.offsetWidth) / 2 - slide.offsetLeft}px,0,0)`;
    }
    if (focusTab) $(`#tab-${selected}`)?.focus({preventScroll:true});
  }
  function move(delta, focus = false) {
    const slides = visibleSlides(), index = slides.findIndex(slide => slide.dataset.widget === selected);
    const next = slides[Math.max(0, Math.min(slides.length - 1, index + delta))];
    if (next) show(next.dataset.widget, focus);
  }
  tabs.addEventListener('click', event => {
    const tab = event.target.closest('[data-slide]');
    if (tab) show(tab.dataset.slide, true);
  });
  tabs.addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault(); move(event.key === 'ArrowRight' ? 1 : -1, true);
    } else if (['Home','End'].includes(event.key)) {
      event.preventDefault(); const slides = visibleSlides();
      show(slides[event.key === 'Home' ? 0 : slides.length - 1]?.dataset.widget, true);
    }
  });
  $('#monitorPrev').addEventListener('click', () => move(-1));
  $('#monitorNext').addEventListener('click', () => move(1));
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault(); move(event.key === 'ArrowRight' ? 1 : -1);
  });
  track.addEventListener('click', event => {
    const slide = event.target.closest('.monitor-slide');
    if (slide && !slide.classList.contains('is-active')) show(slide.dataset.widget);
  });
  let touchStart;
  viewport.addEventListener('touchstart', event => {
    if (event.target.closest('button, input, select, .events')) return;
    touchStart = {x:event.touches[0].clientX,y:event.touches[0].clientY};
  },{passive:true});
  viewport.addEventListener('touchend', event => {
    if (!touchStart) return;
    const dx = event.changedTouches[0].clientX - touchStart.x, dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.3) move(dx < 0 ? 1 : -1);
    touchStart = null;
  },{passive:true});
  new ResizeObserver(() => show(selected)).observe(viewport);
  document.addEventListener('teaflow:config', () => show(selected));
  document.addEventListener('teaflow:show-widget', event => show(event.detail));
  show(selected);
})();
