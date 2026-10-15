import { useState } from "react";
import { faChevronDown, faPlus, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { Skeleton, ErrorState } from "@/components/states";
import { AppLink } from "@/app/links";
import { chatPath } from "./paths";
import { CHAT_PAGE_SIZE, chatStamp, limitGroups } from "./logic";
import type { ChatGroup } from "./types";

/* The past chats, grouped by recency, with delete on hover/focus. */
export function Sidebar({
  groups,
  loading,
  error,
  onRetry,
  activeId,
  collapsed,
  onDelete,
}: {
  groups: ChatGroup[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  activeId: string | undefined;
  collapsed: boolean;
  onDelete: (chat: { id: string; title: string }) => void;
}) {
  const [limit, setLimit] = useState(CHAT_PAGE_SIZE);
  /* Newest chats first; older ones load on request. */
  const view = limitGroups(groups ?? [], limit);
  const hasOlder = view.total > view.shown;
  const now = new Date();

  return (
    <aside className={`chat-sidebar${collapsed ? " collapsed" : ""}`} id="chat-sidebar" aria-label="Chats">
      <AppLink href={chatPath()} className="btn btn--primary btn--block new-chat-btn">
        <Icon icon={faPlus} /> New chat
      </AppLink>
      <div className="chat-list">
        {loading ? (
          <Skeleton lines={4} />
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : view.groups.length ? (
          view.groups.map((group) => (
            <div key={group.label} role="group" aria-label={group.label}>
              <p className="group-label">{group.label}</p>
              {group.chats.map((chat) => {
                const active = chat.id === activeId;
                return (
                  <div key={chat.id} className={`chat-item-container${active ? " active" : ""}`}>
                    <AppLink href={chatPath(chat.id)} className={`chat-item${active ? " active" : ""}`} aria-current={active ? "page" : undefined}>
                      <span className="chat-title" title={chat.title}>
                        {chat.title}
                      </span>
                    </AppLink>
                    <span className="reveal-stamp">{chatStamp(chat.updated_at, now)}</span>
                    <button type="button" className="delete-chat-btn" title="Delete chat" aria-label={`Delete chat: ${chat.title}`} onClick={() => onDelete(chat)}>
                      <Icon icon={faTrash} />
                    </button>
                  </div>
                );
              })}
            </div>
          ))
        ) : (
          <p className="empty chat-list-empty">No chats yet. Filter some sessions and ask a question.</p>
        )}
        {hasOlder ? (
          <button type="button" className="btn btn--quiet btn--block load-older-chats" onClick={() => setLimit(limit + CHAT_PAGE_SIZE)}>
            <Icon icon={faChevronDown} /> Load older chats
          </button>
        ) : null}
      </div>
    </aside>
  );
}
