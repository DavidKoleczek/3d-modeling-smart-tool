import { Box } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ModelList, ModelMenu } from "@/components/ModelList";
import { SteeringPanel, type Message } from "@/components/SteeringPanel";
import { Viewport } from "@/components/Viewport";
import { agentMessages, describe, steer } from "@/lib/api";
import { onDisplayMode } from "@/lib/host";
import { useModels } from "@/lib/models";
import { cn } from "@/lib/utils";

const POLL_MS = 1000;

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [fullscreen, setFullscreen] = useState(false);
  const { listing, model, error, pick } = useModels();

  useEffect(
    () => onDisplayMode((mode) => setFullscreen(mode === "fullscreen")),
    [],
  );

  // A host pushes only what opened the view, so the agent's later messages come from polling the server.
  useEffect(() => {
    let shown = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const fresh = await agentMessages(shown);
        shown += fresh.length;
        if (fresh.length > 0) {
          setMessages((previous) => [
            ...previous,
            ...fresh.map((text): Message => ({ from: "agent", text })),
          ]);
        }
      } catch (cause) {
        setMessages((previous) => [
          ...previous,
          {
            from: "status",
            text: `Stopped listening for the agent: ${describe(cause)}`,
          },
        ]);
        return;
      }
      if (!stopped) {
        timer = setTimeout(poll, POLL_MS);
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);

  const send = useCallback(async (text: string) => {
    setMessages((previous) => [...previous, { from: "you", text }]);
    try {
      await steer(text);
    } catch (cause) {
      setMessages((previous) => [
        ...previous,
        { from: "status", text: `Not delivered: ${describe(cause)}` },
      ]);
    }
  }, []);

  const picker = { listing, selected: model?.name ?? null, onSelect: pick };

  return (
    <div
      className={cn(
        "flex flex-col gap-3 bg-background p-3 font-sans text-foreground",
        fullscreen ? "h-dvh" : "h-[560px]",
      )}
    >
      <header className="flex items-center gap-2">
        <Box className="size-5 text-primary" />
        <h1 className="font-heading text-base font-semibold">Modeling 3D</h1>
        <ModelMenu {...picker} className="ml-auto lg:hidden" />
      </header>
      <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-3 md:grid-cols-[minmax(0,1fr)_20rem] md:grid-rows-1 lg:grid-cols-[16rem_minmax(0,1fr)_20rem]">
        <ModelList {...picker} error={error} className="hidden lg:flex" />
        <Viewport listing={listing} model={model} />
        <SteeringPanel messages={messages} onSend={send} />
      </main>
    </div>
  );
}

export default App;
