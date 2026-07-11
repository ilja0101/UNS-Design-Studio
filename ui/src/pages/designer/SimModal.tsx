import { useState } from "react";
import { X } from "lucide-react";
import type { ProfileGroup, Sim, UnsTag } from "../../api";
import { Button, inputCls, cx } from "../../components/ui";

const HINTS: Record<string, string> = {
  oee: "Correlated with plant state machine. Degrades on fault, recovers automatically.",
  availability: "Drops sharply during fault, climbs during recovery.",
  boolean_running: "TRUE only when the plant is in Running state.",
  boolean_fault: "TRUE only during an active fault.",
  boolean_alarm: "TRUE during fault and recovery phases.",
  accumulator_good: "Monotonically increasing. Only advances when the plant is running.",
  accumulator_energy: "Increases proportionally to current power draw.",
  silo_level: "Drains during production. Auto-refills when low (truck arrival).",
  truck_id: "Cycles to a new truck ID on each silo refill event.",
  remaining_useful_life: "Counts down. Resets after a recovery / PM event.",
  vibration: "Rises as a fault approaches, drops after recovery.",
  motor_current: "Spikes during fault, normalises during recovery.",
  erp_order_id: "Cycles to a new order ID on batch change events.",
  order_status: "Progresses through Created → Released → In Progress → Completed → Closed.",
  default: "Gaussian walk. Configure base value, std deviation and bounds below.",
};

export function SimModal({
  tag,
  profiles,
  onClose,
  onSave,
}: {
  tag: UnsTag;
  profiles: ProfileGroup[];
  onClose: () => void;
  onSave: (sim: Sim | null) => void;
}) {
  const sim = tag.simulation ?? ({} as Sim);
  const [profile, setProfile] = useState(sim.profile ?? "");
  const [base, setBase] = useState(sim.base ?? 50);
  const [std, setStd] = useState(sim.std ?? 8);
  const [min, setMin] = useState(sim.min ?? 0);
  const [max, setMax] = useState(sim.max ?? 100);

  const hint = HINTS[profile] ?? (profile ? "Plant-state-aware: paused during fault, slower during recovery." : "");

  const submit = () => {
    if (!profile) return onSave(null);
    if (profile === "default") onSave({ profile, base, std, min, max });
    else onSave({ profile });
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="rise-in w-full max-w-md rounded-xl border border-border bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-fg">
            Simulation profile — <span className="text-accent">{tag.name}</span>
          </h3>
          <button onClick={onClose} className="text-fg-faint hover:text-fg">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3 px-4 py-4">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] font-medium text-fg-muted">
              Profile <span className="text-fg-faint">(optional — enables live simulation)</span>
            </span>
            <select className={inputCls} value={profile} onChange={(e) => setProfile(e.target.value)}>
              <option value="">None (static value)</option>
              {profiles.map((g) => (
                <optgroup key={g.group} label={g.group}>
                  {g.profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>

          {profile === "default" && (
            <div className="grid grid-cols-4 gap-2">
              {(
                [
                  ["Base", base, setBase],
                  ["Std", std, setStd],
                  ["Min", min, setMin],
                  ["Max", max, setMax],
                ] as const
              ).map(([label, val, setter]) => (
                <label key={label} className="flex flex-col gap-1">
                  <span className="text-[11px] text-fg-muted">{label}</span>
                  <input
                    type="number"
                    step="0.01"
                    className={cx(inputCls, "h-8")}
                    value={val}
                    onChange={(e) => setter(Number(e.target.value))}
                  />
                </label>
              ))}
            </div>
          )}

          {hint && (
            <div className="rounded-lg bg-surface-2 px-3 py-2 text-[11px] text-fg-muted">💡 {hint}</div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit}>Save</Button>
        </div>
      </div>
    </div>
  );
}
