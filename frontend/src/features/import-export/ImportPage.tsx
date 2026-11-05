import { FileDrop } from "@/components/ui";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { faFileImport } from "@fortawesome/free-solid-svg-icons";
import { AppLink, urls } from "@/app/links";
import { Icon } from "@/components/Icon";
import { useToast } from "@/app/toasts";
import { requestJson } from "@/api/client";
import { errorMessage } from "@/api/errors";
import { previewImport, type ImportPreview } from "./preview";
import { useAllProjects, useContexts } from "@/api/meta";
import { useInvalidate } from "@/api/sync";
import { classifyMessage, isFinal, parseSseBuffer, projectProgress, succeeded, type LogKind } from "./importStream";
import "./import.css";

interface LogLine {
  id: number;
  text: string;
  kind: LogKind;
}

/* Import (core/templates/core/import.html + stream_server_responses.js):
   upload the file with its options, then follow the import live. */
export default function ImportPage() {
  const toast = useToast();
  const invalidate = useInvalidate();
  const contexts = useContexts();
  const projects = useAllProjects();
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [contextId, setContextId] = useState("");
  const [newContext, setNewContext] = useState("");
  const [autumnImport, setAutumnImport] = useState(false);
  const [force, setForce] = useState(false);
  const [merge, setMerge] = useState(true);
  const [verbose, setVerbose] = useState(false);
  const [tolerance, setTolerance] = useState("0.5");
  const [errors, setErrors] = useState<Record<string, string[]>>({});

  const [started, setStarted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [percent, setPercent] = useState<number | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let current = true;
    setPreview(null);
    setShowAll(false);
    setPreviewError("");
    if (file) void file.text().then((text) => {
      const inventory = previewImport(JSON.parse(text));
      if (current) setPreview(inventory);
    }).catch((failure: unknown) => {
      if (current) setPreviewError(failure instanceof SyntaxError ? "This file is not valid JSON." : errorMessage(failure));
    });
    return () => { current = false; };
  }, [file]);
  const source = useRef<AbortController | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  useEffect(() => () => source.current?.abort(), []);
  useEffect(() => {
    const log = logEnd.current?.parentElement;
    if (log) log.scrollTop = log.scrollHeight;
  }, [lines]);

  const append = (text: string, kind?: LogKind) =>
    setLines((current) => [...current, { id: nextId.current++, text, kind: kind ?? classifyMessage(text) }]);

  const finish = (ok: boolean) => {
    source.current = null;
    setBusy(false);
    setDone(true);
    if (ok) {
      setPercent(100);
      invalidate("projects", "sessions", "meta");
    }
  };

  const follow = async (uploadId: string) => {
    const controller = new AbortController();
    source.current = controller;
    let over = false;
    const handle = (message: string) => {
      append(message);
      const progress = projectProgress(message);
      if (progress) setPercent(progress.percent);
      if (isFinal(message)) {
        over = true;
        finish(succeeded(message) || message.includes("completed with skipped"));
      }
    };
    try {
      const response = await fetch(`/api/v2/import/uploads/${uploadId}/stream/`, {
        credentials: "same-origin",
        headers: { Accept: "*/*", "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error(`Import could not start (HTTP ${response.status}).`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!over) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseBuffer(buffer);
        buffer = parsed.rest;
        parsed.messages.forEach((message) => {
          if (!over) handle(message);
        });
      }
      if (!over) throw new Error("Connection lost. Please try again.");
    } catch (error) {
      if (controller.signal.aborted || over) return;
      over = true;
      append(`Error: ${error instanceof Error ? error.message : "Connection lost. Please try again."}`, "error");
      finish(false);
    }
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !preview) return;
    const found: Record<string, string[]> = {};
    if (!file) found.file = ["Choose a JSON file to import."];
    const tol = Number(tolerance);
    if (tolerance.trim() === "" || !Number.isFinite(tol) || tol < 0) {
      found.tolerance = ["Enter a number of minutes, 0 or more."];
    }
    setErrors(found);
    if (Object.keys(found).length || !file) return;

    const body = new FormData();
    body.append("file", file);
    body.append("autumn_import", String(autumnImport));
    body.append("force", String(force));
    body.append("merge", String(merge));
    body.append("verbose", String(verbose));
    body.append("tolerance", String(tol));
    if (contextId) body.append("import_context", contextId);
    if (newContext.trim()) body.append("import_context_new", newContext.trim());

    source.current?.abort();
    setBusy(true);
    setStarted(true);
    setDone(false);
    setLines([]);
    setPercent(null);
    setTitle(file.name);
    try {
      const { upload_id } = await requestJson<{ upload_id: string }>("POST", "/api/v2/import/uploads/", body);
      void follow(upload_id);
    } catch (error) {
      const details = (error as { details?: unknown }).details;
      const fieldErrors: Record<string, string[]> = {};
      if (details && typeof details === "object") {
        for (const [field, value] of Object.entries(details as Record<string, unknown>)) {
          fieldErrors[field] = Array.isArray(value) ? value.map(String) : [String(value)];
        }
      }
      setErrors(fieldErrors);
      append(`Error: ${errorMessage(error)}`, "error");
      toast.error(errorMessage(error));
      setBusy(false);
      setDone(true);
    }
  };

  const fieldErrors = (name: string) =>
    errors[name]?.map((line) => (
      <p key={line} className="io-field-error" role="alert">
        {line}
      </p>
    ));

  const failed = done && lines.some((line) => line.kind === "error");

  return (
    <div className="import-page">
      <div className="desk-head">
        <div>
          <h1 className="page-title">Import</h1>
        </div>
      </div>

      <form className="fields" onSubmit={onSubmit} noValidate>
        <div className="split">
          {!started ? <section id="import_options" className="slab slab-pad">
            <div className="field">
              <label htmlFor="import-file">JSON file</label>
              <FileDrop
                id="import-file"
                accept=".json,application/json"
                onFile={setFile}
              />
              {fieldErrors("file")}
              <small className="muted">Choose an Autumn JSON export. Nothing changes until you import.</small>
              {previewError ? <p className="io-field-error" role="alert">{previewError}</p> : null}
              {file && !preview && !previewError ? <p role="status">Reading file...</p> : null}
            </div>
            {preview ? <section className="import-preview" aria-label="Import preview">
              <h2 className="settings-form-title">Ready to bring over</h2>
              <p><strong>{preview.names.length} projects</strong> and <strong>{preview.sessions} sessions</strong> in this file</p>
              <ul tabIndex={0} aria-label="Projects in the import file">{(showAll ? preview.names : preview.names.slice(0, 6)).map((name, index) => {
                const exists = projects.data?.some((project) => project.name === name);
                const action = !projects.isSuccess ? "Checking existing projects..." : !exists ? "Add project" : preview.portable ? (force ? "Merge: update conflicting sessions" : "Existing project - conflicts checked during import") : force ? "Replace existing project" : merge ? "Merge into existing project" : "Skip existing project";
                return <li key={index}><span>{name}</span><small className={exists && force ? "text-red" : "muted"}>{action}</small></li>;
              })}</ul>
              <p className="muted">Showing {showAll ? preview.names.length : Math.min(6, preview.names.length)} of {preview.names.length}{preview.names.length > 6 ? <button type="button" className="btn btn--quiet" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : "Show all projects"}</button> : null}</p>
              <p className="muted">Autumn checks the full file when importing. Existing duplicate sessions are kept once.</p>
            </section> : null}
            <details className="import-advanced"><summary>Advanced options</summary><div className="fields">

            <div className="field">
              <label htmlFor="import-context">Import under context</label>
              <select id="import-context" value={contextId} onChange={(event) => setContextId(event.target.value)}>
                <option value="">(Use file context / default)</option>
                {(contexts.data ?? []).map((context) => (
                  <option key={context.id} value={context.id}>
                    {context.name}
                  </option>
                ))}
              </select>
              {fieldErrors("import_context")}
            </div>

            <div className="field">
              <label htmlFor="import-context-new">Or create context</label>
              <input
                id="import-context-new"
                type="text"
                placeholder="New context name"
                value={newContext}
                onChange={(event) => setNewContext(event.target.value)}
              />
              <small className="muted">
                Optional. If provided, a new context will be created (or reused) and used for all imported projects.
              </small>
              {fieldErrors("import_context_new")}
            </div>

            <div className="check-row u-mt-4">
              <input
                id="import-autumn"
                type="checkbox"
                checked={autumnImport}
                onChange={(event) => setAutumnImport(event.target.checked)}
              />
              <label htmlFor="import-autumn">Import an Autumn CLI legacy file</label>
            </div>
            {fieldErrors("autumn_import")}

            <div className="check-row">
              <input
                id="import-force"
                type="checkbox"
                checked={force}
                onChange={(event) => setForce(event.target.checked)}
              />
              <label htmlFor="import-force">{preview?.portable ? "Update conflicting sessions" : "Replace matching projects"}</label>
            </div>
            {fieldErrors("force")}
            {force ? <p className="io-field-error">{preview?.portable ? "Conflicting sessions with the same ID will be updated from the file." : "Matching projects and their existing sessions will be deleted before importing."}</p> : null}

            <div className="check-row">
              <input
                id="import-merge"
                type="checkbox"
                checked={merge}
                onChange={(event) => setMerge(event.target.checked)}
              />
              <label htmlFor="import-merge">Merge matching projects</label>
            </div>
            {fieldErrors("merge")}

            <div className="check-row">
              <input
                id="import-verbose"
                type="checkbox"
                checked={verbose}
                onChange={(event) => setVerbose(event.target.checked)}
              />
              <label htmlFor="import-verbose">Show detailed progress</label>
            </div>
            {fieldErrors("verbose")}

            <div className="field u-mt-4">
              <label htmlFor="import-tolerance">Duplicate time tolerance (minutes)</label>
              <input
                id="import-tolerance"
                type="number"
                step="any"
                min={0}
                value={tolerance}
                onChange={(event) => setTolerance(event.target.value)}
              />
              {fieldErrors("tolerance")}
            </div>

            </div></details>
            {!preview ? <p className="muted">Choose a valid Autumn JSON file to enable Import.</p> : null}
            <p className="import-policy">{force ? "Conflicts: replace from this file" : merge ? "Conflicts: merge projects, preserve existing sessions" : "Conflicts: skip existing projects"}</p>
            <div className="form-actions">
              <button type="submit" className="btn btn--primary btn--lg" disabled={busy || !preview}>
                <Icon icon={faFileImport} /> {busy ? "Importing..." : "Import"}
              </button>
            </div>
          </section> : null}

          {started ? (
            <section className="slab slab-pad stream-output" id="output-section" aria-live="polite">
              <h2 className="disclose-title">
                {done ? failed ? "Import needs attention: " : "Import complete: " : "Importing "}
                <span id="output-title" className="text-orange">
                  {title}
                </span>
              </h2>

              <div
                id="progress-bar"
                className={`meter stream-progress${busy && percent === null ? " is-indeterminate" : ""}`}
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent === null ? undefined : Math.round(percent)}
                aria-label="Import progress"
              >
                <div
                  className={`progress meter-fill ${failed ? "behind" : "complete"}`}
                  style={percent === null ? undefined : { width: `${percent}%` }}
                >
                  {percent === null ? "" : `${percent.toFixed(2)}%`}
                </div>
              </div>
              {done ? <div className="import-result"><p className="muted">{failed ? "Review the details below before trying again." : "Your journal is ready."}</p><button className="btn btn--secondary" type="button" onClick={() => { setStarted(false); setDone(false); }}>Choose another file</button>{!failed ? <AppLink className="btn btn--primary" href={urls.sessions()}>Open your journal</AppLink> : null}</div> : null}
              <details className="import-result-details" open={!done || failed}><summary>Import details</summary><div id="output-text" className="stream-log" tabIndex={0} aria-label="Import progress details">
                {lines.map((line) => (
                  <div key={line.id} className={`log-entry${line.kind === "info" ? "" : ` ${line.kind}`}`}>
                    {line.text}
                  </div>
                ))}
                <div ref={logEnd} />
              </div></details>
            </section>
          ) : null}
        </div>
      </form>
    </div>
  );
}
