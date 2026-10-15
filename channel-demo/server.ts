#!/usr/bin/env bun
import { join } from 'path'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import type { ServerWebSocket } from 'bun'

const PORT = 8788
const ORIGINS = new Set([`http://localhost:${PORT}`, `http://127.0.0.1:${PORT}`])
const pages = new Set<ServerWebSocket<unknown>>()

function show(from: 'you' | 'claude', text: string) {
  const data = JSON.stringify({ from, text })
  for (const page of pages) page.send(data)
}

const mcp = new Server(
  { name: 'channel-demo', version: '0.0.1' },
  {
    // The claude/channel capability is what makes Claude Code listen for this server's channel notifications.
    capabilities: { tools: {}, experimental: { 'claude/channel': {} } },
    // Claude Code hands this to Claude when the server connects.
    instructions:
      `Messages from the chat page arrive as <channel source="channel-demo">. ` +
      `The sender reads the page at http://localhost:${PORT}, not this terminal, so answer with the reply tool.`,
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'reply',
      description: 'Send a message to the chat page.',
      inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
    },
  ],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  if (req.params.name !== 'reply') throw new Error(`unknown tool: ${req.params.name}`)
  const { text } = req.params.arguments as { text: string }
  show('claude', text)
  return { content: [{ type: 'text', text: pages.size ? 'sent' : 'sent, but no chat page is open' }] }
})

await mcp.connect(new StdioServerTransport())

Bun.serve({
  port: PORT,
  hostname: '127.0.0.1',
  fetch(req, server) {
    const url = new URL(req.url)
    if (url.pathname === '/ws') {
      // Browsers let any website open a WebSocket to localhost, so only this page's own origin may type into the session.
      if (!ORIGINS.has(req.headers.get('origin') ?? '')) return new Response('forbidden', { status: 403 })
      if (server.upgrade(req)) return
      return new Response('upgrade failed', { status: 400 })
    }
    if (url.pathname === '/') return new Response(Bun.file(join(import.meta.dir, 'index.html')))
    return new Response('not found', { status: 404 })
  },
  websocket: {
    open: page => {
      pages.add(page)
    },
    close: page => {
      pages.delete(page)
    },
    message: (_, raw) => {
      const text = String(raw).trim()
      if (!text) return
      show('you', text)
      void mcp.notification({ method: 'notifications/claude/channel', params: { content: text } })
    },
  },
})

// stdout carries the MCP messages to Claude Code, so logs go to stderr.
process.stderr.write(`channel-demo: http://localhost:${PORT}\n`)
