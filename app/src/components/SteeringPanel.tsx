import { SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type Message = {
  from: "agent" | "you" | "status";
  text: string;
};

function Bubble({ from, text }: Message) {
  return (
    <li
      className={cn(
        "max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap",
        from === "you" && "self-end bg-primary text-primary-foreground",
        from === "agent" && "self-start bg-muted",
        from === "status" &&
          "self-center bg-destructive/10 text-xs text-destructive",
      )}
    >
      {text}
    </li>
  );
}

/** The conversation with the agent, and where the user steers it. */
export function SteeringPanel({
  messages,
  onSend,
}: {
  messages: Message[];
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLLIElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (text) {
      onSend(text);
      setDraft("");
    }
  };

  return (
    <section className="flex min-h-0 flex-col rounded-xl border bg-card">
      <header className="border-b px-4 py-3">
        <h2 className="text-sm font-medium">Steer</h2>
        <p className="text-xs text-muted-foreground">
          Point the agent somewhere else at any time.
        </p>
      </header>
      <ol className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-4">
        {messages.length === 0 && (
          <li className="m-auto text-center text-sm text-muted-foreground">
            Nothing yet. Say what you want built.
          </li>
        )}
        {messages.map((message, index) => (
          <Bubble key={index} {...message} />
        ))}
        <li ref={end} aria-hidden />
      </ol>
      <form onSubmit={submit} className="flex gap-2 border-t p-3">
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Make the legs longer..."
          aria-label="Message to the agent"
        />
        <Button type="submit" size="icon" aria-label="Send">
          <SendHorizontal />
        </Button>
      </form>
    </section>
  );
}
