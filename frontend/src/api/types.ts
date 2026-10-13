import type { components } from "./schema";

type S = components["schemas"];

/* note_html is only present when asked for with include=note_html; the
   schema marks every read-only field required, so loosen it here. */
type WithOptionalNoteHtml<T> = Omit<T, "note_html"> & { note_html?: string | null };

export type Session = WithOptionalNoteHtml<S["SessionListItem"]>;
export type SessionResource = WithOptionalNoteHtml<S["SessionResource"]>;
export type Timer = SessionResource;
export type Project = S["ProjectResource"];
export type ProjectDetail = S["ProjectDetailResource"];
export type ProjectSummary = S["ProjectSummary"];
export type Subproject = S["SubprojectResource"];
export type SubprojectAllocation = S["SubprojectAllocation"];
export type Context = S["ContextResource"];
export type Tag = S["TagResource"];
export type Commitment = S["CommitmentResource"];
export type ProjectStatus = S["StatusEnum"];
