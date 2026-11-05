import { Navigate, useLocation } from "react-router";
import { faBell, faFileExport, faFileImport, faLayerGroup, faPlug, faTags, faUserCircle } from "@fortawesome/free-solid-svg-icons";
import { bootstrap } from "@/bootstrap";
import { csrfToken } from "@/lib/csrf";
import { clearPersistedQueries } from "@/app/persist";
import { useAccount, useProfilePreferences } from "@/features/profile/api";
import { AppLink } from "@/app/links";
import { Icon } from "@/components/Icon";
import ProfilePage from "@/features/profile/ProfilePage";
import ContextsPage from "@/features/contexts-tags/ContextsPage";
import TagsPage from "@/features/contexts-tags/TagsPage";
import NotificationsPage from "@/features/notifications/NotificationsPage";
import ImportPage from "@/features/import-export/ImportPage";
import ExportPage from "@/features/import-export/ExportPage";

const sections = [
  { id: "account", title: "Account & appearance", description: "Your details, backdrop and everyday defaults", icon: faUserCircle },
  { id: "contexts", title: "Contexts", description: "Separate work, study and the rest of life", icon: faLayerGroup },
  { id: "tags", title: "Tags", description: "Connect projects with a shared theme", icon: faTags },
  { id: "notifications", title: "Reminders & notifications", description: "A nudge at the right time", icon: faBell },
  { id: "ai", title: "AI connections", description: "Model providers, related search and connected apps", icon: faPlug },
  { id: "import", title: "Import", description: "Bring your existing time into Autumn", icon: faFileImport },
  { id: "export", title: "Export", description: "Take your projects and journal with you", icon: faFileExport },
] as const;

export default function SettingsPage() {
  const location = useLocation();
  const prefs = useProfilePreferences();
  const account = useAccount();
  const id = location.pathname.split("/")[2];
  const section = sections.find((item) => item.id === id);
  return <div className={`settings-page${section ? " settings-page--section" : ""}`}>
    <header className="settings-heading">
      {section ? <AppLink className="settings-back" href="/settings/">‹ All settings</AppLink> : null}
      <h1 className="page-title">{section?.title ?? "Settings"}</h1>
      <p>{section?.description ?? "Your account and workspace."}</p>
    </header>
    <div className="settings-layout">
      <nav className="settings-sections" aria-label="Settings sections">
        {sections.map((item) => <AppLink key={item.id} href={`/settings/${item.id}/`} aria-current={id === item.id ? "page" : undefined}>
          <Icon icon={item.icon} /><span><strong>{item.title}</strong><small>{item.description}</small></span><span className="settings-chevron" aria-hidden="true">›</span>
        </AppLink>)}
      </nav>
      <div className="settings-content" key={id ?? "index"}>
        {id === "account" ? <ProfilePage section="account" /> : id === "ai" ? <ProfilePage section="ai" /> : id === "contexts" ? <ContextsPage /> : id === "tags" ? <TagsPage /> : id === "notifications" ? <NotificationsPage /> : id === "import" ? <ImportPage /> : id === "export" ? <ExportPage /> : <section className="settings-overview slab slab-pad"><h2>Your workspace</h2><dl><div><dt>Signed in as</dt><dd>{account.data?.username ?? bootstrap().user.username}</dd></div><div><dt>Timezone</dt><dd>{prefs.data?.timezone ?? bootstrap().profile.timezone}</dd></div><div><dt>Backdrop</dt><dd>{prefs.data?.automatic_background ? "A new photo every day" : prefs.data?.background.image_url ? "Your uploaded photo" : "Night Ledger"}</dd></div><div><dt>Reporting range</dt><dd>{prefs.data ? `${prefs.data.default_filter_value} ${prefs.data.default_filter_unit.replaceAll("_", " ")}` : "Loading…"}</dd></div></dl><AppLink className="btn btn--secondary" href="/settings/account/">Edit account & appearance</AppLink></section>}
      </div>
    </div>
    <form className="settings-logout" method="POST" action="/logout/" onSubmit={clearPersistedQueries}><input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} /><button className="btn btn--quiet" type="submit">Log out</button></form>
  </div>;
}

/** Bookmarks and cached SPA links follow the same redirects as Django. */
export function LegacySettingsPage() {
  const { pathname, search, hash } = useLocation();
  const section = ({ profile: "account", contexts: "contexts", tags: "tags", notifications: "notifications", import: "import", export: "export" } as Record<string, string>)[pathname.split("/")[1] ?? ""];
  return <Navigate replace to={`/settings/${section ?? ""}/${search}${hash}`} />;
}
