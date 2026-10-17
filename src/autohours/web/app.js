"use strict";

// The view sends answers to Python. It never calculates billing or builds rules.
let token = "", heartbeat;
const sessionKey = "autohours-token";
const page = document.querySelector("#page");
const footer = document.querySelector("#footer");
const toast = document.querySelector("#toast");
let state, step = "welcome", editing = false, generation = 0, awTimer;
let projects = [], items = [], remote = [], selected = 0, activitySearch = "";
let projectQueue = Promise.resolve(), projectFailure = null, projectRevision = 0;
let primary, keyConnected = false, singleWorkspace = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child.nodeType ? child : document.createTextNode(String(child)));
  return node;
}
function button(label, action, className = "") {
  const b = el("button", {type: "button", class: className}, label);
  if (action) b.addEventListener("click", () => work(b, action));
  return b;
}
async function api(path, data, method = data === undefined ? "GET" : "POST") {
  const response = await fetch("/api/" + path, {
    method, headers: {"X-Autohours-Token": token, ...(data === undefined ? {} : {"Content-Type": "application/json"})},
    body: data === undefined ? undefined : JSON.stringify(data), cache: "no-store", credentials: "omit"
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || "Please try again."), {field: result.field});
  return result;
}
function notice(message, failure = false) {
  toast.textContent = message;
  toast.hidden = !message;
  toast.classList.toggle("failure", failure);
}
function clearErrors() {
  page.querySelectorAll("[aria-invalid]").forEach(clearFieldError);
  page.querySelectorAll(".error").forEach(n => n.remove());
  notice("");
}
function clearFieldError(field) {
  if (!field) return;
  document.getElementById("error-" + field.id)?.remove();
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
function showError(error) {
  if (step === "projects" && /^project-\d+$/.test(error.field || "")) {
    selected = Number(error.field.slice(8)); renderProject();
  }
  const field = error.field && document.getElementById(error.field);
  if (field) {
    for (let parent = field.closest("details"); parent; parent = parent.parentElement?.closest("details")) parent.open = true;
    const id = "error-" + error.field;
    document.getElementById(id)?.remove();
    const message = el("p", {id, class: "error", role: "alert"}, error.message);
    field.after(message);
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("aria-describedby", [...new Set([...(field.getAttribute("aria-describedby") || "").split(" ").filter(Boolean), id])].join(" "));
    const target = error.field.startsWith("project-") ? document.querySelector("#activity-list input:not(:disabled)") || field :
      field.matches("input, select, button") ? field : field.querySelector("input, button") || field;
    target.focus();
  } else notice(error.message || "Could not connect. Reopen autohours and try again.", true);
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
  return el("label", {class: "field", for: id}, el("span", {}, label), input);
}
function toggle(label, id, checked = false, change = () => {}) {
  const input = el("input", {id, type: "checkbox", role: "switch", onchange: () => change(input.checked)});
  input.checked = checked;
  return el("label", {class: "toggle", for: id}, input, el("span", {}, label));
}
function choices(title, id, options, value, change = () => {}, segmented = false, help = "") {
  const group = el("fieldset", {id, class: segmented ? "segments" : "choices", tabindex: "-1"}, el("legend", {}, title));
  if (help) {
    group.append(el("small", {id: id + "-help", class: "question-help"}, help));
    group.setAttribute("aria-describedby", id + "-help");
  }
  options.forEach(([key, label, detail, icon]) => {
    const input = el("input", {type: "radio", name: id, value: key, onchange: () => change(key)});
    input.checked = String(value) === String(key);
    group.append(el("label", {class: segmented ? "segment" : "choice"}, input,
      !segmented && icon ? el("span", {class: "choice-icon", "aria-hidden": "true"}, icon) : null,
      segmented ? label : el("span", {}, el("strong", {}, label), el("small", {}, detail || "")),
      !segmented ? el("span", {class: "tick", "aria-hidden": "true"}, "✓") : null));
  });
  return group;
}
function value(id) { return document.getElementById(id)?.value || ""; }
function radio(id) { return document.querySelector(`#${id} input:checked`)?.value || ""; }
function card(title, ...children) { return el("section", {class: "card"}, title ? el("h2", {}, title) : null, children); }
function link(label, url) { return el("a", {class: "button-link", href: url, target: "_blank", rel: "noreferrer noopener"}, label); }
function foot(label, action, back) {
  footer.replaceChildren();
  if (back) footer.append(button("Back", back, "text-button"));
  primary = button(label, action, "primary");
  footer.append(primary);
}
function screen(name, title, subtitle) {
  step = name; generation++; clearTimeout(awTimer); clearErrors();
  page.replaceChildren(el("h1", {tabindex: "-1"}, title), el("p", {class: "subtitle"}, subtitle));
  page.classList.remove("page-enter");
  requestAnimationFrame(() => page.classList.add("page-enter"));
  footer.replaceChildren(); primary = null;
  const steps = ["welcome", "activitywatch", "destination", ...(state?.destination.type === "clockify" ? ["connect", ...(!singleWorkspace ? ["workspace"] : [])] : []), "projects", "billing", "finish"];
  const index = steps.indexOf(name);
  document.querySelector("#progress-label").textContent = name === "home" ? "Your workspace" : editing ? "Projects and billing" : `Step ${index + 1} of ${steps.length}`;
  document.querySelector("#progress").max = steps.length;
  document.querySelector("#progress").value = index + 1;
  document.querySelector("#progress").hidden = name === "home";
  page.querySelector("h1").focus({preventScroll: true});
  window.scrollTo(0, 0);
}
async function refresh() { state = await api("state"); }
async function cancelEdit() { await projectQueue.catch(() => {}); await api("reset", {}); await home(); }

function welcome() {
  screen("welcome", "Turn your computer activity into timesheets, automatically.", "A little setup now. More time for your work later.");
  page.append(card(null, el("ul", {class: "benefits"},
    el("li", {}, "Tracks what you work on"), el("li", {}, "Leaves out time you were away"),
    el("li", {}, "Writes to Clockify or a spreadsheet"))));
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
}

function activityWatch() {
  screen("activitywatch", "Meet ActivityWatch", "A free app that records which apps you use and when you step away.");
  const status = card(null, el("p", {role: "status", "aria-live": "polite"}, "Checking ActivityWatch..."));
  const download = link("Download ActivityWatch", "https://activitywatch.net/downloads/"); download.hidden = true;
  const hostBox = el("div", {hidden: true});
  const host = el("select", {id: "hostname"});
  hostBox.append(el("label", {class: "field", for: "hostname"}, el("span", {}, "Computer to use"), host));
  const web = toggle("Also use websites from the ActivityWatch browser extension", "use_web", state.activitywatch.use_web || false, () => check());
  page.append(status, download, hostBox, web);
  let running = false, checking = false;
  const current = generation;
  async function check() {
    if (checking || generation !== current) return;
    checking = true;
    try {
      const result = await api("activitywatch/check", {hostname: host.value || state.activitywatch.hostname, use_web: web.querySelector("input").checked});
      if (generation !== current) return;
      running = result.running;
      status.classList.toggle("success", running);
      status.replaceChildren(el("p", {role: "status", "aria-live": "polite"}, (running ? "✓ " : "") + result.message));
      if (!running) status.append(el("small", {class: "busy"}, "Checking..."));
      download.hidden = running || result.hosts.length > 0;
      const previous = host.value;
      host.replaceChildren(el("option", {value: ""}, "Choose your computer"), ...result.hosts.map(h => el("option", {value: h}, h)));
      host.value = result.hostname || previous;
      hostBox.hidden = result.hosts.length <= 1;
      if (running) state.activitywatch = {hostname: result.hostname, use_web: web.querySelector("input").checked};
    } catch (error) { if (generation === current) showError(error); }
    finally { checking = false; if (generation === current && !running) awTimer = setTimeout(check, 3000); }
  }
  host.addEventListener("change", () => { running = false; check(); });
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
    ["clockify", "Clockify", "Time tracking app, rates and invoices", "◷"],
    ["csv", "A spreadsheet file", "Opens in Excel, Numbers or Google Sheets", "▤"]
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
    status.replaceChildren(card(null, el("p", {class: "success"}, `✓ Connected as ${result.name}`)));
    instructions.hidden = saved.hidden = true;
    primary.textContent = "Continue";
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
    loading.replaceWith(el("p", {class: "error"}, error.message));
    foot("Try again", workspace, connect); return;
  }
  if (current !== generation) return;
  loading.replaceWith(choices("Workspace", "workspace", result.workspaces.map(w => [w.id, w.name, "Your Clockify projects", "◷"]), state.destination.workspace || ""));
  foot("Continue", async () => {
    const result = await api("clockify/workspace", {workspace: radio("workspace")});
    state.currency = result.currency; state.workspace_name = result.workspace_name;
    await projectsScreen();
  }, connect);
}

function updateCoverage(percent) {
  const bar = document.querySelector("#coverage");
  if (bar) { bar.value = percent; document.querySelector("#coverage-label").textContent = `${Math.round(percent)}% of your last 7 days is assigned`; }
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
function activityRows() {
  const list = document.querySelector("#activity-list");
  if (!list) return;
  const focused = list.contains(document.activeElement) ? document.activeElement.id : null;
  list.replaceChildren();
  const project = projects[selected];
  for (const item of items.filter(item => item.name.toLowerCase().includes(activitySearch.toLowerCase()))) {
    const input = el("input", {id: `activity-${item.id}`, type: "checkbox", "aria-label": `Assign ${item.name} to ${project?.name || "a project"}`});
    input.checked = !!project?.items.includes(item.id); input.disabled = !project;
    const badges = el("span", {});
    for (const other of projects.filter(p => p !== project && p.items.includes(item.id))) badges.append(el("span", {class: "assigned"}, other.name));
    const label = el("label", {class: "activity-row"}, input,
      el("span", {class: "name"}, item.name, el("small", {}, item.kind), badges),
      el("span", {class: "hours"}, duration(item.hours * 60)));
    input.addEventListener("change", async () => {
      const checked = input.checked;
      projects.forEach(p => { p.items = p.items.filter(id => id !== item.id); });
      if (checked) project.items.push(item.id);
      clearFieldError(document.getElementById(`project-${selected}`));
      // Keep this native checkbox focusable while the save is in flight.
      await saveProjects();
      // Keep the clicked input in place so the first click and focus never scroll.
      badges.replaceChildren();
      renderPills();
    });
    list.append(label);
  }
  if (!list.children.length) list.append(el("p", {class: "muted"}, "No activity matches your search."));
  if (focused) document.getElementById(focused)?.focus({preventScroll: true});
}
function renderPills(menuOpen = !!document.querySelector("#project-menu") && !document.querySelector("#project-menu").hidden) {
  const pills = document.querySelector("#project-pills"); if (!pills) return;
  pills.replaceChildren();
  projects.forEach((project, i) => {
    const b = button("", () => { selected = i; renderProject(); document.getElementById(`pill-${i}`)?.focus({preventScroll: true}); });
    b.id = `pill-${i}`;
    b.className = "pill"; b.setAttribute("aria-pressed", String(i === selected));
    b.append(el("span", {class: `dot dot-${i % 4}`, "aria-hidden": "true"}), project.name);
    const pill = el("div", {class: "project-pill"}, b);
    if (i === selected) {
      const more = button("...", () => {
        const menu = document.querySelector("#project-menu");
        menu.hidden = !menu.hidden;
        more.setAttribute("aria-expanded", String(!menu.hidden));
        if (!menu.hidden) menu.querySelector("input").focus();
      }, "project-more");
      more.setAttribute("aria-label", `More options for ${project.name}`);
      more.setAttribute("aria-controls", "project-menu"); more.setAttribute("aria-expanded", String(menuOpen));
      pill.append(more);
    }
    pills.append(pill);
  });
}
function renderProject() {
  renderPills(false); activityRows();
  const details = document.querySelector("#project-details"); details.replaceChildren();
  const project = projects[selected]; if (!project) return;
  details.id = "project-details";
  const validation = el("div", {id: `project-${selected}`, tabindex: "-1"});
  const menu = el("div", {id: "project-menu", class: "project-actions", hidden: true});
  menu.append(field("Project name", "rename", project.name), field("Timesheet description", "description", project.description));
  menu.append(button("Save details", async () => {
    project.name = value("rename"); project.description = value("description"); await saveProjects();
    if (!projectFailure) renderProject();
  }), button("Move up", async () => {
    if (selected > 0) { [projects[selected - 1], projects[selected]] = [projects[selected], projects[selected - 1]]; selected--; await saveProjects(); renderProject(); }
  }, "text-button"), button("Remove project", async () => { projects.splice(selected, 1); selected = Math.max(0, selected - 1); await saveProjects(); renderProject(); }, "text-button"));
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
  if (state.workspace_name) page.append(el("small", {}, `Using ${state.workspace_name} in Clockify.`));
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
  page.append(el("div", {class: "row input-row"}, addField, addButton), el("div", {id: "project-pills", class: "pills", "aria-label": "Choose a project"}), el("div", {id: "project-details"}));
  const loading = loadingRows("Reading your last 7 days of activity..."); page.append(loading);
  foot("Continue", async () => { await activityReady; if (ready) { await saveProjects(true); billing(); } }, back);
  const activityReady = api("activity").then(result => {
    if (generation !== current) return;
    loading.remove(); items = result.items; projects = result.projects; remote = result.remote;
    state.currency = result.currency; state.workspace_name = result.workspace_name;
    selected = Math.min(selected, Math.max(0, projects.length - 1));
    const search = field("Search your activity", "activity-search", activitySearch, "search");
    search.querySelector("input").addEventListener("input", e => { activitySearch = e.target.value; activityRows(); });
    page.append(el("h2", {}, "Your activity from the last 7 days"), search,
      el("small", {}, "Picking an app includes all time in that app. Pick a window title for work in a shared app."),
      el("div", {id: "activity-list", class: "activity-list"}),
      el("div", {class: "coverage"}, el("p", {id: "coverage-label", "aria-live": "polite"}), el("progress", {id: "coverage", max: "100", "aria-label": "Activity assigned"})));
    if (items.some(item => item.matches.length > 1)) page.append(el("small", {}, "When activity matches more than one project, the project higher in your list gets the time."));
    renderProject(); updateCoverage(result.coverage);
    ready = true;
  }).catch(error => {
    if (generation !== current) return;
    loading.replaceWith(el("p", {class: "error", role: "status"}, error.message));
    foot("Try again", projectsScreen, back);
  });
  await activityReady;
}

function billing() {
  screen("billing", projects.length === 1 ? `How do you bill ${projects[0].name}?` : "How do you bill your projects?", "Use the agreement you have with each client. You can leave the hourly rate empty.");
  projects.forEach((project, i) => {
    const a = project.agreement;
    const group = card(project.name);
    const rates = el("div", {class: "rate-row"}, field("Your rate", `rate-${i}`, a.rate ?? "", "number", {min: "0", step: "any"}),
      el("span", {class: "muted"}, "per hour in"), field("Currency", `currency-${i}`, a.currency || state.currency || "", "text", {maxlength: "3", placeholder: "For example, CAD"}));
    rates.hidden = a.billing !== "hourly";
    group.append(choices("How do you bill this client?", `billing-${i}`, [
      ["hourly", "By the hour", "Track time and an optional hourly amount", "◷"],
      ["flat", "Flat monthly fee", "Track time covered by a fixed fee", "▤"],
      ["retainer", "Retainer with a monthly cap", "Track time within your agreement", "◴"],
      ["none", "Not billed", "Keep a record without billing", "○"]
    ], a.billing || "", v => { a.billing = v; rates.hidden = v !== "hourly"; }, false,
    "Your rate can be added later. No rate is assumed."), rates);
    const breaks = String(a.count_breaks_up_to_minutes ?? 0);
    const custom = field("Custom break limit in minutes", `count_breaks_up_to_minutes-${i}`, breaks, "number", {min: "0", max: "1440", step: "1"});
    custom.hidden = ["0", "5", "10", "15"].includes(breaks);
    group.append(choices("Do short breaks count?", `breaks-${i}`, [["0", "No"], ["5", "5 min"], ["10", "10 min"], ["15", "15 min"], ["custom", "Custom"]], custom.hidden ? breaks : "custom", v => {
      custom.hidden = v !== "custom";
      if (v !== "custom") custom.querySelector("input").value = v;
    }, true, "The limit includes exactly that many minutes. Longer breaks stay out."), custom,
    el("h3", {}, "Count calls when you step away from the keyboard?"),
    el("small", {}, "A Zoom call with no typing can still count when it matches this project."),
    toggle("Count calls while away", `calls-${i}`, a.count_calls_when_away || false));
    const quantum = String(a.round_to_minutes ?? 0);
    const roundingOptions = [["0", "No rounding"], ["6", "6 min"], ["15", "15 min"], ["30", "30 min"]];
    if (!roundingOptions.some(o => o[0] === quantum)) roundingOptions.push([quantum, `${quantum} min (saved)`]);
    const roundUp = toggle("Always round up", `up-${i}`, a.rounding === "up");
    roundUp.hidden = quantum === "0";
    group.append(choices("Round each entry", `round_to_minutes-${i}`, roundingOptions, quantum, v => { roundUp.hidden = v === "0"; }, true,
      "Use the closest interval, or choose to always round up."), roundUp,
      el("details", {}, el("summary", {}, "More options"), field("Monthly cap in hours", `monthly_cap_hours-${i}`, a.monthly_cap_hours ?? "", "number", {min: "0", step: "any"})));
    page.append(group);
  });
  function collect() {
    return projects.map((p, i) => ({billing: radio(`billing-${i}`), rate: value(`rate-${i}`), currency: value(`currency-${i}`),
      count_breaks_up_to_minutes: value(`count_breaks_up_to_minutes-${i}`), count_calls_when_away: document.getElementById(`calls-${i}`).checked,
      round_to_minutes: radio(`round_to_minutes-${i}`), rounding: document.getElementById(`up-${i}`).checked ? "up" : "nearest", monthly_cap_hours: value(`monthly_cap_hours-${i}`)}));
  }
  foot("Save and continue", async () => {
    const agreements = collect();
    await api("agreements", {agreements});
    await api("save", {});
    projects.forEach((p, i) => { p.agreement = agreements[i]; });
    await refresh();
    if (editing) { editing = false; await home(); } else await finish();
  }, async () => {
    const agreements = collect(); projects.forEach((p, i) => { p.agreement = agreements[i]; });
    // Keep unfinished billing answers in this page until the user returns.
    const drafts = projects.map(p => [p.name, p.agreement]);
    await projectsScreen();
    for (const p of projects) p.agreement = drafts.find(([name]) => name === p.name)?.[1] || p.agreement;
  });
}

function confirmation(parent, title, text, approveLabel, action, cancel = () => {}) {
  parent.querySelector(".confirmation")?.remove();
  const panel = el("section", {class: "confirmation", tabindex: "-1", "aria-label": title}, el("h3", {}, title));
  if (text) panel.append(el("pre", {}, text));
  panel.append(el("div", {class: "row wrap"}, button(approveLabel, async () => { await action(); panel.remove(); }, "primary"),
    button("Not now", () => { panel.remove(); cancel(); }, "text-button")));
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
    confirmation(section, `Write ${preview.count} entries (${duration(preview.hours * 60)}) to ${target}?`,
      "The preview below checks existing entries and monthly limits. Already logged time is skipped.\n\n" + preview.text,
      "Write them", async () => {
        const result = await api("write", {day: preview.day, confirm: true, preview: preview.preview});
        notice(result.message); reviewed = null; writeButton.disabled = true;
      });
  });
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
      day = chosen; date.querySelector("input").value = chosen; reviewed = result;
      yesterday.setAttribute("aria-pressed", String(chosen === state.yesterday));
      today.setAttribute("aria-pressed", String(chosen === state.today));
      const metric = (number, label) => el("div", {class: "metric"}, el("strong", {}, number), el("small", {}, label));
      results.replaceChildren(el("div", {class: "metrics"}, metric(duration(result.minutes), "Time"), metric(String(result.entries.length), "Entries"), ...result.amounts.map(a => metric(a, "Hourly amount"))));
      if (!result.entries.length) results.append(el("p", {class: "muted"}, "No timesheet entries yet. Let ActivityWatch record some work, then review this day again."));
      else {
        const descriptions = result.entries.some(e => e.description !== e.project);
        const fullDate = new Intl.DateTimeFormat(undefined, {weekday: "long", month: "long", day: "numeric"}).format(new Date(chosen + "T12:00:00"));
        const table = el("table", {}, el("caption", {class: "muted"}, fullDate),
          el("thead", {}, el("tr", {}, ...["Time", "Duration", "Project", ...(descriptions ? ["Description"] : [])].map(h => el("th", {scope: "col"}, h)))),
          el("tbody", {}, ...result.entries.map(e => el("tr", {}, el("td", {}, e.time), el("td", {}, duration(e.minutes)), el("td", {}, e.project), descriptions ? el("td", {}, e.description) : null))));
        results.append(el("div", {class: "table-scroll"}, table));
      }
      if (result.unmatched_minutes > 0) results.append(el("p", {class: "review-note"}, `${duration(result.unmatched_minutes)} of activity did not match a project. `,
        button("Assign it", async () => { editing = true; await projectsScreen(); }, "text-button")));
      if (result.short_piece_minutes > 0) results.append(el("p", {class: "review-note"}, `${duration(result.short_piece_minutes)} was in pieces too short to bill (under ${result.minimum_minutes} min).`));
      results.append(el("details", {}, el("summary", {}, "How is this worked out?"),
        el("p", {}, "Rounding and monthly limits can change totals. Confirmed offline work is included."),
        el("p", {}, "Nearby work can share an entry. Excluded gaps are not billed. Time away stays out unless your agreement counts it."),
        el("p", {}, "The write preview checks time already logged and monthly limits. Monthly local review can differ because writing reserves logged destination time.")));
      writeButton.disabled = !result.entries.length; reportButton.disabled = false;
      writeButton.textContent = `Write ${day === state.yesterday ? "yesterday" : day === state.today ? "today" : "this day"} to ${state.destination.type === "clockify" ? "Clockify" : "your spreadsheet"}`;
    } catch (error) {
      if (request !== requestNumber) return;
      results.replaceChildren(el("p", {class: "error", role: "status"}, error.message));
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
  const switchBox = toggle("Write yesterday's timesheet every morning at", "nightly", enabled, checked => preview(checked));
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
    checks.replaceChildren(el("h2", {}, result.checks.every(c => c.ok) ? "All set" : "A few things to fix"), el("ul", {class: "checklist"}, ...result.checks.map(c => el("li", {class: c.ok ? "good" : "warning"}, `${c.ok ? "✓" : "!"} ${c.message}`))));
  } catch (error) { checks.replaceChildren(el("h2", {}, "A few things to fix"), el("p", {class: "error"}, error.message)); }
  await reviewReady;
  if (generation !== current) return;
  if (state.destination.type === "clockify" && state.projects.some(p => p.agreement.billing === "hourly")) {
    const rates = card("Clockify rates", el("div", {class: "skeleton"})); page.append(rates);
    try {
      const result = await api("rates"); if (generation !== current) return;
      const text = Array.isArray(result.messages) ? result.messages.join("\n") : result.messages;
      rates.replaceChildren(el("h2", {}, "Clockify rates"), el("pre", {}, text), button("Update Clockify", () => {
        confirmation(rates, "Apply these exact changes to Clockify?", text, "Update Clockify", async () => {
          const updated = await api("rates/apply", {confirm: true, preview: result.preview});
          rates.replaceChildren(el("h2", {}, updated.failed ? "Some rates need attention" : "Clockify rates checked"), el("pre", {}, updated.messages.join("\n")));
        });
      }));
    } catch (error) { rates.replaceChildren(el("p", {class: "error"}, error.message)); }
  }
  if (generation !== current) return;
}

async function home() {
  await projectQueue.catch(() => {});
  await refresh(); editing = false;
  screen("home", "Your timesheets", "A clear view of your work, ready when you are.");
  page.append(card("Last nightly run", el("p", {class: "muted"}, state.last_run)));
  const review = reviewCard(state.yesterday); page.append(review.section);
  const morning = scheduleCard(); morning.hidden = true;
  const billingNames = {hourly: "hourly", flat: "flat fee", retainer: "retainer", none: "not billed"};
  const kinds = [...new Set(state.projects.map(p => billingNames[p.agreement.billing] || "billing not set"))].join(", ");
  function tile(title, description, status, drawing, action) {
    const node = button("", action);
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({viewBox: "0 0 24 24", width: "26", height: "26", fill: "none", stroke: "currentColor", "stroke-width": "1.6", "aria-hidden": "true"})) icon.setAttribute(key, value);
    const path = document.createElementNS(icon.namespaceURI, "path"); path.setAttribute("d", drawing); icon.append(path);
    node.append(icon, el("strong", {}, title), el("small", {}, description), status);
    return node;
  }
  page.append(el("div", {class: "tiles"},
    tile("Projects and billing", "Match activity and manage agreements", el("small", {class: "tile-state"}, `${state.projects.length} ${state.projects.length === 1 ? "project" : "projects"}, ${kinds}`), "M3 7h7l2 2h9v11H3z M3 7V4h7l2 3h9v2", async () => { editing = true; await projectsScreen(); }),
    tile("Every morning", "Set up automatic daily writes", el("small", {id: "morning-state", class: "tile-state"}, state.schedule), "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l4 2", () => { morning.hidden = !morning.hidden; if (!morning.hidden) { morning.scrollIntoView({block: "start"}); morning.querySelector("input").focus({preventScroll: true}); } }),
    tile("Settings file", "Open in your text editor", el("small", {class: "tile-state"}, "Saved on this computer"), "M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6", async () => { await api("settings/open", {}); notice("Your settings file opened in your default editor."); }),
    tile("Run setup again", "Start over with new answers", el("small", {class: "tile-state"}, "Review before saving"), "M4 10a8 8 0 1 1 1 8 M4 4v6h6", () => { editing = false; welcome(); })), morning);
  await review.load(state.yesterday);
}

document.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.defaultPrevented && !e.isComposing && !e.ctrlKey && !e.metaKey && !e.altKey &&
      !e.target.closest("button, a, summary, textarea, .confirmation") && primary && !primary.disabled) { e.preventDefault(); primary.click(); }
});
document.querySelector("#brand").addEventListener("click", e => {
  e.preventDefault();
  if (state?.saved && step !== "home") confirmation(page, "Return home?", "Unsaved changes will be discarded. Saved settings and completed writes stay as they are.", "Return home", cancelEdit);
});
document.querySelector("#quit").addEventListener("click", () => {
  confirmation(page, "Close autohours?", "Unsaved setup answers will be lost. Saved settings and completed writes stay on this computer.", "Close app", async () => {
    await api("quit", {}); clearInterval(heartbeat);
    page.replaceChildren(el("h1", {}, "See you next time"), el("p", {}, "You can close this window now.")); footer.replaceChildren(); window.close();
  });
});
async function beat() {
  try { await api("heartbeat", {}); }
  catch { notice("This window has disconnected. Reopen autohours to continue.", true); }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && token) beat(); });
(async () => {
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
    token = "";
    try { sessionStorage.removeItem(sessionKey); } catch {}
    page.replaceChildren(el("h1", {}, "This window has expired. Close it and open autohours again."));
    footer.replaceChildren();
    document.querySelector("#quit").disabled = true;
    return;
  }
  heartbeat = setInterval(beat, 5000);
  try { await refresh(); if (state.saved) await home(); else welcome(); }
  catch (error) { showError(error); }
})();
