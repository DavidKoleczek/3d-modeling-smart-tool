import { clsx, type ClassValue } from "clsx";
import type { KeyboardEvent } from "react";
import { extendTailwindMerge } from "tailwind-merge";

// Without these, `text-body` reads as a text color and `cn` drops it beside `text-ink`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["display", "title", "body", "label", "caption"] },
    classGroups: { "font-size": ["mono-value", "mono-annotation"] },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Submit on Enter, and leave Shift+Enter and an input method's Enter to the text. */
export function submitsOnEnter(submit: () => void) {
  return (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      submit();
    }
  };
}

/** Put `text` on the clipboard; true when it got there. A host may not let a sandboxed view write it directly. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.cssText = "position: fixed; opacity: 0;";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    return copied;
  }
}
