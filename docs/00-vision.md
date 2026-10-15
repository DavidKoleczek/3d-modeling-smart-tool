# Vision

An expert in creating and editing 3D models.
It creates 3D models from a description and optional reference images or models.
There is a UX that lets you view what is being built, provide inputs, and steer the agent.

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
