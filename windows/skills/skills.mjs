// The skills CLI's own library, which the Windows app runs on Node to list the agents and to install the Agent Skill
// for them. It is given a command, and JSON after it, and prints one line of JSON.

import { homedir } from "node:os";
import { join } from "node:path";

import { detectAgents, getSupportedAgents, installSkills, listSkills, removeSkills } from "skills";

const SKILL = "modeling-3d";
// The Windows app brings the skill up to date with itself, so the skills CLI isn't told of it to update it too.
const GLOBALLY = { scope: "global", lockfile: false, telemetry: false };
// The skills CLI's target for the shared folder that every agent sharing it reads.
const SHARED = "universal";

const supported = getSupportedAgents().filter((agent) => agent.globalSkillsDir !== null && agent.id !== SHARED);
const sharing = new Set(supported.filter((agent) => agent.universal).map((agent) => agent.id));

async function detected() {
  return new Set((await detectAgents()).agents.map((agent) => agent.id));
}

async function installedFor() {
  const { skills } = await listSkills({ scope: "global" });
  return skills.find((skill) => skill.name === SKILL)?.agents ?? [];
}

async function agents() {
  const found = await detected();
  return {
    home: homedir(),
    shared: join(homedir(), ".agents", "skills"),
    agents: supported.map((agent) => ({
      id: agent.id,
      name: agent.name,
      folder: agent.globalSkillsDir,
      shares: sharing.has(agent.id),
      detected: found.has(agent.id),
    })),
    installed: await installedFor(),
  };
}

/** Installs the skill from a folder for the shared folder and the agents chosen, and takes it from the others. */
async function install({ source, agents: chosen, mode }) {
  const found = await detected();
  // A sharing agent found here may read a folder of its own as well, which the skills CLI then links.
  const targets = [SHARED, ...[...sharing].filter((id) => found.has(id)), ...chosen];
  // A sharing agent's folder is the shared copy, which stays. The rest go first, since the skills CLI also takes the
  // shared copy away when no agent it finds is left using it.
  const dropped = (await installedFor()).filter((id) => !chosen.includes(id) && !sharing.has(id));
  const removed = dropped.length ? await removeSkills([SKILL], { ...GLOBALLY, agents: dropped }) : { failed: [] };
  const result = await installSkills(source, { ...GLOBALLY, skills: [SKILL], agents: targets, mode });
  const named = (ids) => supported.filter((agent) => ids.has(agent.id)).map((agent) => agent.name);
  return {
    // The ones chosen, then the sharing ones found here, then the rest that share.
    names: [
      ...named(new Set(chosen)),
      ...named(new Set([...sharing].filter((id) => found.has(id)))),
      ...named(new Set([...sharing].filter((id) => !found.has(id)))),
    ],
    installed: result.installed.map((target) => ({
      agent: target.agent,
      mode: target.mode,
      path: target.path,
      canonicalPath: target.canonicalPath ?? null,
    })),
    failed: [...result.failed, ...removed.failed].map((failure) => failure.message),
  };
}

async function remove() {
  // With the skills CLI's lock, for a skill it installed before the Windows app did.
  const { failed } = await removeSkills([SKILL], { scope: "global", telemetry: false });
  return { failed: failed.map((failure) => failure.message) };
}

const commands = { agents, install, remove };
const [command, given] = process.argv.slice(2);
if (!(command in commands)) {
  throw new Error(`Ask for one of: ${Object.keys(commands).join(", ")}.`);
}
const answer = await commands[command](given ? JSON.parse(given) : {});
process.stdout.write(`${JSON.stringify(answer)}\n`);
