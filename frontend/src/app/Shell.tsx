import { useEffect, useLayoutEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import {
  faChartPie,
  faPlus,
  faSearch,
  faFolderOpen,
  faHome,
  faListUl,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { IconButton } from "@/components/ui";
import { hasCustomAvatar } from "@/features/profile/model";
import { bootstrap } from "@/bootstrap";
import { AppLink, urls } from "./links";
import { useActiveContext } from "./context";
import { ToastOutlet } from "./toasts";
import { OfflineSync } from "./OfflineSync";
import { fetchPreferences } from "@/features/profile/api";
import { CaptureLink } from "@/features/timers/CaptureLayer";
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
      <header className={`app-header app-header--auth${settingsActive ? " app-header--settings" : ""}`}>
        <div className="screen app-header-screen--auth">
          <AppLink className="brand" href={urls.home()} aria-label="Autumn">
            <img className="brand-mark" src={boot.static.leaf} alt="" />
            <span className="brand-word">{settingsActive ? "Settings" : "Autumn"}</span>
          </AppLink>
          <nav className="primary-nav" aria-label="Primary">
            {tabs.map((tab, index) => {
              const active = isActive(tab, pathname);
              return <div className="nav-slot" key={tab.href}>
                {index === 2 ? <CaptureLink className="nav-capture btn-icon" aria-label="New timer" title="New timer"><Icon icon={faPlus} /></CaptureLink> : null}
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
            <CaptureLink className="header-capture btn-icon" aria-label="New timer" title="New timer"><Icon icon={faPlus} /></CaptureLink>
            <AppLink className={`avatar${settingsActive ? " is-active" : ""}`} href="/settings/" aria-label="Settings" title="Settings">
              <img src={boot.profile.avatar_url} alt="" hidden={!hasCustomAvatar(boot.profile.avatar_url)} />
              <span className="avatar-monogram" hidden={hasCustomAvatar(boot.profile.avatar_url)}>{boot.user.username.slice(0, 1).toUpperCase() || "A"}</span>
            </AppLink>
          </div>
        </div>
      </header>
      <ToastOutlet />
      <OfflineSync />
      <main id="main-content" className="screen screen-pad">

        {children}
      </main>

    </div>
  );
}

function ContextSwitch() {
  const { contextId, contexts, setContextId } = useActiveContext();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const params = new URLSearchParams(search);
  const selected = params.get("context");
  const activeId = selected === "all" ? null : selected ? Number(selected) : contextId;
  return (
    <div className={`context-switch${activeId !== null ? " is-filtered" : ""}`}>
      <label className="sr-only" htmlFor="context-switch">
        Active context
      </label>
      <select
        id="context-switch"
        value={activeId === null ? "all" : String(activeId)}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "manage") { navigate("/settings/contexts/"); return; }
          if (selected) { params.set("context", value); navigate(`${pathname}?${params}`, { replace: true }); }
          else void setContextId(value === "all" ? null : Number(value));
        }}
      >
        <option value="all">All contexts</option>
        {contexts.map((ctx) => (
          <option key={ctx.id} value={ctx.id}>
            {ctx.name}
          </option>
        ))}
        <option value="manage">Manage contexts</option>
      </select>
    </div>
  );
}
