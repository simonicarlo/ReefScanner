import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";

/** Tiny classname joiner. A dependency for this would be silly. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "quiet";
  size?: "sm" | "md";
};

export function Button({
  variant = "quiet",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-[3px] border font-medium",
        "transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
        variant === "primary" &&
          "border-signal/60 bg-signal/15 text-signal hover:bg-signal/25",
        variant === "danger" &&
          "border-reject/50 bg-reject/10 text-reject hover:bg-reject/20",
        variant === "ghost" &&
          "border-transparent text-dim hover:border-rule hover:text-read",
        variant === "quiet" &&
          "border-rule bg-panel-hi text-read hover:border-rule-hi hover:bg-rule/40",
        className,
      )}
    />
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
    <label className="block">
      <span className="legend block mb-1.5">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "w-full rounded-[3px] border border-rule bg-abyss/60 px-2.5 py-1.5",
        "text-sm text-read placeholder:text-faint",
        "focus:border-signal/60 focus:outline-none",
        className,
      )}
    />
  );
}

/** Status pill. Colour is the whole message, so it stays sparing. */
export function Tag({
  tone = "neutral",
  children,
  className,
}: {
  tone?: "neutral" | "signal" | "reject" | "hedge" | "dim";
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-[3px] border px-1.5 py-0.5",
        "font-mono text-[11px] uppercase tracking-wider",
        tone === "signal" && "border-signal/40 bg-signal/10 text-signal",
        tone === "reject" && "border-reject/40 bg-reject/10 text-reject",
        tone === "hedge" && "border-hedge/40 bg-hedge/10 text-hedge",
        tone === "dim" && "border-rule bg-hull text-faint",
        tone === "neutral" && "border-rule-hi bg-panel-hi text-dim",
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A labelled number. The panel's basic unit of information. */
export function Readout({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "signal" | "dim";
}) {
  return (
    <div>
      <div className="legend">{label}</div>
      <div
        className={cx(
          "tabular mt-0.5 text-sm",
          tone === "signal" && "text-signal",
          tone === "dim" && "text-faint",
          !tone && "text-read",
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="panel flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="text-lg text-dim">{title}</div>
      {children && <div className="max-w-md text-sm text-faint">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-[3px] border border-reject/40 bg-reject/10 px-3 py-2 text-sm text-reject">
      {message}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-8 text-sm text-faint">
      <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-signal" />
      {label}…
    </div>
  );
}
