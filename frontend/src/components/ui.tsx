import { useEffect, useState, type ReactNode } from "react";

// Inputs commit on Enter or blur, so each edit produces one undo step and one
// engine reset rather than one per keystroke.

export function Field({ label, children, stack, title }: { label: string; children: ReactNode; stack?: boolean; title?: string }) {
  return (
    <div className={`field${stack ? " stack" : ""}`} title={title}>
      <label>{label}</label>
      {children}
    </div>
  );
}

export function TextInput({ value, onCommit, code, placeholder, invalid, ariaLabel }: {
  value: string; onCommit: (v: string) => void; code?: boolean; placeholder?: string; invalid?: boolean; ariaLabel?: string;
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => { if (v !== value) onCommit(v); };
  return (
    <input className={`input${code ? " code" : ""}${invalid ? " invalid" : ""}`} value={v} placeholder={placeholder}
      aria-label={ariaLabel} spellCheck={false}
      onChange={(e) => setV(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setV(value); }} />
  );
}

export function TextArea({ value, onCommit, code, rows = 3 }: { value: string; onCommit: (v: string) => void; code?: boolean; rows?: number }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <textarea className={`textarea${code ? " code" : ""}`} rows={rows} value={v} spellCheck={false}
      onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onCommit(v)} />
  );
}

export function NumberInput({ value, onCommit, step, min, max, ariaLabel, allowNull }: {
  value: number | null; onCommit: (v: number | null) => void; step?: number; min?: number; max?: number; ariaLabel?: string; allowNull?: boolean;
}) {
  const shown = value === null || value === undefined ? "" : String(value);
  const [v, setV] = useState(shown);
  useEffect(() => setV(shown), [shown]);
  const parsed = v.trim() === "" ? null : Number(v);
  const invalid = (parsed === null && !allowNull) || (parsed !== null && (!Number.isFinite(parsed) ||
    (min !== undefined && parsed < min) || (max !== undefined && parsed > max)));
  const commit = () => { if (!invalid && v !== shown) onCommit(parsed); };
  return (
    <input className={`input code${invalid ? " invalid" : ""}`} value={v} inputMode="decimal" aria-label={ariaLabel}
      placeholder={allowNull ? "auto" : undefined}
      onChange={(e) => setV(e.target.value)} onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setV(shown);
        if ((e.key === "ArrowUp" || e.key === "ArrowDown") && step && parsed !== null) {
          e.preventDefault();
          const n = +(parsed + (e.key === "ArrowUp" ? step : -step)).toFixed(10);
          setV(String(n));
          onCommit(n);
        }
      }} />
  );
}

export function Select<T extends string>({ value, options, onChange, ariaLabel }: {
  value: T; options: (T | { value: T; label: string })[]; onChange: (v: T) => void; ariaLabel?: string;
}) {
  return (
    <select className="select" value={value} aria-label={ariaLabel} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => {
        const opt = typeof o === "string" ? { value: o, label: o } : o;
        return <option key={opt.value} value={opt.value}>{opt.label}</option>;
      })}
    </select>
  );
}

export function Check({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="check"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>
  );
}

export function Section({ title, aside, children }: { title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="section">
      <h3><span className="grow">{title}</span>{aside}</h3>
      {children}
    </div>
  );
}

const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
export const Icon = {
  play: () => <svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" fill="currentColor" /></svg>,
  pause: () => <svg viewBox="0 0 16 16"><path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor" /></svg>,
  step: () => <svg viewBox="0 0 16 16"><path d="M3 2.5v11l7-5.5z" fill="currentColor" /><path d="M12 2.5v11" {...P} strokeWidth={2} /></svg>,
  end: () => <svg viewBox="0 0 16 16"><path d="M2 2.5v11l6-5.5zM8 2.5v11l6-5.5z" fill="currentColor" /></svg>,
  reset: () => <svg viewBox="0 0 16 16"><path d="M3 8a5 5 0 1 0 1.6-3.7M3 2.5v3h3" {...P} /></svg>,
  undo: () => <svg viewBox="0 0 16 16"><path d="M5 4 2 7l3 3M2.5 7H10a3.5 3.5 0 0 1 0 7H7" {...P} /></svg>,
  redo: () => <svg viewBox="0 0 16 16"><path d="m11 4 3 3-3 3M13.5 7H6a3.5 3.5 0 0 0 0 7h3" {...P} /></svg>,
  open: () => <svg viewBox="0 0 16 16"><path d="M2 4.5V13h12V6H8L6.5 4.5z" {...P} /></svg>,
  save: () => <svg viewBox="0 0 16 16"><path d="M8 2v8m0 0-3-3m3 3 3-3M3 12.5h10" {...P} /></svg>,
  layout: () => <svg viewBox="0 0 16 16"><path d="M2.5 3h4v4h-4zM9.5 9h4v4h-4zM6.5 5h3v4" {...P} /></svg>,
  fit: () => <svg viewBox="0 0 16 16"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" {...P} /></svg>,
  trash: () => <svg viewBox="0 0 16 16"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 9h5.6l.7-9" {...P} /></svg>,
  plus: () => <svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" {...P} /></svg>,
  copy: () => <svg viewBox="0 0 16 16"><path d="M5.5 5.5h8v8h-8zM2.5 10.5v-8h8" {...P} /></svg>,
  theme: () => <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5" {...P} /><path d="M8 2.5a5.5 5.5 0 0 0 0 11z" fill="currentColor" /></svg>,
};

export function Brand() {
  return (
    <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden>
      <path d="M16 30 L2 16 L16 2 L30 16 Z" fill="none" stroke="var(--quantum)" strokeWidth="2.5" />
      <path d="M2 16 H30" stroke="var(--rule-strong)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="3" fill="var(--ink)" />
    </svg>
  );
}
