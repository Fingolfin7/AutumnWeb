export interface ImportPreview { names: string[]; sessions: number; portable: boolean }

/** A local inventory, never an import or a claim that server validation passed. */
export function previewImport(document: unknown): ImportPreview {
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error("Choose an Autumn JSON export.");
  const data = document as Record<string, unknown>;
  if (data.format === 2) {
    if (!Array.isArray(data.projects)) throw new Error("This export needs a projects list.");
    let sessions = 0;
    const names = data.projects.map((item: unknown) => {
      if (!item || typeof item !== "object" || !("name" in item) || typeof item.name !== "string") throw new Error("A project is missing its name.");
      if (!("sessions" in item) || !Array.isArray(item.sessions)) throw new Error("A project is missing its sessions list.");
      sessions += item.sessions.length;
      return item.name;
    });
    return { names, sessions, portable: true };
  }
  let sessions = 0;
  for (const item of Object.values(data)) {
    if (!item || typeof item !== "object" || !("Session History" in item) || !Array.isArray(item["Session History"])) throw new Error("Choose an Autumn JSON export with project session histories.");
    sessions += item["Session History"].length;
  }
  return { names: Object.keys(data), sessions, portable: false };
}
