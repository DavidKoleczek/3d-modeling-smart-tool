import { useEffect, useState } from "react";

const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const clock = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});
const clockSeconds = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** How long ago `iso` was, such as "5 minutes ago", or "just now" within the last minute. */
export function ago(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((Date.parse(iso) - now) / 1000);
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) {
      return format.format(Math.round(seconds / size), unit);
    }
  }
  return "just now";
}

/** A span of seconds as the activity shows one, such as "45s" or "3m 5s". */
export function duration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

/** The span between two times, to a tenth of a second under ten seconds, such as "<0.1s", "0.2s", "41s", or "1m 50s". */
export function between(from: string, to: string | number): string {
  const end = typeof to === "number" ? to : Date.parse(to);
  const seconds = Math.max(0, (end - Date.parse(from)) / 1000);
  if (seconds < 0.05) {
    return "<0.1s";
  }
  return seconds < 10
    ? `${seconds.toFixed(1)}s`
    : duration(Math.round(seconds));
}

/** The time of day, such as "14:02" or "2:02 PM", in the person's own format; `seconds` adds them. */
export function timeOfDay(iso: string, seconds = false): string {
  return (seconds ? clockSeconds : clock).format(Date.parse(iso));
}

/** Now, ticking every second while `ticking`, for elapsed times that count up. */
export function useNow(ticking = true): number {
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (!ticking) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);

  return now;
}

/** How long since `iso` until now, counting up each second, such as "2m 14s". */
export function useElapsed(iso: string): string {
  const now = useNow();
  return duration(Math.max(0, Math.round((now - Date.parse(iso)) / 1000)));
}

/** Whether `active` has held for `ms`, so a quick load shows nothing rather than flashing a message. */
export function useDelayed(active: boolean, ms = 300): boolean {
  const [late, setLate] = useState(false);

  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = setTimeout(() => setLate(true), ms);
    return () => {
      clearTimeout(timer);
      setLate(false);
    };
  }, [active, ms]);

  return active && late;
}
