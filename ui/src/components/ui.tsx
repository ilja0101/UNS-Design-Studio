import type { ReactNode } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

/** Standard scrollable page frame with a title/subtitle header and an optional
 * actions slot — the layout every ported page shares. */
export function Page({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1600px] px-8 py-6">
        <div className="mb-5 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-fg">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-fg-muted">{subtitle}</p>}
          </div>
          {actions}
        </div>
        <div className="flex flex-col gap-5">{children}</div>
      </div>
    </div>
  );
}

export function Card({
  title,
  desc,
  icon,
  children,
  footer,
}: {
  title: string;
  desc?: string;
  icon?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface shadow-card">
      <header className="flex items-start gap-3 border-b border-border px-4 py-3">
        {icon && (
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
          {desc && <p className="mt-0.5 text-xs text-fg-muted">{desc}</p>}
        </div>
      </header>
      <div className="px-4 py-4">{children}</div>
      {footer && (
        <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          {footer}
        </footer>
      )}
    </section>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-fg-muted">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-fg-faint">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "h-9 w-full rounded-lg border border-border bg-bg px-2.5 text-sm text-fg outline-none focus:border-accent";

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "rounded-lg px-3.5 py-2 text-sm font-medium transition-tokens disabled:opacity-50",
        variant === "primary"
          ? "bg-accent text-accent-fg hover:bg-accent-hover"
          : "border border-border bg-surface text-fg hover:bg-surface-2",
      )}
    >
      {children}
    </button>
  );
}

export function Toggle({
  on,
  onChange,
  disabled,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cx(
        "relative h-6 w-11 shrink-0 rounded-full transition-tokens disabled:opacity-50",
        on ? "bg-accent" : "bg-surface-3",
      )}
    >
      <span
        className={cx(
          "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform",
          on ? "left-0.5 translate-x-5" : "left-0.5",
        )}
      />
    </button>
  );
}
