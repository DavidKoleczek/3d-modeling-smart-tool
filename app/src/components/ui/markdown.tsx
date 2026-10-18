import { useRef, useState, type ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { app } from "@/lib/host";
import { cn, copyText } from "@/lib/utils";

function CodeBlock({ children }: ComponentProps<"pre">) {
  const block = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="group/code relative mb-2 last:mb-0">
      <pre
        ref={block}
        className="overflow-x-auto rounded-md border border-line bg-field px-2.5 py-2 font-mono text-label/4.5 whitespace-pre [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0 [&>code]:font-normal"
      >
        {children}
      </pre>
      <Button
        variant="secondary"
        size="sm"
        icon
        aria-label={copied ? "Copied" : "Copy"}
        title={copied ? "Copied" : "Copy"}
        onClick={async () => {
          if (await copyText(block.current?.textContent ?? "")) {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }
        }}
        className="absolute top-1 right-1 opacity-0 group-hover/code:opacity-100 focus-visible:opacity-100"
      >
        <Icon name={copied ? "check" : "copy"} />
      </Button>
    </div>
  );
}

/** Opens through the host, since the view's sandbox cannot navigate. */
function Link({ href, children }: ComponentProps<"a">) {
  return (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        if (href) {
          void app.openLink({ url: href });
        }
      }}
      className="text-accent-ink underline underline-offset-2"
    >
      {children}
    </a>
  );
}

const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h3 className="mt-3 mb-1 text-[15px]/5.5 font-semibold first:mt-0">
      {children}
    </h3>
  ),
  h2: ({ children }) => (
    <h4 className="mt-3 mb-1 font-semibold first:mt-0">{children}</h4>
  ),
  h3: ({ children }) => (
    <h5 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h5>
  ),
  h4: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  h5: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  h6: ({ children }) => (
    <h6 className="mt-2 mb-1 text-label font-semibold first:mt-0">
      {children}
    </h6>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children, className }) => (
    <ul
      className={cn(
        "mb-2 list-disc pl-4.5 last:mb-0",
        className?.includes("contains-task-list") && "list-none pl-0",
      )}
    >
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal pl-4.5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="my-0.5 marker:text-ink-muted">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  del: ({ children }) => <del className="text-ink-muted">{children}</del>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-line-control pl-2.5 text-ink-muted last:mb-0">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded-sm border border-line bg-field px-1 mono-value">
      {children}
    </code>
  ),
  pre: CodeBlock,
  a: Link,
  // The view's CSP refuses images from anywhere, so one shows as a link with its alt text.
  img: ({ src, alt }) =>
    typeof src === "string" ? <Link href={src}>{alt || src}</Link> : null,
  hr: () => <hr className="my-3 border-line" />,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="border-collapse text-label font-normal">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-line-control py-1 pr-4 text-left font-medium text-ink-muted">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-line py-1 pr-4">{children}</td>
  ),
  input: ({ checked }) => (
    <input
      type="checkbox"
      checked={checked}
      readOnly
      disabled
      className="mr-1.5 align-middle accent-(--accent)"
    />
  ),
};

/** What an agent wrote, rendered as Markdown with GitHub's extensions; raw HTML in it is left out. */
export function Markdown({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 wrap-break-word text-ink", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={COMPONENTS}
        skipHtml
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
