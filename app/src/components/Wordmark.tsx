import { APP_NAME } from "@/lib/brand";
import { cn } from "@/lib/utils";

/** The app's name in the brand's type, with the light blue square where a period would be. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-baseline text-[14px]/4 font-semibold tracking-[-0.015em] whitespace-nowrap text-ink",
        className,
      )}
    >
      {APP_NAME}
      <span
        aria-hidden
        className="ml-[0.12em] inline-block size-[0.3em] shrink-0 bg-accent"
      />
    </span>
  );
}

/** The compact mark, for where the wordmark has no room: a line-drawn cube on an ink tile, with the square. */
export function AppMark({
  size = 20,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role="img"
      aria-label={APP_NAME}
      className={cn("block shrink-0", className)}
    >
      <rect width="64" height="64" rx="14" fill="#12161c" />
      <g
        transform="translate(9 9) scale(1.5)"
        fill="none"
        stroke="#eef2f6"
        strokeWidth="2.2"
        strokeLinejoin="miter"
      >
        <path d="M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z" />
        <path d="M3.5 7.25L12 12l8.5-4.75M12 12v9.5" />
      </g>
      <rect x="44" y="44" width="11" height="11" fill="#6ab3ee" />
    </svg>
  );
}
