import { useEffect, useState } from "react";

import { readToolCall, type ToolCall } from "@/lib/api";
import { describe } from "@/lib/errors";

// Enough for the steps someone opens while reading back through a model's activity.
const CACHED = 64;

const cache = new Map<string, Promise<ToolCall>>();

/** A tool call in full, read once for each `version` of it, such as before and after it finished. */
function readCall(
  model: string,
  runId: string,
  callId: string,
  version: string,
): Promise<ToolCall> {
  const key = JSON.stringify([model, runId, callId, version]);
  let call = cache.get(key);
  if (!call) {
    call = readToolCall(model, runId, callId);
    // A failed read is tried again next time.
    call.catch(() => cache.delete(key));
    cache.set(key, call);
    for (const old of cache.keys()) {
      if (cache.size <= CACHED) {
        break;
      }
      cache.delete(old);
    }
  }
  return call;
}

/** The tool call `callId` of run `runId` on model `model` in full, once read, or why it could not be. */
export function useToolCall(
  model: string,
  runId: string,
  callId: string,
  version: string,
): { call: ToolCall | null; error: string | null } {
  const [loaded, setLoaded] = useState<{
    key: string;
    call: ToolCall | null;
    error: string | null;
  } | null>(null);
  const key = JSON.stringify([model, runId, callId, version]);

  useEffect(() => {
    let current = true;
    readCall(model, runId, callId, version).then(
      (call) => current && setLoaded({ key, call, error: null }),
      (cause: unknown) =>
        current && setLoaded({ key, call: null, error: describe(cause) }),
    );
    return () => {
      current = false;
    };
  }, [model, runId, callId, version, key]);

  return loaded?.key === key
    ? { call: loaded.call, error: loaded.error }
    : { call: null, error: null };
}
