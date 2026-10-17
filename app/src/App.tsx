import { Box } from "lucide-react";
import { useEffect, useState } from "react";

import { ActivityPanel } from "@/components/ActivityPanel";
import { ModelList, ModelMenu } from "@/components/ModelList";
import { NewModel } from "@/components/NewModel";
import { Viewport } from "@/components/Viewport";
import { onDisplayMode } from "@/lib/host";
import { useModels } from "@/lib/models";
import { cn } from "@/lib/utils";

function App() {
  const [fullscreen, setFullscreen] = useState(false);
  const [creating, setCreating] = useState(false);
  const { listing, model, error, pick } = useModels();

  useEffect(
    () => onDisplayMode((mode) => setFullscreen(mode === "fullscreen")),
    [],
  );

  const select = (name: string) => {
    setCreating(false);
    void pick(name);
  };
  const picker = {
    listing,
    selected: creating ? null : (model?.name ?? null),
    onSelect: select,
    onNew: () => setCreating(true),
    creating,
  };
  const models = listing?.models ?? [];

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
        {creating ? (
          <NewModel
            models={models}
            onCreated={select}
            onCancel={() => setCreating(false)}
          />
        ) : (
          <ActivityPanel model={model} models={models} />
        )}
      </main>
    </div>
  );
}

export default App;
