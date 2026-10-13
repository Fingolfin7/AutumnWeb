import type { components } from "./schema";

type S = components["schemas"];

export type Session = S["SessionListItem"];
export type SessionResource = S["SessionResource"];
export type Timer = S["SessionResource"];
export type Project = S["ProjectResource"];
export type ProjectDetail = S["ProjectDetailResource"];
export type ProjectSummary = S["ProjectSummary"];
export type Subproject = S["SubprojectResource"];
export type SubprojectAllocation = S["SubprojectAllocation"];
export type Context = S["ContextResource"];
export type Tag = S["TagResource"];
export type Commitment = S["CommitmentResource"];
export type ProjectStatus = S["StatusEnum"];
