# Vision

An expert in creating and editing 3D models.
It creates 3D models from a description and optional reference images or models.
There is a UX that lets you view what is being built, provide inputs, and steer the agent.

The primary of way of driving the tool is through an agent app like Claude Code or Codex.
You ask it to create a 3D model, and it calls the smart capability. 
It automatically opens up the app or embeds its work through an MCP app.
In the app, you can provide feedback at any time, even pointing to specific things on the model.

User Flows
1. User says that they want to create a 3D model in their agent session. If the app is not already open, it gets opened in the current working dir by default.
2. Choose a directory when starting it up or default to one within the current dir. The app shows you all the models that were genertaed by it in that dir.
3. When you open the model it shows you the render. It also automatically opens to your last viewed one
4. To edit, you can click and drag to make boxes to highlight things you want changed and then you type what the change you want is.
5. Then you hit submit, which takes a screenshot plus text for the model to then iterate on it
6. You can create new models. You type what you want and provide optional screenshots or point to existing models.
7. This by default will always try to resume the previous agent session when you are in a model, rather than having your edits be done in a new one. It also discourages you from changing providers if that would cause loss of the context from that session. However, the code creating the model should be structured such that someone could pick it back up.
8. All these changes can also be driven without the UX in the host session (like Claude Code). The UX is a thin wrapper around that. It can also be driven completely from the app by the user taking actions.

## Goals

- Has a dashboard where users can easily see and steer the 3D model being made.

## Non-Goals

- No pixel art, sound, etc. The tool is focused on creating 3D models.

## Principles

- The library is the tool. The CLI and any other surface are thin wrappers over it.
- Deterministic capabilities run with no model provider configured, and never refuse to load without one.
- The intelligence is behind an interface, so another implementation is a new module rather than a rewrite.
- The tool works on Windows, macOS, and Linux seamlessly.
- We do not use bun, prefer pnpm and Node.
