import { useEffect, useMemo, useRef, useState } from "react";
import { useStore, type ConsoleEntry } from "../store";
import { api } from "../api";
import { Icon } from "./ui";

// The engine's command catalog drives everything here: groups, one-click starters and result views.
type CommandInfo = { name: string; usage: string; help: string; aliases: string[]; category: string; starter?: string | null };

const COLLAPSE_AT = 14;

function needsArgs(c: CommandInfo) {
  return /<[^>]+>/.test(c.usage.replace(/\[[^\]]*\]/g, ""));
}

function HelpResult({ data, onPick }: { data: CommandInfo[]; onPick: (c: CommandInfo) => void }) {
  const [all, setAll] = useState(false);
  const groups = new Map<string, CommandInfo[]>();
  for (const c of data) groups.set(c.category, [...(groups.get(c.category) ?? []), c]);
  const entries = Array.from(groups.entries());
  return (
    <div className="cx-help">
      <p className="cx-help-intro">Click a command to use it. The full list is also in the guide on the right.</p>
      {(all ? entries : entries.slice(0, 2)).map(([cat, cmds]) => (
        <div key={cat}>
          <h5>{cat}</h5>
          {cmds.map((c) => (
            <button key={c.name} className="cx-help-row" onClick={() => onPick(c)}>
              <code>{c.usage}</code><span>{c.help}</span>
            </button>
          ))}
        </div>
      ))}
      {entries.length > 2 && <button className="cx-more" onClick={() => setAll(!all)}>{all ? "Show less" : `Show all ${data.length} commands`}</button>}
    </div>
  );
}

function DecisionResult({ d }: { d: any }) {
  return (
    <div className="cx-decision">
      <div className={`cx-verdict ${d.outcome}`}>{d.summary}</div>
      <ul>{(d.verifiers ?? []).map((v: any) => (
        <li key={v.id}><b>{v.id}</b> {v.verdict ? `${v.verdict}ed` : v.status}{v.reason ? `: ${v.reason}` : ""}</li>
      ))}</ul>
    </div>
  );
}

function Entry({ e, onRerun, onPick }: { e: ConsoleEntry; onRerun: (cmd: string) => void; onPick: (c: CommandInfo) => void }) {
  const [open, setOpen] = useState(false);
  const isHelp = e.status === "ok" && e.view === "help" && Array.isArray(e.data);
  const isDecision = e.status === "ok" && e.view === "decision" && e.data?.summary;
  const lines = e.text.split("\n");
  const long = lines.length > COLLAPSE_AT;
  const shown = long && !open ? lines.slice(0, COLLAPSE_AT).join("\n") : e.text;
  return (
    <div className={`cx-entry ${e.status}`}>
      <div className="cx-asked">
        <span className="cx-chevron" aria-hidden><Icon.chevron /></span>
        <button className="cx-cmd" title="Run again" onClick={() => onRerun(e.cmd)}>{e.cmd}</button>
        <span className="cx-status" role="status">
          {e.status === "running" && <span className="muted">Working…</span>}
          {e.status === "ok" && <><span className="cx-ok"><Icon.check /></span>Done</>}
          {e.status === "error" && <><span className="cx-err"><Icon.alert /></span>Couldn’t do that</>}
        </span>
      </div>
      {isHelp && <div className="cx-result"><HelpResult data={e.data} onPick={onPick} /></div>}
      {isDecision && <div className="cx-result"><DecisionResult d={e.data} /></div>}
      {e.status !== "running" && !isHelp && !isDecision && (
        <div className="cx-result">
          <pre>{shown}</pre>
          {e.status === "error" && !/help/.test(e.text) && <div className="cx-hint">Type <b>help</b> to see what you can do.</div>}
          {long && (
            <button className="cx-more" onClick={() => setOpen(!open)}>
              {open ? "Show less" : `Show all ${lines.length} lines`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function ConsolePanel() {
  const log = useStore((s) => s.consoleLog);
  const exec = useStore((s) => s.consoleExec);
  const clear = useStore((s) => s.clearConsole);
  const catalog: CommandInfo[] = useStore((s) => s.meta?.console_commands ?? []);
  const [line, setLine] = useState("");
  const [hist, setHist] = useState<string[]>([]);
  const [hi, setHi] = useState(-1);
  const [comps, setComps] = useState<string[]>([]);
  const out = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (out.current) out.current.scrollTop = out.current.scrollHeight; }, [log]);

  const groups = useMemo(() => {
    const m = new Map<string, CommandInfo[]>();
    for (const c of catalog) m.set(c.category, [...(m.get(c.category) ?? []), c]);
    return Array.from(m.entries());
  }, [catalog]);

  const first = line.trim().split(/\s+/)[0]?.toLowerCase() ?? "";
  const typed = catalog.find((c) => c.name === first || c.aliases.includes(first));

  const run = async (cmd: string) => {
    const l = cmd.trim();
    if (!l) return;
    setHist((h) => [...h.filter((x) => x !== l), l]);
    setHi(-1);
    setLine("");
    setComps([]);
    await exec(l);
    input.current?.focus();
  };
  const pick = (c: CommandInfo) => {
    if (needsArgs(c)) {
      setLine(`${c.name} `);
      input.current?.focus();
    } else run(c.name);
  };
  const complete = async () => {
    const opts = await api.complete(line);
    if (opts.length === 1) {
      const parts = line.split(" ");
      parts[parts.length - 1] = opts[0];
      setLine(parts.join(" ") + " ");
      setComps([]);
    } else setComps(opts.slice(0, 24));
  };

  return (
    <div className="cx">
      <div className="cx-main">
        <div className="cx-log" ref={out} data-testid="console-out" aria-live="polite">
          {log.length === 0 ? (
            <div className="cx-welcome">
              <h4>Ask the simulation</h4>
              <p>Commands run against the live engine, exactly like the buttons above. Start with one of these, or type your own below.</p>
              <div className="cx-starters">
                {catalog.filter((c) => c.starter).map((c) => (
                  <button key={c.name} className="cx-chip" onClick={() => run(c.name)}>
                    {c.starter}<code>{c.name}</code>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            log.map((e) => <Entry key={e.id} e={e} onRerun={run} onPick={pick} />)
          )}
        </div>
        {comps.length > 0 && (
          <div className="cx-comps">
            {comps.map((c) => (
              <button key={c} onClick={() => {
                const parts = line.split(" ");
                parts[parts.length - 1] = c;
                setLine(parts.join(" ") + " ");
                setComps([]);
                input.current?.focus();
              }}>{c}</button>
            ))}
          </div>
        )}
        <div className="cx-usage" aria-live="polite">
          {typed ? <><code>{typed.usage}</code><span>{typed.help}</span></>
            : <span>Tab completes names · ↑ and ↓ recall earlier commands · times are in nanoseconds</span>}
        </div>
        <form className="cx-input" onSubmit={(e) => { e.preventDefault(); run(line); }}>
          <span className="cx-chevron" aria-hidden><Icon.chevron /></span>
          <input ref={input} value={line} onChange={(e) => { setLine(e.target.value); setComps([]); }}
            aria-label="Console command" spellCheck={false} autoComplete="off" data-testid="console-input"
            placeholder="Type a command, for example run, step or decision"
            onKeyDown={(e) => {
              if (e.key === "Tab") { e.preventDefault(); complete(); }
              else if (e.key === "ArrowUp" && hist.length) { e.preventDefault(); const n = hi < 0 ? hist.length - 1 : Math.max(0, hi - 1); setHi(n); setLine(hist[n]); }
              else if (e.key === "ArrowDown" && hi >= 0) { e.preventDefault(); const n = hi + 1; if (n >= hist.length) { setHi(-1); setLine(""); } else { setHi(n); setLine(hist[n]); } }
              else if (e.key === "Escape") { setLine(""); setComps([]); }
            }} />
          <button type="submit" className="btn primary" disabled={!line.trim()}>Run command</button>
        </form>
      </div>
      <aside className="cx-guide" aria-label="Command guide">
        <div className="cx-guide-head">
          <span className="grow">Command guide</span>
          {log.length > 0 && <button className="btn ghost" onClick={clear}>Clear</button>}
        </div>
        <div className="cx-guide-body">
          {groups.map(([cat, cmds]) => (
            <div key={cat} className="cx-group">
              <h5>{cat}</h5>
              {cmds.map((c) => (
                <button key={c.name} className="cx-item" title={`${c.usage}\n${c.help}`} onClick={() => pick(c)}>
                  <code>{c.name}</code><span>{c.help}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
