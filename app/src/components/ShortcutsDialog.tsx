import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";

const SHORTCUTS: [string[], string][] = [
  [["F"], "Fit the model"],
  [["G"], "Grid"],
  [["W"], "Wireframe"],
  [["D"], "Dimensions"],
  [["M"], "Mark up what to change"],
  [["1", "2"], "3D or Renders"],
  [["Left", "Right"], "The render before or after"],
  [["["], "Your models"],
  [["]"], "Activity"],
  [["N"], "New model"],
  [["/"], "Search models"],
  [["?"], "This list"],
  [["Esc"], "Close, or stop marking"],
];

/** Every key the app answers to. */
export function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Keyboard shortcuts" className="sm:max-w-90">
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 px-5 pt-4 pb-5">
          {SHORTCUTS.map(([keys, action]) => (
            <div key={action} className="contents">
              <dt className="flex gap-1">
                {keys.map((key) => (
                  <Kbd key={key}>{key}</Kbd>
                ))}
              </dt>
              <dd>{action}</dd>
            </div>
          ))}
        </dl>
        <p className="px-5 pb-5 text-caption text-ink-muted">
          Single keys act only when you are not typing in a field.
        </p>
      </DialogContent>
    </Dialog>
  );
}
