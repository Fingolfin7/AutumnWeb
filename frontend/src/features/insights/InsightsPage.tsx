import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { faCalendarAlt, faCheck, faCheckSquare, faChevronLeft, faChevronRight, faComments, faCopy, faSlidersH, faTimes } from "@fortawesome/free-solid-svg-icons";
import { useQueryClient } from "@tanstack/react-query";
import { Icon } from "@/components/Icon";
import { ConfirmDialog } from "@/components/Sheet";
import { Empty, ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useActiveContext } from "@/app/context";
import { useToast } from "@/app/toasts";
import { useAllProjects, useContexts, useTags } from "@/api/meta";
import { ApiError } from "@/api/errors";
import { bootstrap } from "@/bootstrap";
import { formatDayDate } from "@/lib/format";
import { semanticSearchAvailable, usePreferences } from "@/features/charts/api";
import { useDeleteChat, useInsightChat, useInsightChats, useInsightOptions, useSelectionPreview } from "./api";
import { Composer } from "./Composer";
import { FilterSheet } from "./FilterSheet";
import { Sidebar } from "./Sidebar";
import { runItems, savedItems, Transcript } from "./Transcript";
import { chatPath } from "./paths";
import { isLive, showsRun } from "./run";
import { currentRun, startRun, stopStream, useRun } from "./runStore";
import {
  buildTranscript,
  describeSelection,
  EMPTY_SELECTION,
  formatUsage,
  previewQuery,
  readSelection,
  resolveSelection,
  selectionFromChat,
  selectionRequest,
  splitChatModel,
  sumUsage,
  USAGE_TITLE,
  visibleTurns,
  type ModelSelection,
  type SelectionFilters,
} from "./logic";
import type { ChatDetail, InsightOptions, StreamRequest } from "./types";
import "./insights.css";

/* ---- remembered choices ---------------------------------------------------- */

const COLLAPSED_KEY = "chatSidebarCollapsed";
const LAST_MODEL_KEY = "autumn:insights:model";

function readLastModel(): { provider?: string; model?: string; effort?: string } {
  try {
    return JSON.parse(window.localStorage.getItem(LAST_MODEL_KEY) ?? "{}") as { provider?: string; model?: string; effort?: string };
  } catch {
    return {};
  }
}

function initialCollapsed(): boolean {
  /* Below 700px the list is a drawer over the transcript, so it starts closed
     whatever was stored (and without overwriting what the wide layout chose). */
  if (window.matchMedia?.("(max-width: 700px)").matches) return true;
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

/* ---- page ------------------------------------------------------------------ */

export default function InsightsPage() {
  const { chatId } = useParams();
  const location = useLocation();
  const profile = bootstrap().profile;
  if (!profile.insights_access_enabled) return <NoAccess aiEnabled={profile.ai_features_enabled} />;
  /* A fresh state per navigation: New chat on /insights/ resets the page. */
  return <Workspace key={location.key} chatId={chatId} />;
}

function NoAccess({ aiEnabled }: { aiEnabled: boolean }) {
  return (
    <>
      <h1 className="sr-only">Insights</h1>
      <section className="slab">
        <Empty>
          {aiEnabled ? (
            <>
              Add an AI provider API key or connect Codex in your <AppLink href={urls.profile()}>Profile</AppLink> to use Insights.
            </>
          ) : (
            <>
              AI features are disabled for this account. You can switch them on in your <AppLink href={urls.profile()}>Profile</AppLink>.
            </>
          )}
        </Empty>
      </section>
    </>
  );
}

function Workspace({ chatId }: { chatId: string | undefined }) {
  const options = useInsightOptions(true);
  const chat = useInsightChat(chatId);

  if (options.isPending || (chatId && chat.isPending)) {
    return (
      <>
        <h1 className="sr-only">Insights</h1>
        <section className="slab slab-pad">
          <Skeleton lines={6} />
        </section>
      </>
    );
  }
  if (options.isError) return <PageError error={options.error} onRetry={() => void options.refetch()} />;
  if (chatId && chat.isError) {
    const gone = chat.error instanceof ApiError && chat.error.status === 404;
    return gone ? (
      <>
        <h1 className="sr-only">Insights</h1>
        <section className="slab">
          <Empty>
            That chat no longer exists. <AppLink href={chatPath()}>Start a new chat</AppLink>.
          </Empty>
        </section>
      </>
    ) : (
      <PageError error={chat.error} onRetry={() => void chat.refetch()} />
    );
  }
  return <Desk chatId={chatId} chat={chat.data} options={options.data!} />;
}

function PageError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <>
      <h1 className="sr-only">Insights</h1>
      <ErrorState error={error} onRetry={onRetry} />
    </>
  );
}

/* ---- the desk -------------------------------------------------------------- */

function Desk({ chatId, chat, options }: { chatId: string | undefined; chat: ChatDetail | undefined; options: InsightOptions }) {
  const navigate = useNavigate();
  const toast = useToast();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const { contextId } = useActiveContext();
  const username = bootstrap().user.username;

  const defaults = useMemo(() => ({ start: options.default_start_date, end: options.default_end_date }), [options]);
  const projects = useAllProjects();
  const tags = useTags();
  const contexts = useContexts();
  const preferences = usePreferences();
  const semantic = semanticSearchAvailable(preferences.data);
  const chats = useInsightChats(true);
  const deleteChat = useDeleteChat();
  const run = useRun();

  /* What the model is grounded in. A chat opens on the filters it was started
     with; a new one on the URL's (old links) or the profile's default range. */
  const [selection, setSelection] = useState<SelectionFilters>(() =>
    chat ? selectionFromChat(chat.filters, defaults) : readSelection(params, defaults),
  );
  const [draft, setDraft] = useState(selection);
  /* The selection changed since the chat last saw it: send it with the next
     question so the model is handed the new sessions. */
  const [reselected, setReselected] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const [model, setModel] = useState<ModelSelection | null>(() => {
    const stored = splitChatModel(chat?.model);
    const wanted = chat ? { ...stored, effort: chat.filters?.reasoning_effort } : readLastModel();
    return resolveSelection(options, wanted);
  });
  const [prompt, setPrompt] = useState("");
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [copiedWhole, setCopiedWhole] = useState(false);
  const [copiedPicked, setCopiedPicked] = useState(false);
  const [deleting, setDeleting] = useState<{ id: string; title: string } | null>(null);
  const ownRun = useRef<number | null>(null);

  const query = previewQuery(selection, projects.data ?? [], contextId);
  const preview = useSelectionPreview(query.none ? null : query.query, !selection.project_name || !!projects.data);
  const count = preview.data?.count;

  const turns = useMemo(() => visibleTurns(chat?.messages ?? [], model?.model ?? ""), [chat, model?.model]);
  const shownRun = run && showsRun(run, chatId, turns.length) ? run : null;
  const items = useMemo(() => [...savedItems(turns), ...(shownRun ? runItems(shownRun) : [])], [turns, shownRun]);
  const live = !!run && isLive(run) && (run.chatId === (chatId ?? null) || ownRun.current === run.id);
  const hasHistory = items.length > 0;

  const usage = sumUsage([...(chat?.messages ?? []).map((m) => m.metadata?.usage), shownRun?.status === "done" ? shownRun.usage : null]);

  /* The first answer creates the chat: move the URL onto it. The page
     remounts there; the run carries over (runStore). */
  useEffect(() => {
    if (!chatId && run && run.chatId && ownRun.current === run.id) {
      ownRun.current = null;
      navigate(chatPath(run.chatId), { replace: true });
    }
  }, [chatId, run, navigate]);

  const pills = describeSelection(
    selection,
    { projects: projects.data ?? [], tags: tags.data ?? [], contexts: contexts.data ?? [] },
    defaults,
    { available: semantic, state: preview.data?.related ?? null },
  );

  const select = (next: SelectionFilters) => {
    setSelection(next);
    setDraft(next);
    setReselected(true);
    setSheetOpen(false);
    toast.success("Session selection updated.");
  };
  const onSelect = (event: FormEvent) => {
    event.preventDefault();
    select(draft);
  };
  const clearSelection = () => select({ ...EMPTY_SELECTION, start_date: defaults.start, end_date: defaults.end });

  const send = () => {
    const message = prompt.trim();
    if (!message || !model || live) return;
    const body: StreamRequest = {
      message,
      provider: model.provider,
      model: model.model,
      ...(model.effort ? { reasoning_effort: model.effort } : {}),
      ...(chatId ? { chat_id: chatId } : {}),
      ...(!chatId || reselected ? selectionRequest(selection, defaults, contextId) : {}),
    };
    try {
      window.localStorage.setItem(LAST_MODEL_KEY, JSON.stringify(model));
    } catch {
      /* storage unavailable */
    }
    setPrompt("");
    const base = turns.length;
    void startRun({
      client,
      body,
      baseCount: base,
      chatModel: `${model.provider}:${model.model}`,
      seedFilters: { ...selectionRequest(selection, defaults, contextId), reasoning_effort: model.effort },
    }).then(() => {
      if (currentRun()?.status !== "error") setReselected(false);
    });
    ownRun.current = currentRun()?.id ?? null;
  };

  const toggleSidebar = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      window.localStorage.setItem(COLLAPSED_KEY, String(next));
    } catch {
      /* storage unavailable */
    }
  };

  const toggleSelecting = () => {
    setSelecting(!selecting);
    setPicked(new Set());
  };
  const togglePicked = (key: string) => {
    const next = new Set(picked);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setPicked(next);
  };
  const copy = (text: string, done: (value: boolean) => void) => {
    void navigator.clipboard?.writeText(text).then(() => {
      done(true);
      window.setTimeout(() => done(false), 2000);
    });
  };

  const confirmDelete = () => {
    if (!deleting) return;
    const target = deleting;
    if (run && isLive(run) && run.chatId === target.id) stopStream();
    deleteChat.mutate(target.id, {
      onSuccess: () => {
        setDeleting(null);
        if (target.id === chatId) navigate(chatPath());
      },
      onSettled: () => setDeleting(null),
    });
  };

  const showEmpty = count === 0 && !hasHistory;
  const loadingBody = preview.isPending && !hasHistory && !preview.isError;
  const sessionLabel = count === 1 ? "session" : "sessions";

  return (
    <>
      <h1 className="sr-only">Insights</h1>
      <form className="fields" id="search_form" onSubmit={onSelect}>
        <div className="searchbar searchbar--range">
          <Icon icon={faCalendarAlt} className="fas muted" />
          <span className="range-fields">
            <label className="sr-only" htmlFor="start_date">
              Start date
            </label>
            <input id="start_date" type="date" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} />
            <span className="range-sep muted" aria-hidden="true">
              &rarr;
            </span>
            <label className="sr-only" htmlFor="end_date">
              End date
            </label>
            <input id="end_date" type="date" value={draft.end_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} />
          </span>
          <button
            className="filter-launcher"
            type="button"
            aria-haspopup="dialog"
            onClick={() => setSheetOpen(true)}
          >
            <Icon icon={faSlidersH} /> Filters
            {pills.length ? <span className="filter-count">{pills.length}</span> : null}
          </button>
          <button type="submit" className="btn btn--primary" id="search_button">
            <Icon icon={faCheck} /> Select sessions
          </button>
        </div>

        {pills.length ? (
          <p className="filter-summary">
            {pills.map((pill) => (
              <span key={pill.label} className="filter-pill" id={pill.label === "Including" || pill.label === "Related" ? "related-pill" : undefined} title={pill.title}>
                {pill.label} <b>{pill.value}</b>
              </span>
            ))}
            <button className="btn btn--quiet" type="button" onClick={clearSelection}>
              Clear
            </button>
          </p>
        ) : null}
      </form>

      <FilterSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        draft={draft}
        onDraft={setDraft}
        onApply={() => select(draft)}
        onClear={clearSelection}
        semantic={semantic}
        projects={projects.data ?? []}
        tags={tags.data ?? []}
        contexts={contexts.data ?? []}
        activeContextId={contextId}
      />

      <section className="slab chat-layout">
        <Sidebar
          groups={chats.data}
          loading={chats.isPending}
          error={chats.isError ? chats.error : null}
          onRetry={() => void chats.refetch()}
          activeId={chatId}
          collapsed={collapsed}
          onDelete={setDeleting}
        />

        <main className="chat-main">
          <div className="chat-header">
            <button type="button" id="toggle-sidebar-btn" className="btn-icon" onClick={toggleSidebar} title="Toggle chat list" aria-label="Toggle chat list" aria-expanded={!collapsed} aria-controls="chat-sidebar">
              <Icon icon={collapsed ? faChevronRight : faChevronLeft} />
            </button>
            {(count ?? 0) > 0 || hasHistory ? (
              <>
                <div className="chat-header-meta">
                  <h3>{count ? `${count} ${sessionLabel}` : "Conversation"}</h3>
                  {count && preview.data?.earliest && preview.data.latest ? (
                    <span className="chat-header-range muted">
                      <span className="text-cyan">{formatDayDate(preview.data.earliest)}</span> &ndash; <span className="text-cyan">{formatDayDate(preview.data.latest)}</span>
                    </span>
                  ) : null}
                  <span id="token-usage" className="chat-header-tokens muted" title={USAGE_TITLE}>
                    {formatUsage(usage)}
                  </span>
                </div>
                {hasHistory ? (
                  <div className="chat-header-actions">
                    <button type="button" id="select-messages-btn" className="chat-action-btn" onClick={toggleSelecting} title="Select messages to copy">
                      <Icon icon={selecting ? faTimes : faCheckSquare} /> {selecting ? "Cancel" : "Select"}
                    </button>
                    {selecting ? (
                      <button
                        type="button"
                        id="copy-selected-btn"
                        className="chat-action-btn"
                        disabled={picked.size === 0}
                        onClick={() => copy(buildTranscript(items.filter((i) => picked.has(i.key)), username), setCopiedPicked)}
                      >
                        <Icon icon={copiedPicked ? faCheck : faCopy} /> {copiedPicked ? "Copied!" : `Copy (${picked.size})`}
                      </button>
                    ) : null}
                    <button type="button" id="copy-full-chat-btn" className="chat-action-btn" onClick={() => copy(buildTranscript(items, username), setCopiedWhole)}>
                      <Icon icon={copiedWhole ? faCheck : faCopy} /> {copiedWhole ? "Copied!" : "Copy chat"}
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>

          {loadingBody ? (
            <Skeleton lines={4} />
          ) : showEmpty ? (
            <div className="empty-state-container">
              {bootstrap().static.leaf ? <img src={bootstrap().static.leaf} alt="" /> : null}
              <p className="empty">
                No sessions match these filters, so there is nothing to ask about yet. Widen the range in <b>Filters</b>, or{" "}
                <AppLink href={urls.sessions()}>check what you have tracked</AppLink>.
              </p>
            </div>
          ) : (
            <div className="chat-form" id="chat-form">
              <Transcript
                items={items}
                selecting={selecting}
                selected={picked}
                onToggle={togglePicked}
                empty={
                  <div className="empty-state-container">
                    <Icon icon={faComments} className="muted" />
                    <p className="empty">
                      {count ?? 0} {sessionLabel} selected. Ask something below to start the conversation.
                    </p>
                  </div>
                }
              />
              {model ? (
                <Composer options={options} selection={model} onSelection={setModel} prompt={prompt} onPrompt={setPrompt} busy={live} onSend={send} onStop={stopStream} />
              ) : (
                <p className="empty">
                  No AI provider is set up. Add a key in your <AppLink href={urls.profile()}>Profile</AppLink>.
                </p>
              )}
            </div>
          )}
        </main>
      </section>

      <ConfirmDialog
        open={!!deleting}
        title="Delete this chat?"
        body={deleting ? <>“{deleting.title}” and its messages will be deleted.</> : null}
        confirmLabel="Delete chat"
        danger
        busy={deleteChat.isPending}
        onConfirm={confirmDelete}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
