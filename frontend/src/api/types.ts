import type { components } from "./schema";

type S = components["schemas"];

/* note_html is only present when asked for with include=note_html; the
   schema marks every read-only field required, so loosen it here. */
type WithOptionalNoteHtml<T> = Omit<T, "note_html"> & { note_html?: string | null };

export type Session = WithOptionalNoteHtml<S["SessionListItem"]>;
export type SessionResource = WithOptionalNoteHtml<S["SessionResource"]>;
/* pending_sync: started while Autumn was unreachable; lives in the offline
   queue (lib/offlineQueue.ts) until the server has it. */
export type Timer = SessionResource & { pending_sync?: boolean };
export type Project = S["ProjectResource"];
export type ProjectDetail = S["ProjectDetailResource"];
export type ProjectSummary = S["ProjectSummary"];
export type Subproject = S["SubprojectResource"];
export type SubprojectAllocation = S["SubprojectAllocation"];
export type Context = S["ContextResource"];
export type Tag = S["TagResource"];
export type Commitment = S["CommitmentResource"];
export type ProjectStatus = S["ProjectStatusEnum"];
export type CommitmentFilters = S["CommitmentFilters"];
export type NamedResource = S["NamedResource"];
export type SessionPatch = S["PatchedSessionPatchRequest"];
export type SubprojectAllocationWrite = S["SubprojectAllocationWrite"];
export type Preferences = S["PreferencesResponse"];
export type CommitmentCreate = S["CommitmentCreateRequest"];
export type CommitmentChanges = S["PatchedCommitmentChangesRequest"];
export type CommitmentPeriod = S["CommitmentPeriod"];
