import { useEffect, useState } from "react";
import { Vector3 } from "three";

import { ImageDialog, type ShownImage } from "@/components/ImageDialog";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { LoadingMark } from "@/components/ui/loading-mark";
import { Notice } from "@/components/ui/notice";
import {
  CHECK_GROUPS,
  checkModel,
  readCheck,
  type CheckResult,
  type ModelCheck,
  type ModelSummary,
} from "@/lib/api";
import { describe } from "@/lib/errors";
import { useModelImage } from "@/lib/images";
import { counted, dimensions } from "@/lib/stats";
import { timeOfDay } from "@/lib/time";
import { cn } from "@/lib/utils";

// How many of a check's lines show before the person asks for the rest.
const LINES_SHOWN = 4;

/** The model's latest check, read again whenever a new one is written, and a way to run the checks again. */
function useCheck(model: ModelSummary): {
  report: ModelCheck | null;
  error: string | null;
  checking: boolean;
  run: () => void;
} {
  const { name, checked } = model;
  const key = JSON.stringify([name, checked]);
  const [read, setRead] = useState<{
    key: string;
    report: ModelCheck | null;
    error: string | null;
  } | null>(null);
  // The model a check started here is running on, and why the last one it ran failed.
  const [checking, setChecking] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ name: string; text: string } | null>(
    null,
  );

  useEffect(() => {
    if (checked === null) {
      return;
    }
    let current = true;
    readCheck(name).then(
      (report) => current && setRead({ key, report, error: null }),
      (cause: unknown) =>
        current && setRead({ key, report: null, error: describe(cause) }),
    );
    return () => {
      current = false;
    };
  }, [name, checked, key]);

  const run = () => {
    setChecking(name);
    setFailed(null);
    // The new report shows once the model's summary says it was written.
    checkModel(name)
      .catch((cause: unknown) => setFailed({ name, text: describe(cause) }))
      .finally(() =>
        setChecking((current) => (current === name ? null : current)),
      );
  };

  const shown = read?.key === key ? read : null;
  return {
    report: shown?.report ?? null,
    error: failed?.name === name ? failed.text : (shown?.error ?? null),
    checking: checking === name,
    run,
  };
}

/** One of a check's renders, small, which opens large. */
function CheckRender({
  model,
  path,
  version,
  onOpen,
}: {
  model: string;
  path: string;
  version: string;
  onOpen: (image: ShownImage) => void;
}) {
  const { url } = useModelImage(model, path, version);
  const label = path.replace(/^checks\//, "");
  return (
    <li className="shrink-0">
      <button
        type="button"
        onClick={() => onOpen({ path, version })}
        aria-label={`Open ${label}`}
        title={label}
        className="block h-18 max-w-64 overflow-hidden rounded-md border border-line bg-panel p-0.5 hover:border-line-control"
      >
        {url ? (
          <img
            src={url}
            alt=""
            className="h-full rounded-sm bg-canvas object-contain"
          />
        ) : (
          <span className="block size-17 rounded-sm bg-field" />
        )}
      </button>
    </li>
  );
}

/** One check: its name and summary, its lines for each part measured, a few at first, and its renders. */
function Check({
  result,
  model,
  version,
  onOpen,
}: {
  result: CheckResult;
  model: string;
  version: string;
  onOpen: (image: ShownImage) => void;
}) {
  const [all, setAll] = useState(false);
  const lines = all ? result.lines : result.lines.slice(0, LINES_SHOWN);
  const hidden = result.lines.length - lines.length;
  return (
    <li className="flex flex-col gap-1 border-t border-line px-3 py-2 first:border-t-0">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <span
          className={cn(
            "mono-value",
            result.skipped ? "text-ink-muted" : "text-ink",
          )}
        >
          {result.name}
        </span>
        {result.skipped && (
          <span className="mono-annotation text-ink-muted">skipped</span>
        )}
      </div>
      <p className={cn(result.skipped && "text-ink-muted")}>{result.summary}</p>
      {lines.length > 0 && (
        <ul className="flex flex-col gap-0.5 mono-annotation text-ink-muted">
          {lines.map((line, index) => (
            <li key={index} className="wrap-break-word">
              {line}
            </li>
          ))}
        </ul>
      )}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setAll(true)}
          className="self-start text-label text-ink-muted underline decoration-line-control underline-offset-2 hover:text-ink"
        >
          {hidden} more
        </button>
      )}
      {result.files.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-2">
          {result.files.map((path) => (
            <CheckRender
              key={path}
              model={model}
              path={path}
              version={version}
              onOpen={onOpen}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/** What the report measured the model against: its budgets, or that it had none. */
function budgets(report: ModelCheck): string {
  const each = [
    report.max_triangles !== null &&
      counted(report.max_triangles, "triangle", "triangles"),
    report.max_draw_calls !== null &&
      counted(report.max_draw_calls, "draw call", "draw calls"),
    report.screen_size !== null &&
      `${report.screen_size[0]} to ${report.screen_size[1]} px on screen`,
  ].filter(Boolean);
  return each.length ? `Budgets: ${each.join(" · ")}` : "No budgets";
}

/**
 * The model's latest check: what it is, what it was measured against, and each check's findings and renders, by the
 * stage of the work each belongs to. Nothing passes or fails; the person, or the agent they ask, decides what matters.
 * Run checks checks the model again, against its own budgets.
 */
export function Checks({ model }: { model: ModelSummary }) {
  const { report, error, checking, run } = useCheck(model);
  const [opened, setOpened] = useState<ShownImage | null>(null);
  const working = model.status === "running";
  const changed =
    report !== null &&
    model.built !== null &&
    Date.parse(model.built) > Date.parse(report.checked);
  const groups = report
    ? CHECK_GROUPS.map(({ group, checks }) => ({
        group,
        results: report.checks.filter((result) => checks.includes(result.name)),
      })).filter(({ results }) => results.length > 0)
    : [];
  return (
    <div className="@container absolute inset-0 flex flex-col">
      <div className="flex h-13 shrink-0 items-center gap-2 px-3">
        <div className="flex h-7 min-w-0 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5">
          <Icon name="report" />
          <span className="mono-annotation whitespace-nowrap text-ink">
            {report
              ? `Checked ${timeOfDay(report.checked, true)}`
              : "Not checked yet"}
          </span>
          {changed && (
            <span className="truncate mono-annotation text-ink-muted">
              model.glb changed since
            </span>
          )}
        </div>
        <span className="flex-1" />
        <Button
          variant="secondary"
          size="sm"
          disabled={checking || working || !model.built}
          title={
            working
              ? "The agent checks it as it finishes. Run the checks yourself once the run ends."
              : "Check model.glb against the model's own budgets"
          }
          onClick={run}
        >
          {checking ? <LoadingMark /> : <Icon name="report" />}
          {checking ? "Checking" : "Run checks"}
        </Button>
      </div>
      {error && <Notice className="mx-3 mb-2 shrink-0">{error}</Notice>}
      {report ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          <div className="mb-3 flex flex-wrap gap-x-3 gap-y-0.5 mono-annotation text-ink-muted">
            <span>{dimensions(new Vector3(...report.dimensions))}</span>
            <span>{counted(report.triangles, "triangle", "triangles")}</span>
            <span>
              {counted(report.mesh_objects, "mesh object", "mesh objects")}
            </span>
            <span>{counted(report.materials, "material", "materials")}</span>
            <span>{budgets(report)}</span>
          </div>
          {groups.map(({ group, results }) => (
            <section key={group} className="mb-3">
              <h3 className="mb-1 text-label text-ink-muted">{group}</h3>
              <ol className="rounded-md border border-line bg-panel">
                {results.map((result) => (
                  <Check
                    key={result.name}
                    result={result}
                    model={model.name}
                    version={report.checked}
                    onOpen={setOpened}
                  />
                ))}
              </ol>
            </section>
          ))}
        </div>
      ) : (
        !error && (
          <p className="mt-8 px-6 text-center text-ink-muted">
            {model.checked === null
              ? `${model.name} hasn't been checked yet. The agent checks it as it finishes, or run the checks now.`
              : "Reading the check..."}
          </p>
        )
      )}
      <ImageDialog
        model={model.name}
        image={opened}
        onClose={() => setOpened(null)}
      />
    </div>
  );
}
