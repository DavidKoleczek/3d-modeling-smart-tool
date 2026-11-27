"use strict";

// The page asks the exe for things with `ask`, and the exe answers by calling `window.setup.show`.

const element = (id) => document.getElementById(id);
const ask = (message) => window.ipc.postMessage(JSON.stringify(message));

const choices = element("choices");
const agentsView = element("agents-view");
const inUse = element("in-use");
const progress = element("progress");
const providersView = element("providers-view");
const done = element("done");
const steps = element("steps");
const switches = {
  claude: element("claude"),
  codex: element("codex"),
  desktopShortcut: element("desktop-shortcut"),
  startMenuShortcut: element("start-menu-shortcut"),
  startAtSignIn: element("start-at-sign-in"),
};
const providerSwitches = [switches.claude, switches.codex];
const skill = element("skill");
const agentList = element("agent-list");
const method = element("method");

const HINTS = {
  symlink: "One copy in the shared folder, which each agent's own folder links to.",
  copy: "A copy of its own in each agent's folder.",
  none: "Nothing to link: every agent chosen reads the shared folder.",
};

// An update shows the same steps, with nothing to choose before them and nothing to go back to. When it adds an agent
// provider, this is its name.
let updating = false;
let adding = null;
// What the install button says once there is nothing more to choose.
let installWord = "Install";
// Whether the skill is installed already, so its agents are the ones to tick.
let skillInstalled = false;
// What the skills CLI listed, once it has.
let listed = null;

/** Shows one view, and hides the others. */
function showView(view) {
  for (const each of [choices, agentsView, inUse, progress, providersView, done]) each.hidden = each !== view;
}

function setStep(state) {
  const step = steps.lastElementChild;
  // A step that ended with a note didn't do all it set out to, so it gets no check.
  const noted = state === "done" && step?.querySelector(".note");
  if (step) step.className = `step is-${noted ? "noted" : state}`;
}

function showEnd(title, buttons) {
  element("progress-title").textContent = title;
  element("progress-lead").hidden = true;
  for (const id of ["close", "back"]) element(id).hidden = !buttons.includes(id);
  if (buttons.length) element(buttons.at(-1)).focus();
}

function nameInstall() {
  element("install").textContent = skill.checked ? "Next" : installWord;
}

/** Keeps at least one agent provider on: the last one on can't be turned off. */
function holdProviders() {
  const on = providerSwitches.filter((input) => input.checked);
  for (const input of providerSwitches) input.disabled = on.length === 1 && input.checked;
}

/** A folder under the user's own, as `~` and the rest. */
function shortFolder(folder) {
  const home = listed.home;
  return folder.toLowerCase().startsWith(home.toLowerCase()) ? `~${folder.slice(home.length)}` : folder;
}

function agentRow(name, folder, tag) {
  const row = element("agent").content.firstElementChild.cloneNode(true);
  row.querySelector(".name").textContent = name;
  row.querySelector(".path").textContent = shortFolder(folder);
  row.querySelector(".tag").textContent = tag;
  row.dataset.name = name.toLowerCase();
  return row;
}

function showAgents() {
  const installed = new Set(listed.installed);
  const byName = (one, other) => one.name.localeCompare(other.name, undefined, { sensitivity: "base" });
  const first = (agent) => (installed.has(agent.id) || agent.detected ? 0 : 1);
  const sharing = listed.agents.filter((agent) => agent.shares).sort((one, other) => first(one) - first(other));
  const own = listed.agents
    .filter((agent) => !agent.shares)
    .sort((one, other) => first(one) - first(other) || byName(one, other));

  const shared = agentRow("Universal", listed.shared, "Always");
  shared.classList.add("locked");
  const box = shared.querySelector("input");
  box.checked = true;
  box.disabled = true;
  const named = sharing.slice(0, 5).map((agent) => agent.name);
  const also = shared.querySelector(".also");
  also.textContent = `${named.join(", ")}, and ${sharing.length - named.length} more`;
  also.hidden = false;
  shared.dataset.name = ["universal", ...sharing.map((agent) => agent.name.toLowerCase())].join(" ");

  const rows = own.map((agent) => {
    const tag = installed.has(agent.id) ? "Installed" : agent.detected ? "Found" : "";
    const row = agentRow(agent.name, agent.folder, tag);
    const input = row.querySelector("input");
    input.value = agent.id;
    input.checked = skillInstalled ? installed.has(agent.id) : agent.detected;
    return row;
  });
  const divider = document.createElement("div");
  divider.className = "divider";
  const none = document.createElement("p");
  none.className = "none";
  none.textContent = "No agent has that name.";
  none.hidden = true;
  agentList.replaceChildren(shared, divider, ...rows, none);

  element("filter").value = "";
  element("agents-loading").hidden = true;
  element("agents-chosen").hidden = false;
  showMethod();
}

function chosenAgents() {
  return [...agentList.querySelectorAll("input:checked:not(:disabled)")].map((input) => input.value);
}

function chosenMode() {
  return method.querySelector('[aria-pressed="true"]').dataset.mode;
}

function showMethod() {
  const linking = chosenAgents().length > 0;
  method.classList.toggle("disabled", !linking);
  element("method-hint").textContent = linking ? HINTS[chosenMode()] : HINTS.none;
}

function setMode(mode) {
  for (const button of method.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
  showMethod();
}

function filterAgents() {
  const looked = element("filter").value.trim().toLowerCase();
  let any = false;
  for (const row of agentList.querySelectorAll(".agent")) {
    row.hidden = !row.dataset.name.includes(looked);
    any ||= !row.hidden;
  }
  agentList.querySelector(".divider").hidden = looked !== "";
  agentList.querySelector(".none").hidden = any;
}

/** Installs with what was chosen. `skillChoice` is the agents and how, false for none, or null to leave it. */
function install(skillChoice) {
  steps.replaceChildren();
  element("failure").hidden = true;
  showEnd("Installing", []);
  showView(progress);
  const chosen = Object.fromEntries(Object.entries(switches).map(([name, input]) => [name, input.checked]));
  ask({ do: "install", workspace: element("workspace").value.trim(), ...chosen, skill: skillChoice });
}

function providerRow({ name, signedInWith, problem }) {
  const row = element("provider").content.firstElementChild.cloneNode(true);
  const signedIn = signedInWith !== null;
  row.classList.add(signedIn ? "is-done" : "is-noted");
  row.querySelector(".name").textContent = name;
  row.querySelector(".standing").textContent = signedIn ? `Signed in with ${signedInWith}` : "Not signed in";
  const said = row.querySelector(".problem");
  said.textContent = signedIn ? "" : (problem ?? "");
  said.title = said.textContent;
  said.hidden = signedIn || !problem;
  const signIn = row.querySelector(".sign-in");
  signIn.hidden = signedIn;
  signIn.addEventListener("click", () => ask({ do: "signIn" }));
  return row;
}

const shows = {
  ready(found) {
    element("version").textContent = found.version;
    if (found.installed) {
      const again = found.installed === found.version;
      element("lead").textContent = again
        ? `Version ${found.installed} is installed. Installing it again repairs it and applies what you choose here.`
        : `Version ${found.installed} is installed, and this replaces it with ${found.version}.`;
      element("lead").hidden = false;
      installWord = again ? "Install again" : "Update";
    }
    element("agents-install").textContent = installWord;
    element("workspace").value = found.workspace;
    const kept = found.workspaces.length > 0;
    element("workspace-group").hidden = kept;
    element("workspaces-kept").hidden = !kept;
    const folders = found.workspaces.map((folder) => {
      const item = document.createElement("li");
      item.textContent = folder;
      return item;
    });
    if (found.moreWorkspaces > 0) {
      const more = document.createElement("li");
      more.className = "more";
      more.textContent = `and ${found.moreWorkspaces} more`;
      folders.push(more);
    }
    element("workspaces").replaceChildren(...folders);
    for (const [name, input] of Object.entries(switches)) input.checked = found[name];
    holdProviders();
    skill.checked = found.skill;
    skillInstalled = found.skillInstalled;
    setMode(found.skillMode);
    nameInstall();
    showView(choices);
  },

  updating(found) {
    updating = true;
    adding = found.adding;
    element("version").textContent = found.version;
    element("in-use-back").textContent = "Cancel";
    showView(progress);
    if (adding) {
      document.title = "3D Modeling Setup";
      showEnd(`Installing ${adding}`, []);
      element("progress-lead").textContent = "3D Modeling starts again when it is done.";
    } else {
      showEnd("Updating 3D Modeling", []);
      element("progress-lead").textContent = found.installed
        ? `Version ${found.installed} is replaced with ${found.version}, and the app starts again when it is done.`
        : "";
    }
    element("progress-lead").hidden = element("progress-lead").textContent === "";
  },

  folder({ folder }) {
    element("workspace").value = folder;
  },

  downloading() {
    element("agents-loading-text").textContent = "Downloading Node.js for the skills CLI...";
  },

  agents({ agents }) {
    listed = agents;
    showAgents();
    element("agents-install").disabled = false;
  },

  noAgents({ text }) {
    element("agents-install").disabled = false;
    element("agents-loading").hidden = true;
    const failure = element("agents-failure");
    failure.textContent = `The agents couldn't be listed, so setup goes on without the skill. Opening setup again can install it later.\n\n${text}`;
    failure.hidden = false;
  },

  inUse({ runs, others, said }) {
    const have = runs + others === 1 ? "has" : "have";
    element("in-use-lead").textContent = `It is used by ${said}, which ${have} to end before it is replaced.`;
    element("in-use-waiting").hidden = true;
    element("in-use-wait").hidden = false;
    for (const id of ["in-use-back", "in-use-stop", "in-use-wait"]) element(id).disabled = false;
    showView(inUse);
    element("in-use-wait").focus();
  },

  back() {
    showView(choices);
  },

  started({ label }) {
    showView(progress);
    setStep("done");
    const step = element("step").content.firstElementChild.cloneNode(true);
    step.classList.add("is-working");
    step.querySelector(".label").textContent = label;
    steps.append(step);
    step.scrollIntoView({ block: "nearest" });
  },

  note({ text }) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = text;
    (steps.lastElementChild ?? steps).append(note);
    note.scrollIntoView({ block: "nearest" });
  },

  installed() {
    setStep("done");
  },

  checking() {
    element("providers-loading").hidden = false;
    element("providers-failure").hidden = true;
    element("check").disabled = true;
    showView(providersView);
  },

  providers({ providers }) {
    element("providers-loading").hidden = true;
    element("check").disabled = false;
    element("provider-list").replaceChildren(...providers.map(providerRow));
    element("continue").focus();
  },

  noProviders({ text }) {
    element("providers-loading").hidden = true;
    element("check").disabled = false;
    element("provider-list").replaceChildren();
    const failure = element("providers-failure");
    failure.textContent = `The tool couldn't say how the agent providers are signed in.\n\n${text}`;
    failure.hidden = false;
  },

  failed({ text }) {
    showView(progress);
    setStep("failed");
    const failure = element("failure");
    failure.textContent = text;
    failure.hidden = false;
    if (adding) showEnd(`${adding} wasn't installed`, ["close"]);
    else if (updating) showEnd("The update didn't finish", ["close"]);
    else showEnd("Setup didn't finish", ["close", "back"]);
    failure.scrollIntoView({ block: "nearest" });
  },
};

window.setup = {
  show(message) {
    shows[message.is](message);
  },
};

choices.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!skill.checked) {
    install(false);
    return;
  }
  showView(agentsView);
  if (listed === null) {
    element("agents-failure").hidden = true;
    element("agents-loading").hidden = false;
    element("agents-install").disabled = true;
    ask({ do: "agents" });
  }
});

agentsView.addEventListener("submit", (event) => {
  event.preventDefault();
  install(listed === null ? null : { agents: chosenAgents(), mode: chosenMode() });
});

skill.addEventListener("change", nameInstall);
for (const input of providerSwitches) input.addEventListener("change", holdProviders);
agentList.addEventListener("change", showMethod);
element("filter").addEventListener("input", filterAgents);
for (const button of method.querySelectorAll("button")) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}
element("agents-back").addEventListener("click", () => showView(choices));
element("browse").addEventListener("click", () => ask({ do: "browse" }));
element("in-use-wait").addEventListener("click", () => {
  element("in-use-wait").hidden = true;
  element("in-use-waiting").hidden = false;
  element("in-use-stop").focus();
  ask({ do: "wait" });
});
element("in-use-stop").addEventListener("click", () => {
  for (const id of ["in-use-back", "in-use-stop", "in-use-wait"]) element(id).disabled = true;
  ask({ do: "stop" });
});
element("in-use-back").addEventListener("click", () => {
  for (const id of ["in-use-back", "in-use-stop", "in-use-wait"]) element(id).disabled = true;
  ask({ do: "back" });
});
element("check").addEventListener("click", () => ask({ do: "check" }));
element("continue").addEventListener("click", () => {
  showView(done);
  // The app is back by the clock already, and the browser app that asked for the agent provider loads again.
  if (adding) {
    element("done-title").textContent = `${adding} is installed`;
    element("open").hidden = true;
    element("done-close").focus();
  } else {
    element("open").focus();
  }
});
element("open").addEventListener("click", () => ask({ do: "open" }));
element("close").addEventListener("click", () => ask({ do: "close" }));
element("done-close").addEventListener("click", () => ask({ do: "close" }));
element("back").addEventListener("click", () => showView(choices));

ask({ do: "ready" });
