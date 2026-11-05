export interface ImportPreview { names: string[]; sessions: number; portable: boolean; projects: { name: string; sessions: number }[]; conflicts: number; repeated: number }

/** A local inventory, never an import or a claim that server validation passed. */
export function previewImport(document: unknown): ImportPreview {
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error("Choose an Autumn JSON export.");
  const data = document as Record<string, unknown>;
  if (data.format === 2) {
    if (!Array.isArray(data.projects)) throw new Error("This export needs a projects list.");
    let sessions = 0;
    const projects: ImportPreview["projects"] = [];
    const records = new Map<string, string>();
    const conflicts = new Set<string>();
    let repeated = 0;
    const names = data.projects.map((item: unknown) => {
      if (!item || typeof item !== "object" || !("name" in item) || typeof item.name !== "string") throw new Error("A project is missing its name.");
      if (!("sessions" in item) || !Array.isArray(item.sessions)) throw new Error("A project is missing its sessions list.");
      sessions += item.sessions.length;
      projects.push({ name: item.name, sessions: item.sessions.length });
      for (const session of item.sessions) {
        if (!session || typeof session !== "object" || typeof session.uuid !== "string") continue;
        const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => [key, stable(value)])) : value;
        const fingerprint = JSON.stringify(stable({ ...session, project: item.name }));
        if (records.has(session.uuid)) { repeated++; if (records.get(session.uuid) !== fingerprint) conflicts.add(session.uuid); }
        else records.set(session.uuid, fingerprint);
      }
      return item.name;
    });
    return { names, sessions, portable: true, projects, conflicts: conflicts.size, repeated };
  }
  let sessions = 0;
  const projects: ImportPreview["projects"] = [];
  for (const [name, item] of Object.entries(data)) {
    if (!item || typeof item !== "object" || !("Session History" in item) || !Array.isArray(item["Session History"])) throw new Error("Choose an Autumn JSON export with project session histories.");
    sessions += item["Session History"].length;
    projects.push({ name, sessions: item["Session History"].length });
  }
  return { names: Object.keys(data), sessions, portable: false, projects, conflicts: 0, repeated: 0 };
}
