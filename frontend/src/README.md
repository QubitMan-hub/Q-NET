# Frontend source

| File | What it does |
|---|---|
| `main.tsx` | Mounts the app. |
| `App.tsx` | Page layout: toolbar, canvas tabs, bottom dock and the right-hand Play / Details panel. Simple mode by default; **Expert** in the toolbar turns on the palette, protocol editor, step-by-step playback and the log tabs. |
| `store.ts` | Global state (zustand): the project, the simulation snapshot, selection, undo/redo, and every call that changes them. |
| `api.ts` | API client with two transports: HTTP to `qpv serve`, or the in-browser engine worker. |
| `pyworker.ts` | Web Worker that loads Pyodide, NumPy and the `qpvsim` package for the static build. |
| `editing.ts` | Undoable edits of the project document (add, duplicate and delete participants, states and links). |
| `types.ts` | TypeScript types for the project format and engine replies. |
| `format.ts` | Time and number formatting (the engine counts integer femtoseconds). |
| `glossary.ts` | One-sentence explanations of QPV concepts, used as tooltips. |
| `styles.css` | Design tokens and all styles, light and dark. |
| `components/` | Panels and canvases. See `components/README.md`. |
