import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import {
  faAdjust,
  faBell,
  faChartPie,
  faPlus,
  faSearch,
  faFileExport,
  faFileImport,
  faFolderOpen,
  faHome,
  faLayerGroup,
  faListUl,
  faPlug,
  faSignOutAlt,
  faTags,
  faUserCircle,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { IconButton } from "@/components/ui";
import { Sheet } from "@/components/Sheet";
import { bootstrap } from "@/bootstrap";
import { csrfToken } from "@/lib/csrf";
import { requestJson } from "@/api/client";
import { AppLink, urls } from "./links";
import { useActiveContext } from "./context";
import { clearPersistedQueries } from "./persist";
import { fetchPreferences } from "@/features/profile/api";
import { TimerDock } from "@/features/timers/TimerDock";
import { applyBackground } from "@/features/profile/shell";

interface Tab {
  href: string;
  label: string;
  icon: IconDefinition;
  /** Path prefixes that light this tab up. */
  match: string[];
}

const tabs: Tab[] = [
  { href: urls.home(), label: "Today", icon: faHome, match: ["/", "/timers", "/start_timer", "/stop_timer", "/remove_timer"] },
  { href: urls.projects(), label: "Projects", icon: faFolderOpen, match: ["/projects", "/create_project", "/update_project", "/delete_project", "/merge_projects", "/create_subproject", "/update_subproject", "/delete_subproject", "/merge_subprojects", "/create_commitment", "/update_commitment", "/delete_commitment"] },
  { href: urls.sessions(), label: "Sessions", icon: faListUl, match: ["/sessions", "/update_session", "/delete_session"] },
  { href: urls.review(), label: "Review", icon: faChartPie, match: ["/charts", "/review", "/insights"] },
];

function isActive(tab: Tab, pathname: string) {
  return tab.match.some((prefix) => (prefix === "/" ? pathname === "/" : pathname.startsWith(prefix)));
}

export function Shell({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const boot = bootstrap();
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => setSettingsOpen(false), [pathname]);
  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname, search]);
  const settingsActive = ["/profile", "/settings", "/contexts", "/update_context", "/delete_context", "/tags", "/update_tag", "/delete_tag", "/notifications", "/import", "/export", "/mcp"].some((prefix) => pathname.startsWith(prefix));

  useEffect(() => {
    const interval = 60 * 60 * 1000;
    let lastCheck = Date.now();
    let disposed = false;
    let checking = false;
    const refresh = () => {
      if (document.hidden || checking || Date.now() - lastCheck < interval) return;
      checking = true;
      lastCheck = Date.now();
      void fetchPreferences().then((prefs) => {
        if (!disposed && prefs.automatic_background && prefs.background.image_url) applyBackground(prefs.background);
      }).catch(() => {
        // Retry on the next check if the connection is unavailable.
        lastCheck = 0;
      }).finally(() => { checking = false; });
    };
    const id = window.setInterval(refresh, interval);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      disposed = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="app-header app-header--auth">
        <div className="screen app-header-screen--auth">
          <AppLink className="brand" href={urls.home()} aria-label="Autumn">
            <img className="brand-mark" src={boot.static.leaf} alt="" />
            <span className="brand-word">Autumn</span>
          </AppLink>
          <nav className="primary-nav" aria-label="Primary">
            {tabs.map((tab, index) => {
              const active = isActive(tab, pathname);
              return <div className="nav-slot" key={tab.href}>
                {index === 2 ? <AppLink className="nav-capture btn-icon" href={urls.startTimer()} aria-label="New timer" title="New timer"><Icon icon={faPlus} /></AppLink> : null}
                <AppLink className={`nav-link${active ? " is-active" : ""}`} href={tab.href} aria-current={active ? "page" : undefined}>
                  <Icon icon={tab.icon} /><span>{tab.label}</span>
                </AppLink>
              </div>;
            })}
          </nav>
          <TimerDock />
          <div className="header-right">
            <ContextSwitch />
            <IconButton icon={faSearch} label="Go anywhere" onClick={() => window.dispatchEvent(new Event("autumn:palette"))} />
            <AppLink className="header-capture btn-icon" href={urls.startTimer()} aria-label="New timer" title="New timer"><Icon icon={faPlus} /></AppLink>
            <button className={`avatar${settingsActive ? " is-active" : ""}`} type="button" aria-label="Settings" title="Settings" aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(true)}>
              <img src={boot.profile.avatar_url} alt="" />
            </button>
          </div>
        </div>
      </header>
      <main id="main-content" className="screen screen-pad">
        {children}
      </main>

      <Sheet open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Settings">
        <div className="sheet-list">
          <SheetLink href={urls.profile()} icon={faUserCircle} label="Account & appearance" />
          <DimControl initial={boot.profile.background_dimming} />
          <SheetLink href={urls.notifications()} icon={faBell} label="Notifications" />
          <SheetLink href={urls.contexts()} icon={faLayerGroup} label="Contexts" />
          <SheetLink href={urls.tags()} icon={faTags} label="Tags" />
          <SheetLink href={urls.import()} icon={faFileImport} label="Import" />
          <SheetLink href={urls.export()} icon={faFileExport} label="Export" />
          <SheetLink href={urls.mcpConnections()} icon={faPlug} label="AI connections" />
          <form method="POST" action={urls.logout()} onSubmit={clearPersistedQueries}>
            <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
            <button className="sheet-item" type="submit">
              <Icon icon={faSignOutAlt} className="sheet-item-icon" /> Log out
            </button>
          </form>
        </div>
      </Sheet>
    </div>
  );
}

function SheetLink({ href, icon, label }: { href: string; icon: IconDefinition; label: string }) {
  return (
    <AppLink className="sheet-item" href={href}>
      <Icon icon={icon} className="sheet-item-icon" /> {label}
    </AppLink>
  );
}

function ContextSwitch() {
  const { contextId, contexts, setContextId } = useActiveContext();
  if (!contexts.length) return null;
  return (
    <div className="context-switch">
      <label className="sr-only" htmlFor="context-switch">
        Active context
      </label>
      <select
        id="context-switch"
        value={contextId === null ? "all" : String(contextId)}
        onChange={(event) => void setContextId(event.target.value === "all" ? null : Number(event.target.value))}
      >
        <option value="all">All contexts</option>
        {contexts.map((ctx) => (
          <option key={ctx.id} value={ctx.id}>
            {ctx.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/* Backdrop dimming, at hand in Settings. CSS shows it only when a photo
   resolved (body.bg-active). Applies instantly; saves debounced. */
function DimControl({ initial }: { initial: number }) {
  const [value, setValue] = useState(initial);
  const timer = useRef<number | undefined>(undefined);

  const change = (next: number) => {
    setValue(next);
    document.body.style.setProperty("--background-dim-opacity", (next / 100).toFixed(2));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void requestJson("PATCH", "/api/v2/me/preferences/", { background_dimming: next }).catch(() => {
        /* cosmetic: a failed save just means the old level returns next visit */
      });
    }, 400);
  };

  return (
    <div className="dim-control" title="Backdrop dimming">
      <Icon icon={faAdjust} className="dim-icon" />
      <label className="sr-only" htmlFor="header-dimming">
        Backdrop dimming
      </label>
      <input
        type="range"
        id="header-dimming"
        min={0}
        max={85}
        step={5}
        value={value}
        onChange={(event) => change(Number(event.target.value))}
      />
    </div>
  );
}
