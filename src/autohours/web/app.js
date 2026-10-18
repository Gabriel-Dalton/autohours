"use strict";

// The view sends answers to Python. It never calculates billing or builds rules.
let token = "", heartbeat, disconnected = false, spriteReady = false;
const sessionKey = "autohours-token";
const page = document.querySelector("#page");
const footer = document.querySelector("#footer");
const toast = document.querySelector("#toast");
let state, step = "welcome", editing = false, generation = 0, awTimer;
let projects = [], items = [], remote = [], selected = 0, activitySearch = "", activityExpanded = false;
let projectQueue = Promise.resolve(), projectFailure = null, projectRevision = 0;
let primary, keyConnected = false, singleWorkspace = false;
let beforeStepBack = () => {};
// Explicit local references keep the sprite contract auditable without a build step.
const iconPaths = {
  "add": "/icons.svg#add",
  "arrow--left": "/icons.svg#arrow--left",
  "arrow--right": "/icons.svg#arrow--right",
  "arrow--up": "/icons.svg#arrow--up",
  "calendar": "/icons.svg#calendar",
  "checkmark": "/icons.svg#checkmark",
  "checkmark--filled": "/icons.svg#checkmark--filled",
  "checkmark--outline": "/icons.svg#checkmark--outline",
  "chevron--down": "/icons.svg#chevron--down",
  "circle-dash": "/icons.svg#circle-dash",
  "close": "/icons.svg#close",
  "document": "/icons.svg#document",
  "edit": "/icons.svg#edit",
  "error--filled": "/icons.svg#error--filled",
  "folder": "/icons.svg#folder",
  "in-progress": "/icons.svg#in-progress",
  "incomplete": "/icons.svg#incomplete",
  "information--filled": "/icons.svg#information--filled",
  "launch": "/icons.svg#launch",
  "overflow-menu--vertical": "/icons.svg#overflow-menu--vertical",
  "renew": "/icons.svg#renew",
  "search": "/icons.svg#search",
  "table": "/icons.svg#table",
  "time": "/icons.svg#time",
  "trash-can": "/icons.svg#trash-can",
  "warning--alt--filled": "/icons.svg#warning--alt--filled",
  "warning--filled": "/icons.svg#warning--filled"
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child.nodeType ? child : document.createTextNode(String(child)));
  if (tag === "summary") node.append(icon("chevron--down"));
  if (tag === "label" && attrs.class === "field") {
    const select = node.querySelector("select");
    if (select) { const wrapper = el("div", {class: "field-control"}); select.replaceWith(wrapper); wrapper.append(select); }
  }
  return node;
}
async function loadIcons() {
  try {
    const response = await fetch("/icons.svg", {cache: "no-store", credentials: "omit"});
    if (!response.ok) throw new Error("Sprite unavailable");
    const parsed = new DOMParser().parseFromString(await response.text(), "image/svg+xml");
    const root = parsed.documentElement;
    if (parsed.querySelector("parsererror") || root.localName !== "svg" || root.namespaceURI !== "http://www.w3.org/2000/svg") throw new Error("Invalid sprite");
    const sprite = document.importNode(root, true);
    sprite.setAttribute("class", "inline-sprite");
    sprite.setAttribute("aria-hidden", "true");
    sprite.setAttribute("focusable", "false");
    document.body.prepend(sprite);
    spriteReady = true;
  } catch {
    // Fall back to the bundled external sprite if embedding fails.
  }
  const update = root => root.querySelectorAll("use").forEach(use => {
    const href = use.getAttribute("href");
    if (href?.startsWith("#") || href?.startsWith("/icons.svg#")) {
      use.setAttribute("href", (spriteReady ? "" : "/icons.svg") + href.slice(href.indexOf("#")));
    }
  });
  update(document);
  document.querySelectorAll("template").forEach(template => update(template.content));
}
function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({class: `icon icon-${size}`, "aria-hidden": "true", focusable: "false"})) svg.setAttribute(key, value);
  const use = document.createElementNS(svg.namespaceURI, "use");
  if (!Object.hasOwn(iconPaths, name)) throw new Error("Unknown local icon: " + name);
  use.setAttribute("href", spriteReady ? "#" + name : iconPaths[name]);
  svg.append(use);
  return svg;
}
function buttonLabel(control, label, name) {
  control.replaceChildren(el("span", {class: "button-label"}, label));
  if (name) control.append(icon(name));
}
function button(label, action, className = "", name = null) {
  const b = el("button", {type: "button", class: className || "tertiary"});
  name ||= label === "Add" ? "add" : label === "Back" ? "arrow--left" : className === "primary" ? "arrow--right" : null;
  buttonLabel(b, label, name);
  if (action) b.addEventListener("click", () => work(b, action));
  return b;
}
function notification(kind, title, subtitle = "", dismiss = false) {
  const symbols = {success: "checkmark--filled", info: "information--filled", warning: "warning--filled", error: "error--filled"};
  const node = el("div", {class: `notification ${kind}`, role: kind === "error" ? "alert" : "status"},
    icon(symbols[kind], 20), el("div", {class: "notification-content"}, el("strong", {}, title), subtitle ? el("p", {}, subtitle) : null));
  if (dismiss) {
    const close = button("", () => { node.remove(); }, "icon-button", "close");
    close.setAttribute("aria-label", "Close notification");
    node.append(close);
  }
  return node;
}
async function api(path, data, method = data === undefined ? "GET" : "POST") {
  if (disconnected) throw new Error("autohours has closed");
  const response = await fetch("/api/" + path, {
    method, headers: {"X-Autohours-Token": token, ...(data === undefined ? {} : {"Content-Type": "application/json"})},
    body: data === undefined ? undefined : JSON.stringify(data), cache: "no-store", credentials: "omit"
  });
  const result = await response.json();
  if (disconnected) throw new Error("autohours has closed");
  if (!response.ok) throw Object.assign(new Error(result.error || "autohours could not process this request."), {field: result.field, nextStep: result.error ? "" : "Try the action again. If it still fails, close this window and open autohours again."});
  return result;
}
function notice(message, failure = false, nextStep = "") {
  if (disconnected) return;
  toast.replaceChildren(...(message ? [notification(failure ? "error" : "info", message, nextStep, true)] : []));
  toast.hidden = !message;
  if (failure && message) toast.scrollIntoView({block: "nearest"});
}
function clearErrors() {
  page.querySelectorAll("[aria-invalid]").forEach(clearFieldError);
  page.querySelectorAll(".error:not(.notification)").forEach(n => n.remove());
  notice("");
}
function clearFieldError(field) {
  if (!field) return;
  document.getElementById("error-" + field.id)?.remove();
  field.closest(".field-control")?.querySelector(".field-error-icon")?.remove();
  field.removeAttribute("aria-invalid");
  const described = (field.getAttribute("aria-describedby") || "").split(" ").filter(id => id && id !== "error-" + field.id);
  if (described.length) field.setAttribute("aria-describedby", described.join(" ")); else field.removeAttribute("aria-describedby");
}
for (const event of ["input", "change"]) page.addEventListener(event, e => {
  clearFieldError(e.target);
  clearFieldError(e.target.closest("fieldset"));
});
function loadingRows(message) {
  return el("div", {class: "loading", role: "status", "aria-live": "polite"},
    el("p", {}, message), ...[1, 2, 3].map(() => el("div", {class: "skeleton skeleton-row", "aria-hidden": "true"})));
}
function duration(minutes) {
  const total = Math.round(minutes);
  return total >= 60 ? `${Math.floor(total / 60)} h${total % 60 ? ` ${total % 60} min` : ""}` : `${total} min`;
}
// Match Carbon's productive cubic-bezier(0.2, 0, 0.38, 0.9).
function productiveEase(progress) {
  if (progress <= 0) return 0;
  if (progress >= 1) return 1;
  let low = 0, high = 1;
  for (let i = 0; i < 18; i++) {
    const t = (low + high) / 2;
    const x = 3 * (1 - t) ** 2 * t * 0.2 + 3 * (1 - t) * t ** 2 * 0.38 + t ** 3;
    if (x < progress) low = t; else high = t;
  }
  const t = (low + high) / 2;
  return 3 * (1 - t) * t ** 2 * 0.9 + t ** 3;
}
const valueAnimations = new WeakMap();
function animateValue(node, target, paint, initial = 0) {
  const previous = valueAnimations.get(node);
  if (previous) cancelAnimationFrame(previous.frame);
  const from = previous?.value ?? initial;
  const animation = {value: from, frame: 0};
  valueAnimations.set(node, animation);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const start = performance.now();
  const tick = now => {
    if (!node.isConnected) { valueAnimations.delete(node); return; }
    const progress = reduced.matches ? 1 : Math.min(1, (now - start) / 240);
    animation.value = from + (target - from) * productiveEase(progress);
    paint(animation.value);
    if (progress < 1) animation.frame = requestAnimationFrame(tick);
  };
  tick(start);
}
function showError(error) {
  if (disconnected) return;
  if (step === "projects" && /^project-\d+$/.test(error.field || "")) {
    selected = Number(error.field.slice(8)); renderProject();
  }
  const field = error.field && document.getElementById(error.field);
  if (field) {
    for (let parent = field.closest("details"); parent; parent = parent.parentElement?.closest("details")) parent.open = true;
    const id = "error-" + error.field;
    document.getElementById(id)?.remove();
    const message = el("p", {id, class: "error", role: "alert"}, error.message);
    const wrapper = field.closest(".field-control");
    if (wrapper) {
      wrapper.querySelector(".field-error-icon")?.remove();
      const symbol = icon("error--filled"); symbol.classList.add("field-error-icon"); wrapper.append(symbol);
      wrapper.after(message);
    } else field.after(message);
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("aria-describedby", [...new Set([...(field.getAttribute("aria-describedby") || "").split(" ").filter(Boolean), id])].join(" "));
    const target = /^project-\d+$/.test(error.field) ? document.querySelector("#activity-list input:not(:disabled)") || field :
      field.matches("input, select, button") ? field : field.querySelector("input, button") || field;
    target.focus();
  } else notice(error instanceof TypeError ? "autohours could not be reached." : error.message || "autohours could not be reached.", true,
    error instanceof TypeError || !error.message ? "Close this window and open autohours again to carry on." : error.nextStep || "");
}
async function work(control, action) {
  if (control?.disabled) return;
  clearErrors();
  if (control) { control.disabled = true; control.classList.add("busy"); control.setAttribute("aria-busy", "true"); }
  try { await action(); }
  catch (error) { showError(error); }
  finally { if (control) { control.disabled = false; control.classList.remove("busy"); control.removeAttribute("aria-busy"); } }
}
function field(label, id, value = "", type = "text", attrs = {}) {
  const input = el("input", {id, type, ...attrs});
  input.value = value;
  const control = el("div", {class: "field-control"}, input);
  if (type === "search") {
    control.classList.add("search-control"); control.prepend(icon("search"));
    const clear = button("", () => { input.value = ""; input.dispatchEvent(new Event("input", {bubbles: true})); input.focus(); }, "icon-button", "close");
    clear.setAttribute("aria-label", "Clear " + label.toLowerCase());
    clear.hidden = !input.value;
    input.addEventListener("input", () => { clear.hidden = !input.value; });
    control.append(clear);
  }
  return el("div", {class: "field"}, el("label", {for: id}, label), control);
}
function toggle(label, id, checked = false, change = () => {}) {
  const input = el("input", {id, type: "checkbox", role: "switch", onchange: () => change(input.checked)});
  input.checked = checked;
  const drawing = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  drawing.setAttribute("viewBox", "0 0 48 24"); drawing.setAttribute("focusable", "false");
  for (const [tag, attrs] of [["rect", {width: 48, height: 24, rx: 12}], ["circle", {cx: 12, cy: 12, r: 9}]]) {
    const shape = document.createElementNS(drawing.namespaceURI, tag);
    for (const [key, val] of Object.entries(attrs)) shape.setAttribute(key, val);
    drawing.append(shape);
  }
  return el("label", {class: "toggle", for: id}, label ? el("span", {class: "toggle-label"}, label) : null,
    el("span", {class: "toggle-control"}, input, el("span", {class: "toggle-track", "aria-hidden": "true"}, drawing),
      el("span", {class: "toggle-on", "aria-hidden": "true"}, "On"), el("span", {class: "toggle-off", "aria-hidden": "true"}, "Off")));
}
function choices(title, id, options, value, change = () => {}, segmented = false, help = "") {
  const group = el("fieldset", {id, class: segmented ? "segments" : "choices", tabindex: "-1"}, el("legend", {}, title));
  if (help) {
    group.append(el("small", {id: id + "-help", class: "question-help"}, help));
    group.setAttribute("aria-describedby", id + "-help");
  }
  options.forEach(([key, label, detail, symbol]) => {
    const input = el("input", {type: "radio", name: id, value: key, onchange: () => change(key)});
    input.checked = String(value) === String(key);
    group.append(el("label", {class: segmented ? "segment" : "choice"}, input,
      !segmented && symbol ? icon(symbol, 20) : null,
      segmented ? label : el("span", {}, el("strong", {}, label), el("small", {}, detail || "")),
      !segmented ? el("span", {class: "tick", "aria-hidden": "true"}, icon("checkmark--filled")) : null));
  });
  return group;
}
function value(id) { return document.getElementById(id)?.value || ""; }
function radio(id) { return document.querySelector(`#${id} input:checked`)?.value || ""; }
function card(title, ...children) { return el("section", {class: "card"}, title ? el("h2", {}, title) : null, children); }
function link(label, url) { return el("a", {class: "button-link", href: url, target: "_blank", rel: "noreferrer noopener"}, label, icon("launch")); }
function foot(label, action, back) {
  footer.replaceChildren();
  if (back) footer.append(button("Back", back, "text-button"));
  primary = button(label, action, "primary");
  footer.append(primary);
}
function screen(name, title, subtitle) {
  step = name; generation++; clearTimeout(awTimer); clearErrors();
  beforeStepBack = () => {};
  const shell = document.querySelector("#app-shell");
  shell.dataset.screen = name;
  shell.dataset.layout = ["projects", "finish", "home", "welcome"].includes(name) ? "wide" : "readable";
  shell.classList.toggle("short-screen", name === "welcome");
  document.querySelector(".welcome-preview")?.remove();
  page.replaceChildren(el("h1", {tabindex: "-1"}, title), el("p", {class: "subtitle"}, subtitle));
  page.classList.remove("page-enter");
  // Commit the reset before restarting the entrance, including rapid Back clicks.
  void page.offsetWidth;
  page.classList.add("page-enter");
  footer.replaceChildren(); primary = null;
  const steps = ["welcome", "activitywatch", "destination", ...(state?.destination.type === "clockify" ? ["connect", ...(!singleWorkspace ? ["workspace"] : [])] : []), "projects", "billing", "finish"];
  const index = steps.indexOf(name);
  const labels = {welcome: "Welcome", activitywatch: "ActivityWatch", destination: "Destination", connect: "Connect", workspace: "Workspace", projects: "Projects", billing: "Billing", finish: "Finish"};
  const routes = {welcome, activitywatch: activityWatch, destination, connect, workspace, projects: projectsScreen, billing, finish};
  document.querySelector("#setup-progress").hidden = name === "home" || editing;
  document.querySelector("#progress-label").textContent = `Step ${index + 1} of ${steps.length}`;
  const progress = document.querySelector("#step-progress");
  animateValue(progress, (index + 1) / steps.length, n => { progress.value = n; });
  document.querySelector("#progress").replaceChildren(...steps.map((s, i) => {
    const children = [icon(i < index ? "checkmark--outline" : i === index ? "incomplete" : "circle-dash"), el("span", {}, labels[s])];
    const control = i < index ? button("", async () => {
      await projectQueue.catch(() => {});
      const restore = beforeStepBack();
      await routes[s]();
      restore?.();
    }, "progress-back") : null;
    if (control) { control.replaceChildren(...children); control.setAttribute("aria-label", `Back to ${labels[s]}`); }
    return el("li", {
      class: i < index ? "complete" : i === index ? "current" : "future", "aria-current": i === index ? "step" : null,
      "aria-label": `${labels[s]}: ${i < index ? "complete" : i === index ? "current" : "not started"}`
    }, ...(control ? [control] : children));
  }));
  page.querySelector("h1").focus({preventScroll: true});
  window.scrollTo(0, 0);
}
async function refresh() { state = await api("state"); }
async function cancelEdit() { await projectQueue.catch(() => {}); await api("reset", {}); await home(); }

function welcome() {
  screen("welcome", "Set up autohours", "autohours turns what you work on into timesheets. It leaves out time you were away.");
  page.append(card(null, el("ul", {class: "benefits"},
    el("li", {}, icon("checkmark"), "Tracks what you work on"), el("li", {}, icon("checkmark"), "Leaves out time you were away"),
    el("li", {}, icon("checkmark"), "Writes to Clockify or a spreadsheet"))));
  page.append(el("p", {}, "Window titles never leave your computer."));
  let friendly;
  try { friendly = new Intl.DateTimeFormat(undefined, {timeZone: state.timezone, timeZoneName: "longGeneric"}).formatToParts(new Date()).find(p => p.type === "timeZoneName").value; }
  catch { friendly = state.timezone; }
  const zoneBox = el("div", {hidden: true});
  const search = field("Search for a city or time zone", "zone-search", "", "search");
  const select = el("select", {id: "timezone"});
  const filterZones = () => {
    const query = value("zone-search").toLowerCase().split(" ").join("_");
    select.replaceChildren(...state.timezones.filter(z => z.toLowerCase().includes(query)).map(z => el("option", {value: z}, z.split("_").join(" "))));
    if ([...select.options].some(o => o.value === state.timezone)) select.value = state.timezone;
  };
  search.querySelector("input").addEventListener("input", filterZones); filterZones();
  zoneBox.append(search, el("label", {class: "field", for: "timezone"}, el("span", {}, "Time zone"), select));
  page.append(el("div", {class: "row wrap"}, el("small", {}, `Time zone: ${friendly} (${state.timezone})`),
    button("Change", () => { zoneBox.hidden = false; search.querySelector("input").focus(); }, "text-button")), zoneBox);
  foot("Get started", async () => { state.timezone = select.value; await api("timezone", {timezone: state.timezone}); activityWatch(); });
  page.parentElement.append(document.querySelector("#welcome-preview").content.cloneNode(true));
}

function activityWatch() {
  screen("activitywatch", "Connect ActivityWatch", "ActivityWatch records which apps you use and when you step away.");
  const status = card(null, el("p", {role: "status", "aria-live": "polite"}, "Checking ActivityWatch..."));
  const download = el("p", {}, link("Download ActivityWatch", "https://activitywatch.net/downloads/")); download.hidden = true;
  const hostBox = el("div", {hidden: true});
  let hostname = state.activitywatch.hostname || "";
  const web = toggle("Also use websites from the ActivityWatch browser extension", "use_web", state.activitywatch.use_web || false, () => check());
  page.append(status, download, hostBox, web);
  let running = false, checking = false, recheck = false;
  const current = generation;
  async function check() {
    if (generation !== current) return;
    if (checking) { recheck = true; return; }
    checking = true;
    const checkedHostname = hostname, useWeb = web.querySelector("input").checked;
    try {
      const result = await api("activitywatch/check", {hostname: checkedHostname, use_web: useWeb});
      if (generation !== current) return;
      if (hostname !== checkedHostname || web.querySelector("input").checked !== useWeb) { recheck = true; return; }
      running = result.running;
      status.replaceChildren(notification(running ? "success" : "info", running ? "ActivityWatch is running" : "Waiting for ActivityWatch",
        running ? "Recording apps and time away on this computer." : result.message));
      if (!running) status.append(el("small", {class: "busy"}, "Checking..."));
      download.hidden = running || result.hosts.length > 0;
      hostname = result.hostname || hostname;
      const hosts = result.hosts.map(h => [h, h, "Recording apps and time away on this computer.", "document"]);
      // Keep radio nodes (and keyboard focus) stable during polling and selection.
      if (JSON.stringify(result.hosts) !== hostBox.dataset.hosts) {
        hostBox.dataset.hosts = JSON.stringify(result.hosts);
        hostBox.replaceChildren(choices("Computer to use", "hostname", hosts, hostname, v => { hostname = v; running = false; check(); }));
      }
      hostBox.querySelectorAll("input").forEach(input => { input.checked = input.value === hostname; });
      hostBox.hidden = result.hosts.length <= 1;
      if (running) state.activitywatch = {hostname: result.hostname, use_web: web.querySelector("input").checked};
    } catch (error) { if (generation === current) showError(error); }
    finally {
      checking = false;
      if (generation === current) {
        if (recheck) { recheck = false; check(); }
        else if (!running) awTimer = setTimeout(check, 3000);
      }
    }
  }
  foot("Continue", async () => {
    await check();
    if (!running) throw new Error("Open ActivityWatch and let it record your apps and time away before continuing.");
    destination();
  }, welcome);
  check();
}

function destination() {
  screen("destination", "Where should your timesheets go?", "Choose the place you already use, or start with a simple file.");
  const path = field("Spreadsheet file", "path", state.destination.path || "");
  const picked = state.destination.type;
  path.hidden = picked !== "csv";
  page.append(choices("Destination", "destination", [
    ["clockify", "Clockify", "Time tracking app, rates and invoices", "time"],
    ["csv", "Spreadsheet", "Opens in Excel, Numbers or Google Sheets", "table"]
  ], picked, v => { path.hidden = v !== "csv"; }), path);
  foot("Continue", async () => {
    const type = radio("destination");
    await api("destination", {type, path: value("path")});
    state.destination = {type, path: value("path")};
    if (type === "clockify") connect(); else await projectsScreen();
  }, activityWatch);
}

function connect() {
  screen("connect", "Connect Clockify", "Your key stays private on this computer.");
  const status = el("div", {role: "status", "aria-live": "polite"});
  const instructions = el("div", {}, el("ol", {},
    el("li", {}, "Open your Clockify settings."), el("li", {}, "Find API and choose Generate."), el("li", {}, "Copy the key and paste it below.")),
    link("Open Clockify settings", "https://app.clockify.me/user/preferences#advanced"),
    field("Paste your API key", "key", "", "password", {autocomplete: "off", spellcheck: "false"}));
  const saved = card("Use your saved key", el("p", {}, "A key is saved on this computer. We will check it before connecting."));
  instructions.hidden = state.saved_key;
  saved.hidden = !state.saved_key;
  let useSaved = state.saved_key;
  let savedConnection = null;
  async function verify() {
    const key = useSaved ? "" : value("key");
    document.querySelector("#key").value = "";
    const result = useSaved && savedConnection ? savedConnection : await api("clockify/key", {key});
    keyConnected = true; singleWorkspace = result.single_workspace;
    state.currency = result.currency; state.workspace_name = result.workspace_name;
    status.replaceChildren(notification("success", "Clockify connected", `Connected as ${result.name}`));
    instructions.hidden = saved.hidden = true;
    buttonLabel(primary, "Continue", "arrow--right");
  }
  const savedButton = button("Use saved key", verify);
  saved.append(savedButton, button("Use a different key", () => {
    useSaved = false; instructions.hidden = false; saved.hidden = true; document.querySelector("#key").focus();
  }, "text-button"));
  page.append(saved, instructions, status);
  keyConnected = false;
  foot("Connect", async () => {
    if (!keyConnected) await verify();
    else if (singleWorkspace) await projectsScreen();
    else await workspace();
  }, destination);
  if (useSaved) {
    const current = generation;
    savedButton.disabled = true; savedButton.classList.add("busy"); primary.disabled = true;
    api("clockify/key", {key: ""}).then(result => {
      if (generation !== current) return;
      savedConnection = result;
      saved.querySelector("p").textContent = "Your saved key is valid. Use it to connect as " + result.name + ".";
    }).catch(() => {
      if (generation === current) saved.querySelector("p").textContent = "We could not check your saved key. Try it again, or use a different key.";
    }).finally(() => {
      savedButton.disabled = false; savedButton.classList.remove("busy");
      if (generation === current && primary) primary.disabled = false;
    });
  }
}

async function workspace() {
  screen("workspace", "Choose your workspace", "Use the workspace where you keep this work.");
  const current = generation;
  const loading = el("div", {class: "skeleton"}); page.append(loading);
  let result;
  try { result = await api("clockify/workspaces"); }
  catch (error) {
    if (generation !== current) return;
    loading.remove(); showError(error);
    foot("Try again", workspace, connect); return;
  }
  if (current !== generation) return;
  loading.replaceWith(choices("Workspace", "workspace", result.workspaces.map(w => [w.id, w.name, "Your Clockify projects", "time"]), state.destination.workspace || ""));
  foot("Continue", async () => {
    const result = await api("clockify/workspace", {workspace: radio("workspace")});
    state.currency = result.currency; state.workspace_name = result.workspace_name;
    await projectsScreen();
  }, connect);
}

function updateCoverage(percent) {
  const bar = document.querySelector("#coverage");
  if (bar) {
    bar.value = percent;
    const figure = document.querySelector("#coverage-percent");
    animateValue(figure, percent, n => { figure.textContent = `${Math.round(n)}%`; });
    document.querySelector("#coverage-label").textContent = `${Math.round(percent)}% of your last 7 days`;
  }
}
function saveProjects(validate = false) {
  const revision = ++projectRevision;
  projectQueue = projectQueue.catch(() => {}).then(async () => {
    const submitted = [...projects];
    const result = await api("projects", {projects: submitted, validate});
    submitted.forEach((p, i) => { p.id = result.projects[i].id; });
    projectFailure = null;
    if (revision === projectRevision) updateCoverage(result.coverage);
  }).catch(error => { projectFailure = error; showError(error); if (validate) throw error; });
  return projectQueue;
}
function activityPage(allItems, search, expanded) {
  const matches = allItems.filter(item => item.name.toLowerCase().includes(search.toLowerCase()));
  return {visible: expanded ? matches : matches.slice(0, 12), total: matches.length};
}
function nightlyKind(summary) {
  if (summary.startsWith("Not run yet.")) return "info";
  return /: (wrote \d+ entries, .+|completed)\.$/.test(summary) ? "success" : "error";
}
function activityRows() {
  const list = document.querySelector("#activity-list");
  if (!list) return;
  const focused = list.contains(document.activeElement) ? document.activeElement.id : null;
  list.replaceChildren();
  const project = projects[selected];
  const {visible, total} = activityPage(items, activitySearch, activityExpanded);
  for (const item of visible) {
    const input = el("input", {id: `activity-${item.id}`, type: "checkbox", "aria-label": `Assign ${item.name} to ${project?.name || "a project"}`});
    input.checked = !!project?.items.includes(item.id); input.disabled = !project;
    const badges = el("span", {class: "assigned-projects"});
    const updateBadges = () => badges.replaceChildren(...projects.filter(p => p.items.includes(item.id)).map(p => el("span", {class: "assigned"}, p.name)));
    updateBadges();
    const label = el("label", {class: "activity-row"}, el("span", {class: "checkbox"}, input, icon("checkmark")),
      el("span", {class: "name"}, item.name, el("small", {}, item.kind)), badges,
      el("span", {class: "hours"}, duration(item.hours * 60)));
    input.addEventListener("change", async () => {
      const checked = input.checked;
      projects.forEach(p => { p.items = p.items.filter(id => id !== item.id); });
      if (checked) project.items.push(item.id);
      clearFieldError(document.getElementById(`project-${selected}`));
      // Keep this native checkbox focusable while the save is in flight.
      await saveProjects();
      // Keep the clicked input in place so the first click and focus never scroll.
      updateBadges();
    });
    list.append(label);
  }
  if (!list.children.length) list.append(el("p", {class: "muted"}, "No activity matches your search."));
  if (total > visible.length) list.append(button(`Show all ${total} items`, () => {
    activityExpanded = true; activityRows();
    document.getElementById(`activity-${activityPage(items, activitySearch, true).visible[12].id}`)?.focus({preventScroll: true});
  }, "text-button"));
  if (focused) document.getElementById(focused)?.focus({preventScroll: true});
}
function closeProjectMenu(focus = false) {
  const menu = document.querySelector("#project-menu");
  if (menu) menu.hidden = true;
  const more = document.querySelector("#project-more");
  more?.setAttribute("aria-expanded", "false");
  if (focus) more?.focus();
}
function renderTabs() {
  const tabs = document.querySelector("#project-tabs"); if (!tabs) return;
  const list = el("div", {class: "tab-list", role: "tablist", "aria-label": "Choose a project"});
  tabs.replaceChildren(list);
  projects.forEach((project, i) => {
    const activate = () => { selected = i; renderProject(); document.getElementById(`project-tab-${i}`)?.focus({preventScroll: true}); };
    const tab = el("button", {type: "button", id: `project-tab-${i}`, class: "project-tab", role: "tab",
      "aria-selected": String(i === selected), "aria-controls": "project-panel", tabindex: i === selected ? "0" : "-1", title: project.name, onclick: activate}, project.name);
    tab.addEventListener("keydown", e => {
      const next = e.key === "ArrowRight" ? (i + 1) % projects.length : e.key === "ArrowLeft" ? (i + projects.length - 1) % projects.length : e.key === "Home" ? 0 : e.key === "End" ? projects.length - 1 : null;
      if (next !== null) { e.preventDefault(); selected = next; renderProject(); document.getElementById(`project-tab-${next}`).focus(); }
    });
    list.append(tab);
  });
  document.getElementById(`project-tab-${selected}`)?.scrollIntoView({block: "nearest", inline: "nearest"});
  if (!projects.length) return;
  const project = projects[selected];
  const more = el("button", {type: "button", id: "project-more", class: "icon-button", "aria-label": `More options for ${project.name}`,
    "aria-controls": "project-menu", "aria-haspopup": "menu", "aria-expanded": "false"}, icon("overflow-menu--vertical"));
  const menu = el("div", {id: "project-menu", class: "project-actions", role: "menu", "aria-label": "Project actions", hidden: true});
  const edit = button("Edit details", () => { closeProjectMenu(); document.querySelector("#project-edit").hidden = false; document.querySelector("#rename").focus(); }, "menu-item", "edit");
  const move = button("Move up", async () => {
    closeProjectMenu();
    if (selected > 0) { [projects[selected - 1], projects[selected]] = [projects[selected], projects[selected - 1]]; selected--; await saveProjects(); renderProject(); document.querySelector("#project-more").focus(); }
  }, "menu-item", "arrow--up");
  move.disabled = selected === 0;
  const remove = button("Remove project", async () => {
    closeProjectMenu(); projects.splice(selected, 1); selected = Math.max(0, selected - 1); await saveProjects(); renderProject();
    (document.querySelector("#project-more") || document.querySelector("#project-name")).focus();
  }, "menu-item danger", "trash-can");
  for (const item of [edit, move, remove]) { item.setAttribute("role", "menuitem"); item.tabIndex = -1; menu.append(item); }
  const open = () => { menu.hidden = false; more.setAttribute("aria-expanded", "true"); edit.focus(); };
  more.addEventListener("click", () => { if (menu.hidden) open(); else closeProjectMenu(true); });
  more.addEventListener("keydown", e => { if (e.key === "ArrowDown") { e.preventDefault(); open(); } });
  menu.addEventListener("keydown", e => {
    const controls = [...menu.querySelectorAll("button:not(:disabled)")];
    const index = controls.indexOf(document.activeElement);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault(); controls[e.key === "Home" ? 0 : e.key === "End" ? controls.length - 1 : (index + (e.key === "ArrowDown" ? 1 : controls.length - 1)) % controls.length].focus();
    } else if (e.key === "Escape") { e.preventDefault(); closeProjectMenu(true); }
    else if (e.key === "Tab") closeProjectMenu(true);
  });
  tabs.append(more, menu);
}
function renderProject() {
  renderTabs(); activityRows();
  const panel = document.querySelector("#project-panel");
  if (projects.length) { panel?.setAttribute("aria-labelledby", `project-tab-${selected}`); panel?.removeAttribute("aria-label"); }
  else { panel?.removeAttribute("aria-labelledby"); panel?.setAttribute("aria-label", "Project activity"); }
  const details = document.querySelector("#project-details"); details.replaceChildren();
  const project = projects[selected]; if (!project) return;
  details.id = "project-details";
  const validation = el("div", {id: `project-${selected}`, tabindex: "-1"});
  const menu = el("div", {id: "project-edit", class: "project-edit", hidden: true});
  menu.append(field("Project name", "rename", project.name), field("Timesheet description", "description", project.description));
  menu.append(button("Save details", async () => {
    project.name = value("rename"); project.description = value("description"); await saveProjects();
    if (!projectFailure) { renderProject(); document.querySelector("#project-more").focus(); }
  }), button("Cancel", () => { menu.hidden = true; document.querySelector("#project-more").focus(); }, "text-button"));
  validation.append(menu);
  if (state.destination.type === "clockify") {
    const select = el("select", {id: "project-target"}, el("option", {value: ""}, "Create it in Clockify"), ...remote.map(p => el("option", {value: p.id}, p.name)));
    select.value = project.target || "";
    select.addEventListener("change", async () => { project.target = select.value; project.create = !select.value; await saveProjects(); });
    validation.append(el("label", {class: "field", for: "project-target"}, el("span", {}, "Use an existing Clockify project"), select),
      el("small", {}, "New projects are created when you save and continue. They will be visible to workspace members."));
  }
  details.append(validation);
}

async function projectsScreen() {
  screen("projects", "What do you work on?", "Add a client or project, then pick the activity that belongs to it.");
  if (state.workspace_name) page.append(el("small", {class: "workspace-note"}, `Using ${state.workspace_name} in Clockify.`));
  const current = generation;
  const back = editing ? cancelEdit : state.destination.type === "clockify" ? (singleWorkspace ? connect : workspace) : destination;
  let ready = false;
  const add = async () => {
    await activityReady;
    if (!ready || generation !== current) return;
    const name = value("project-name").trim();
    if (!name) throw Object.assign(new Error("Give your client or project a name."), {field: "project-name"});
    const match = remote.find(p => p.name.toLowerCase() === name.toLowerCase());
    projects.push({id: null, name, description: name, items: [], agreement: {}, target: match?.id || "", create: !match});
    selected = projects.length - 1;
    await saveProjects();
    if (projectFailure) { projects.pop(); selected = Math.max(0, selected - 1); return; }
    document.querySelector("#project-name").value = ""; renderProject();
    clearFieldError(document.querySelector("#project-name"));
    document.querySelector("#project-name").focus({preventScroll: true});
  };
  const addButton = button("Add", add);
  const addField = field("Add a client or project", "project-name", "", "text", {placeholder: "For example, Acme Corp"});
  addField.querySelector("input").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); addButton.click(); } });
  const panel = el("div", {id: "project-panel", role: "tabpanel", tabindex: "0"}, el("div", {id: "project-details"}));
  page.append(el("div", {class: "row input-row"}, addField, addButton), el("div", {id: "project-tabs", class: "project-tabs"}), panel);
  const loading = loadingRows("Reading your last 7 days of activity..."); panel.append(loading);
  foot("Continue", async () => { await activityReady; if (ready) { await saveProjects(true); billing(); } }, back);
  const activityReady = api("activity").then(result => {
    if (generation !== current) return;
    loading.remove(); items = result.items; projects = result.projects; remote = result.remote;
    state.currency = result.currency; state.workspace_name = result.workspace_name;
    selected = Math.min(selected, Math.max(0, projects.length - 1));
    const search = field("Search your activity", "activity-search", activitySearch, "search");
    search.querySelector("input").addEventListener("input", e => { activitySearch = e.target.value; activityExpanded = false; activityRows(); });
    panel.append(el("h2", {}, "Your activity from the last 7 days"), search,
      el("small", {}, "Picking an app includes all time in that app. Pick a window title for work in a shared app."),
      el("div", {id: "activity-list", class: "activity-list"}),
      el("div", {class: "coverage"}, el("div", {class: "coverage-heading"}, el("span", {}, "Assigned"), el("span", {id: "coverage-percent"})),
        el("progress", {id: "coverage", max: "100", "aria-label": "Activity assigned"}), el("small", {id: "coverage-label", "aria-live": "polite"})));
    if (items.some(item => item.matches.length > 1)) page.append(el("small", {}, "When activity matches more than one project, the project higher in your list gets the time."));
    renderProject(); updateCoverage(result.coverage);
    ready = true;
  }).catch(error => {
    if (generation !== current) return;
    loading.remove(); showError(error);
    foot("Try again", projectsScreen, back);
  });
  await activityReady;
}

function billing() {
  screen("billing", projects.length === 1 ? `How do you bill ${projects[0].name}?` : "How do you bill your clients?", "Use the agreement you have with each client. You can leave the hourly rate empty.");
  projects.forEach((project, i) => {
    const a = project.agreement;
    const group = card(projects.length > 1 ? project.name : null);
    group.classList.add("billing-group");
    const rates = el("div", {class: "rate-row"}, field("Hourly rate", `rate-${i}`, a.rate ?? "", "number", {min: "0", step: "any"}),
      el("span", {class: "muted"}, "per hour in"), field("Currency", `currency-${i}`, a.currency || state.currency || "", "text", {maxlength: "3", placeholder: "For example, CAD"}));
    rates.hidden = a.billing !== "hourly";
    const billingQuestion = choices("How do you bill this client?", `billing-${i}`, [
      ["hourly", "By the hour", "Track time and an optional hourly amount", "time"],
      ["flat", "Flat monthly fee", "Track time covered by a fixed fee", "calendar"],
      ["retainer", "Retainer", "Track time within your agreement", "in-progress"],
      ["none", "Not billed", "Keep a record without billing", "close"]
    ], a.billing || "", v => { a.billing = v; rates.hidden = v !== "hourly"; }, false,
    "Your rate can be added later. No rate is assumed.");
    billingQuestion.append(rates);
    group.append(billingQuestion);
    const breaks = String(a.count_breaks_up_to_minutes ?? 0);
    const custom = field("Custom break limit in minutes", `count_breaks_up_to_minutes-${i}`, breaks, "number", {min: "0", max: "1440", step: "1"});
    custom.hidden = ["0", "5", "10", "15"].includes(breaks);
    const breaksQuestion = choices("Do short breaks count?", `breaks-${i}`, [["0", "No"], ["5", "5 min"], ["10", "10 min"], ["15", "15 min"], ["custom", "Custom"]], custom.hidden ? breaks : "custom", v => {
      custom.hidden = v !== "custom";
      if (v !== "custom") custom.querySelector("input").value = v;
    }, true, "The limit includes exactly that many minutes. Longer breaks stay out.");
    breaksQuestion.append(custom);
    const calls = toggle("", `calls-${i}`, a.count_calls_when_away || false);
    calls.querySelector("input").setAttribute("aria-labelledby", `calls-question-${i}`);
    calls.querySelector("input").setAttribute("aria-describedby", `calls-help-${i}`);
    group.append(breaksQuestion, el("fieldset", {},
      el("legend", {id: `calls-question-${i}`}, "Count calls when you step away from the keyboard?"),
      el("p", {id: `calls-help-${i}`, class: "question-help"}, "A Zoom call with no typing can still count when it matches this project."), calls));
    const quantum = String(a.round_to_minutes ?? 0);
    const roundingOptions = [["0", "No rounding"], ["6", "6 min"], ["15", "15 min"], ["30", "30 min"]];
    if (!roundingOptions.some(o => o[0] === quantum)) roundingOptions.push([quantum, `${quantum} min (saved)`]);
    const roundUp = toggle("Always round up", `up-${i}`, a.rounding === "up");
    roundUp.hidden = quantum === "0";
    const roundingQuestion = choices("Round each entry", `round_to_minutes-${i}`, roundingOptions, quantum, v => { roundUp.hidden = v === "0"; }, true,
      "Use the closest interval, or choose to always round up.");
    roundingQuestion.append(roundUp);
    group.append(roundingQuestion,
      el("details", {}, el("summary", {}, "More options"), field("Monthly cap in hours", `monthly_cap_hours-${i}`, a.monthly_cap_hours ?? "", "number", {min: "0", step: "any"})));
    page.append(group);
  });
  function collect() {
    return projects.map((p, i) => ({billing: radio(`billing-${i}`), rate: value(`rate-${i}`), currency: value(`currency-${i}`),
      count_breaks_up_to_minutes: value(`count_breaks_up_to_minutes-${i}`), count_calls_when_away: document.getElementById(`calls-${i}`).checked,
      round_to_minutes: radio(`round_to_minutes-${i}`), rounding: document.getElementById(`up-${i}`).checked ? "up" : "nearest", monthly_cap_hours: value(`monthly_cap_hours-${i}`)}));
  }
  beforeStepBack = () => {
    const agreements = collect(); projects.forEach((p, i) => { p.agreement = agreements[i]; });
    const drafts = projects.map(p => [p.name, p.agreement]);
    return () => { for (const p of projects) p.agreement = drafts.find(([name]) => name === p.name)?.[1] || p.agreement; };
  };
  foot("Save and continue", async () => {
    const agreements = collect();
    await api("agreements", {agreements});
    await api("save", {});
    projects.forEach((p, i) => { p.agreement = agreements[i]; });
    await refresh();
    if (editing) { editing = false; await home(); } else await finish();
  }, async () => {
    // Keep unfinished billing answers in this page until the user returns.
    const restore = beforeStepBack();
    await projectsScreen();
    restore();
  });
}

function confirmation(parent, title, text, approveLabel, action, cancel = () => {}, details = "") {
  parent.querySelector(".confirmation")?.remove();
  const panel = el("section", {class: "confirmation notification warning", tabindex: "-1", "aria-label": title}, icon("warning--filled", 20));
  const content = el("div", {class: "notification-content"}, el("h3", {}, title));
  if (text) content.append(el("pre", {}, text));
  if (details) content.append(el("details", {}, el("summary", {}, "Show the full preview"), el("pre", {}, details)));
  const trigger = document.activeElement;
  const restoreFocus = () => { if (trigger?.isConnected) trigger.focus(); };
  content.append(el("div", {class: "row wrap"}, button("Not now", () => { panel.remove(); cancel(); restoreFocus(); }, "secondary"),
    button(approveLabel, async () => { await action(); panel.remove(); restoreFocus(); }, "primary")));
  panel.append(content);
  parent.append(panel); panel.focus();
  return panel;
}

function reviewCard(initialDay, fallback = false) {
  let day = initialDay, reviewed = null, requestNumber = 0;
  const section = card("Review a day");
  const date = field("Date", "day", day, "date", {max: state.today});
  const results = el("div", {});
  const writeButton = button("Write this day", async () => {
    if (!reviewed || value("day") !== day) throw Object.assign(new Error("Review this day before writing it."), {field: "day"});
    const preview = await api("write/preview", {day});
    const target = state.destination.type === "clockify" ? "Clockify" : "your spreadsheet";
    if (!preview.count) { notice(`This day is already in ${target}. There is nothing new to write.`); return; }
    const entries = `${preview.count} ${preview.count === 1 ? "entry" : "entries"}`;
    const skipped = Number((preview.text.match(/would skip (\d+)/) || [0, 0])[1]);
    const summary = `Time already in ${target} is skipped, and monthly limits are checked.` +
      (skipped ? ` ${skipped} ${skipped === 1 ? "entry is" : "entries are"} already logged and will be skipped.` : "");
    confirmation(section, `Write ${entries} (${duration(preview.hours * 60)}) to ${target}?`, summary,
      `Write ${entries}`, async () => {
        const result = await api("write", {day: preview.day, confirm: true, preview: preview.preview});
        notice(result.message); reviewed = null; writeButton.disabled = true;
      }, () => {}, preview.text);
  }, "primary");
  writeButton.disabled = true;
  const reportButton = button("Open full report", async () => { await api("review/open", {day}); notice("Your private report opened in your browser."); }, "text-button");
  reportButton.disabled = true;
  const yesterday = button("Yesterday", () => load(state.yesterday), "date-chip");
  const today = button("Today", () => load(state.today), "date-chip");
  section.append(el("div", {class: "row input-row date-controls wrap"}, date, el("div", {class: "row date-chips", role: "group", "aria-label": "Review date"}, yesterday, today)),
    results, el("div", {class: "row wrap"}, writeButton, reportButton));
  date.querySelector("input").addEventListener("change", () => { fallback = false; load(value("day")); });
  async function load(chosen) {
    const request = ++requestNumber;
    section.querySelector(".confirmation")?.remove();
    reviewed = null; writeButton.disabled = reportButton.disabled = true;
    date.querySelector("input").value = chosen;
    yesterday.setAttribute("aria-pressed", String(chosen === state.yesterday));
    today.setAttribute("aria-pressed", String(chosen === state.today));
    results.replaceChildren(loadingRows(chosen === state.yesterday ? "Reading yesterday's activity..." : chosen === state.today ? "Reading today's activity..." : "Reading this day's activity..."));
    try {
      let result = await api("review?day=" + encodeURIComponent(chosen));
      if (request !== requestNumber) return;
      if (fallback && !result.entries.length && chosen === state.yesterday) { chosen = state.today; result = await api("review?day=" + chosen); }
      fallback = false;
      if (request !== requestNumber) return;
      if (toast.querySelector(".notification.error")) notice("");
      day = chosen; date.querySelector("input").value = chosen; reviewed = result;
      yesterday.setAttribute("aria-pressed", String(chosen === state.yesterday));
      today.setAttribute("aria-pressed", String(chosen === state.today));
      const metric = (number, label, format) => {
        const figure = el("strong", {}, el("span", {class: "visually-hidden"}, format(number)), el("span", {"aria-hidden": "true"}, format(number)));
        const node = el("div", {class: "metric"}, el("small", {}, label), figure);
        results.querySelector(".metrics").append(node);
        if (step === "home") animateValue(figure.lastChild, number, n => { figure.lastChild.textContent = format(n); });
      };
      results.replaceChildren(el("div", {class: "metrics"}));
      metric(result.minutes, "Time", duration);
      metric(result.entries.length, "Entries", n => String(Math.round(n)));
      for (const amount of result.amounts) {
        const [number, currency] = amount.split(" ");
        metric(Number(number), "Amount", n => n === Number(number) ? amount : `${n.toFixed(2)} ${currency}`);
      }
      if (!result.entries.length) results.append(el("p", {class: "muted"}, "No timesheet entries yet. Let ActivityWatch record some work, then review this day again."));
      else {
        const descriptions = result.entries.some(e => e.description !== e.project);
        const fullDate = new Intl.DateTimeFormat(undefined, {weekday: "long", year: "numeric", month: "long", day: "numeric"}).format(new Date(chosen + "T12:00:00"));
        const table = el("table", {}, el("caption", {class: "muted"}, el("strong", {}, "Timesheet entries"), fullDate),
          el("thead", {}, el("tr", {}, ...["Time", "Project", ...(descriptions ? ["Description"] : []), "Duration"].map(h => el("th", {scope: "col"}, h)))),
          el("tbody", {}, ...result.entries.map(e => el("tr", {}, el("td", {}, e.time), el("td", {}, e.project), descriptions ? el("td", {}, e.description) : null, el("td", {}, duration(e.minutes))))));
        results.append(el("div", {class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Timesheet entries, scroll to see all columns"}, table));
      }
      if (result.unmatched_minutes > 0) results.append(el("p", {class: "review-note"}, `${duration(result.unmatched_minutes)} of activity did not match a project. `,
        button("Assign it", async () => { editing = true; await projectsScreen(); }, "text-button")));
      if (result.short_piece_minutes > 0) results.append(el("p", {class: "review-note"}, `${duration(result.short_piece_minutes)} was in pieces too short to bill (under ${result.minimum_minutes} min).`));
      results.append(el("details", {}, el("summary", {}, "How is this worked out?"),
        el("p", {}, "Rounding and monthly limits can change totals. Confirmed offline work is included."),
        el("p", {}, "Nearby work can share an entry. Excluded gaps are not billed. Time away stays out unless your agreement counts it."),
        el("p", {}, "The write preview checks time already logged and monthly limits. Monthly local review can differ because writing reserves logged destination time.")));
      writeButton.disabled = !result.entries.length; reportButton.disabled = false;
      buttonLabel(writeButton, `Write ${day === state.yesterday ? "yesterday" : day === state.today ? "today" : "this day"} to ${state.destination.type === "clockify" ? "Clockify" : "your spreadsheet"}`, "arrow--right");
    } catch (error) {
      if (request !== requestNumber) return;
      results.replaceChildren(); showError(error);
    }
  }
  return {section, load};
}

function scheduleCard() {
  const section = card("Every morning");
  let enabled = state.schedule.startsWith("On");
  let savedTime = /\d{2}:\d{2}/.exec(state.schedule)?.[0] || "06:00";
  let revision = 0;
  const timeField = field("Time on this computer", "at", savedTime, "time");
  const timeInput = timeField.querySelector("input");
  const restore = () => { input.checked = enabled; timeInput.value = savedTime; };
  const updateState = () => {
    state.schedule = enabled ? `On at ${savedTime}` : "Off";
    const tileState = document.getElementById("morning-state");
    if (tileState) tileState.textContent = state.schedule;
    restore();
  };
  async function preview(wanted) {
    const request = ++revision;
    section.querySelector(".confirmation")?.remove();
    input.checked = enabled;
    input.disabled = timeInput.disabled = true;
    try {
      if (!wanted) {
        confirmation(section, "Stop automatic morning writes?", `Remove the daily ${savedTime} schedule on this computer. Existing timesheets stay as they are.`, "Turn off", async () => {
          await api("schedule", {confirm: true}, "DELETE"); enabled = false; updateState();
        }, restore);
        return;
      }
      const plan = await api("schedule/plan?at=" + encodeURIComponent(timeInput.value));
      if (request !== revision || !section.isConnected) return;
      confirmation(section, `Write yesterday every morning at ${plan.at}?`, plan.text, enabled ? "Use this time" : "Turn on", async () => {
        await api("schedule", {confirm: true, preview: plan.preview});
        enabled = true; savedTime = plan.at; updateState();
      }, restore);
    } catch (error) { restore(); showError(error); }
    finally { input.disabled = timeInput.disabled = false; }
  }
  const switchBox = toggle("Write yesterday's timesheet automatically", "nightly", enabled, checked => preview(checked));
  const input = switchBox.querySelector("input");
  timeInput.addEventListener("change", () => preview(true));
  section.append(el("div", {class: "schedule-row"}, switchBox, timeField),
    el("small", {}, "Writes yesterday only. Missed days are not backfilled."));
  return section;
}

async function finish() {
  screen("finish", "Check and finish", "Your settings are saved. Review your time and choose what happens next.");
  foot("Finish", home, billing);
  const current = generation;
  const checks = card("Checking your settings", loadingRows("Checking connections..."));
  const review = reviewCard(state.yesterday, true);
  page.append(checks, review.section, scheduleCard());
  const reviewReady = review.load(state.yesterday);
  try {
    const result = await api("doctor"); if (generation !== current) return;
    checks.replaceChildren(el("h2", {}, result.checks.every(c => c.ok) ? "All set" : "A few things to fix"), el("ul", {class: "checklist"}, ...result.checks.map(c => el("li", {class: c.ok ? "good" : "warning"}, icon(c.ok ? "checkmark--filled" : "warning--alt--filled"), c.message))));
  } catch (error) { checks.replaceChildren(el("h2", {}, "Settings check unavailable"), el("p", {}, "Open Check and finish again to retry the settings check.")); showError(error); }
  await reviewReady;
  if (generation !== current) return;
  if (state.destination.type === "clockify" && state.projects.some(p => p.agreement.billing === "hourly")) {
    const rates = card("Clockify rates", el("div", {class: "skeleton"})); page.append(rates);
    try {
      const result = await api("rates"); if (generation !== current) return;
      const text = Array.isArray(result.messages) ? result.messages.join("\n") : result.messages;
      if (result.changes === false) { rates.replaceChildren(el("h2", {}, "Clockify rates"), el("pre", {}, text)); return; }
      rates.replaceChildren(el("h2", {}, "Clockify rates"), el("pre", {}, text), button("Update Clockify", () => {
        confirmation(rates, "Apply these exact changes to Clockify?", text, "Update Clockify", async () => {
          const updated = await api("rates/apply", {confirm: true, preview: result.preview});
          rates.replaceChildren(el("h2", {}, updated.failed ? "Some rates need attention" : "Clockify rates checked"), el("pre", {}, updated.messages.join("\n")));
        });
      }));
    } catch (error) { rates.replaceChildren(el("h2", {}, "Clockify rates unavailable")); showError(error); }
  }
  if (generation !== current) return;
}

async function home() {
  await projectQueue.catch(() => {});
  await refresh(); editing = false;
  screen("home", "Your timesheets", "Review your time, write timesheets and manage your settings.");
  page.append(notification(nightlyKind(state.last_run), "Last morning run", state.last_run));
  const review = reviewCard(state.yesterday); page.append(review.section);
  const morning = scheduleCard(); morning.hidden = true;
  const billingNames = {hourly: "hourly", flat: "flat fee", retainer: "retainer", none: "not billed"};
  const kinds = [...new Set(state.projects.map(p => billingNames[p.agreement.billing] || "billing not set"))].join(", ");
  function tile(title, description, status, symbol, action) {
    const node = button("", action, "clickable-tile");
    node.replaceChildren(icon(symbol, 24), el("strong", {}, title), el("span", {class: "tile-description"}, description), status, icon("arrow--right"));
    return node;
  }
  page.append(el("div", {class: "tiles"},
    tile("Projects and billing", "Match activity and manage agreements", el("small", {class: "tile-state"}, `${state.projects.length} ${state.projects.length === 1 ? "project" : "projects"}, ${kinds}`), "folder", async () => { editing = true; await projectsScreen(); }),
    tile("Every morning", "Set up automatic daily writes", el("small", {id: "morning-state", class: "tile-state"}, state.schedule), "time", () => { morning.hidden = !morning.hidden; if (!morning.hidden) { morning.scrollIntoView({block: "start"}); morning.querySelector("input").focus({preventScroll: true}); } }),
    tile("Settings file", "Open in your text editor", el("small", {class: "tile-state"}, "Saved on this computer"), "document", async () => { await api("settings/open", {}); notice("Your settings file opened in your default editor."); }),
    tile("Run setup again", "Start over with new answers", el("small", {class: "tile-state"}, "Review before saving"), "renew", () => { editing = false; welcome(); })), morning);
  await review.load(state.yesterday);
}

document.addEventListener("click", e => { if (!e.target.closest("#project-menu, #project-more")) closeProjectMenu(); });
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.defaultPrevented && !e.isComposing && !e.ctrlKey && !e.metaKey && !e.altKey &&
      !e.target.closest("button, a, summary, textarea, select, input[type=checkbox], input[type=radio], .confirmation") && primary && !primary.disabled) { e.preventDefault(); primary.click(); }
});
document.querySelector("#brand").addEventListener("click", e => {
  e.preventDefault();
  if (!disconnected && state?.saved && step !== "home") confirmation(page, "Return home?", "Unsaved changes will be discarded. Saved settings and completed writes stay as they are.", "Return home", cancelEdit);
});
document.querySelector("#quit").addEventListener("click", () => {
  confirmation(page, "Close autohours?", "Unsaved setup answers will be lost. Saved settings and completed writes stay on this computer.", "Close app", async () => {
    await api("quit", {});
    closedScreen(); window.close();
  });
});
function closedScreen(expired = false) {
  if (disconnected) return;
  disconnected = true; token = ""; generation++;
  clearInterval(heartbeat); clearTimeout(awTimer);
  try { sessionStorage.removeItem(sessionKey); } catch {}
  primary = null; beforeStepBack = () => {};
  const shell = document.querySelector("#app-shell");
  shell.dataset.screen = "closed";
  shell.dataset.layout = "readable";
  shell.classList.remove("short-screen");
  document.querySelector(".welcome-preview")?.remove();
  document.querySelector("#setup-progress").hidden = true;
  document.querySelector("#quit").hidden = true;
  footer.replaceChildren(); footer.hidden = true;
  toast.replaceChildren(); toast.hidden = true;
  page.classList.remove("page-enter");
  const heading = el("h1", {tabindex: "-1"}, expired ? "This window has expired" : "autohours has closed");
  page.replaceChildren(el("section", {class: "closed-state"}, icon("time", 24), heading,
    el("p", {}, expired ? "This window no longer has an active autohours session. Your saved settings are safe." :
      "This window lost its connection, usually because autohours was closed or the computer went to sleep. Your saved settings are safe."),
    el("p", {}, "Close this window and open autohours again to carry on.")));
  heading.focus();
}
async function beat() {
  if (disconnected) return;
  try { await api("heartbeat", {}); }
  catch { closedScreen(); }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && token) beat(); });
(async () => {
  await loadIcons();
  try {
    const bootstrap = new URLSearchParams(location.hash.slice(1)).get("b");
    history.replaceState(null, "", location.pathname + location.search);
    if (bootstrap) {
      const response = await fetch("/api/session", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({bootstrap}), cache: "no-store", credentials: "omit"
      });
      if (!response.ok) throw new Error("Expired session");
      const result = await response.json();
      token = result.token;
      try { sessionStorage.setItem(sessionKey, token); } catch {}
    } else {
      try { token = sessionStorage.getItem(sessionKey) || ""; } catch {}
    }
    if (!token) throw new Error("Expired session");
    await api("heartbeat", {});
  } catch {
    closedScreen(true);
    return;
  }
  heartbeat = setInterval(beat, 5000);
  try { await refresh(); if (state.saved) await home(); else welcome(); }
  catch (error) { showError(error); }
})();
