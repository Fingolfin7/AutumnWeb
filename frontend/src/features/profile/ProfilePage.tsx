import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faPlug, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { bootstrap } from "@/bootstrap";
import { keys } from "@/api/keys";
import { ApiError, errorMessage } from "@/api/errors";
import {
  fetchPreferences,
  meKeys,
  patchAccount,
  patchPreferences,
  removeAvatar,
  removeBackground,
  uploadAvatar,
  uploadBackground,
  useAccount,
  useProfilePreferences,
  useSocialAccounts,
} from "./api";
import {
  accountChanges,
  accountDraft,
  deviceTimeZone,
  detailsOf,
  FILTER_UNITS,
  hasCustomAvatar,
  isToDate,
  prefsChanges,
  prefsDraft,
  timeZoneNames,
  validatePrefs,
  type Account,
  type AccountDraft,
  type Prefs,
  type PrefsDraft,
} from "./model";
import { AiSection } from "./AiSection";
import { BackgroundSection } from "./BackgroundSection";
import { FieldErrors, SlabHead } from "./Parts";
import { applyAvatar, applyBackground, applyDimming, applyPrefs, refreshBootstrapProfile, syncHeaderDimming } from "./shell";
import { SocialConnectForms, SocialSection } from "./SocialSection";
import { SimilaritySlider } from "@/features/search/SimilaritySlider";
import { similarityScale } from "@/features/search/similarity";
import "./profile.css";

/* Profile (users/templates/users/profile.html): account, avatar, backdrop,
   defaults, LLM connections, connected logins. */
export default function ProfilePage({ section = "account" }: { section?: "account" | "appearance" | "defaults" | "search" | "ai" }) {
  const account = useAccount();
  const prefs = useProfilePreferences();
  const social = useSocialAccounts();

  /* The form starts from these values and is then the user's to edit, so wait
     for a fresh answer rather than start from another page's cached copy
     (offline, a paused request means the cached copy is all there is). */
  const settled = (q: typeof account | typeof prefs) => q.isFetchedAfterMount || q.fetchStatus === "paused";
  const failed = (account.isError && !account.data) || (prefs.isError && !prefs.data);
  const editable = account.data && prefs.data && settled(account) && settled(prefs);

  return (
    <>
      <div className="desk-head">
        <div>
          <h1 className="page-title">{{ account: "Account", appearance: "Appearance", defaults: "Reporting defaults", search: "Search preferences", ai: "AI connections" }[section]}</h1>
        </div>
      </div>
      {failed ? (
        <ErrorState
          error={account.error ?? prefs.error}
          onRetry={() => {
            void account.refetch();
            void prefs.refetch();
          }}
        />
      ) : editable ? (
        <ProfileEditor section={section} account={account.data} prefs={prefs.data} social={social.data ?? { accounts: [], has_usable_password: true }} />
      ) : (
        <section className="slab slab-pad">
          <Skeleton lines={6} />
        </section>
      )}
    </>
  );
}

type SaveScope = "account" | "appearance" | "defaults" | "search" | "ai";
const PREF_SCOPE: Record<SaveScope, string[]> = {
  account: ["timezone"], appearance: ["automatic_background", "bing_background", "nasa_apod_background", "background_dimming"],
  defaults: ["default_filter_value", "default_filter_unit", "insights_default_filter_value", "insights_default_filter_unit", "default_chart_project_count"],
  search: ["related_similarity"], ai: ["luna_recommendation_effort"],
};
const DRAFT_SCOPE: Record<SaveScope, (keyof PrefsDraft)[]> = { account: ["timezone"], appearance: ["automatic", "choice", "dimming"], defaults: ["filterValue", "filterUnit", "insightsValue", "insightsUnit", "chartCount"], search: ["similarity"], ai: ["luna"] };

function ProfileEditor({
  account,
  prefs,
  social,
  section,
}: {
  section: "account" | "appearance" | "defaults" | "search" | "ai";
  account: Account;
  prefs: Prefs;
  social: ReturnType<typeof useSocialAccounts>["data"] & object;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const [accountD, setAccountD] = useState<AccountDraft>(() => accountDraft(account));
  const [prefsD, setPrefsD] = useState<PrefsDraft>(() => prefsDraft(prefs));
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [backgroundFile, setBackgroundFile] = useState<File | null>(null);
  const [removeBg, setRemoveBg] = useState(false);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [retryVersion, setRetryVersion] = useState(0);

  const patchPrefsDraft = (patch: Partial<PrefsDraft>) => setPrefsD((current) => ({ ...current, ...patch }));
  const zones = useMemo(timeZoneNames, []);
  const device = useMemo(deviceTimeZone, []);

  /* The header's dimming slider and this page's slider are the same setting. */
  useEffect(() => {
    const onInput = (event: Event) => {
      const target = event.target as HTMLElement | null;
      if (target?.id === "header-dimming") {
        setPrefsD((current) => ({
          ...current,
          dimming: Number((target as HTMLInputElement).value),
        }));
      }
    };
    document.addEventListener("input", onInput);
    return () => {
      document.removeEventListener("input", onInput);
      /* An unsaved preview must not outlive the page. */
      const header = document.getElementById("header-dimming") as HTMLInputElement | null;
      applyDimming(header ? Number(header.value) : bootstrap().profile.background_dimming);
    };
  }, []);

  const avatarPreview = useMemo(() => (avatarFile ? URL.createObjectURL(avatarFile) : null), [avatarFile]);
  useEffect(() => () => (avatarPreview ? URL.revokeObjectURL(avatarPreview) : undefined), [avatarPreview]);

  const onRemoveAvatar = async () => {
    try {
      const result = await removeAvatar();
      applyAvatar(result.url ?? "");
      setAvatarFile(null);
      void qc.invalidateQueries({ queryKey: keys.preferences() });
      toast.success("Profile image removed.");
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const onSubmit = async (event: FormEvent | undefined, scope: SaveScope, automatic = false) => {
    event?.preventDefault();
    if (saving) return;

    const invalid = Object.fromEntries(Object.entries(validatePrefs(prefsD)).filter(([key]) => PREF_SCOPE[scope].includes(key)));
    if (Object.keys(invalid).length) {
      setSaveFailed(true);
      setErrors(Object.fromEntries(Object.entries(invalid).map(([field, message]) => [field, [message]])));
      toast.error("Please fix the highlighted fields.");
      return;
    }

    setSaveFailed(false);
    setSaving(true);
    const found: Record<string, string[]> = {};
    const general: string[] = [];
    let didSomething = false;

    /* One failed part must not stop the others; each reports its own fields. */
    const attempt = async <T,>(scope: string | null, run: () => Promise<T>): Promise<T | undefined> => {
      try {
        const result = await run();
        didSomething = true;
        return result;
      } catch (error) {
        const { fields, general: message } = detailsOf(error);
        for (const [field, lines] of Object.entries(fields)) {
          const key = scope && (field === "image" || field === "key") ? scope : field;
          (found[key] ??= []).push(...lines);
        }
        if (message) general.push(message);
        else if (!Object.keys(fields).length && error instanceof ApiError) general.push(error.message);
        return undefined;
      }
    };

    let accountOk = true;
    let prefsOk = true;

    if (scope === "account" && avatarFile) {
      const result = await attempt("avatar_image", () => uploadAvatar(avatarFile));
      if (result) {
        applyAvatar(result.url ?? "");
        setAvatarFile(current => current === avatarFile ? null : current);
      }
    }

    const accountPatch = scope === "account" ? accountChanges(accountD, account) : null;
    let newAccount: Account | undefined;
    if (accountPatch) {
      newAccount = await attempt(null, () => patchAccount(accountPatch));
      accountOk = !!newAccount;
      if (newAccount) {
        qc.setQueryData(meKeys.account(), newAccount);
        bootstrap().user.username = newAccount.username;
        bootstrap().user.email = newAccount.email;
        setAccountD(current => {
          const next = accountDraft(newAccount!);
          return Object.fromEntries(Object.entries(current).map(([key, value]) => [key, value === accountD[key as keyof AccountDraft] ? next[key as keyof AccountDraft] : value])) as unknown as AccountDraft;
        });
      }
    }

    if (scope === "appearance" && !prefsD.automatic) {
      if (backgroundFile) {
        const result = await attempt("background_image", () => uploadBackground(backgroundFile));
        if (result) setBackgroundFile(current => current === backgroundFile ? null : current);
        else prefsOk = false;
      } else if (removeBg && prefs.background.mode === "upload") {
        const result = await attempt(null, () => removeBackground());
        if (result !== undefined) setRemoveBg(false);
        else prefsOk = false;
      }
    }

    const prefsPatch = Object.fromEntries(Object.entries(prefsChanges(prefsD, prefs) ?? {}).filter(([key]) => PREF_SCOPE[scope].includes(key)));
    if (Object.keys(prefsPatch).length) {
      const updated = await attempt(null, () => patchPreferences(prefsPatch));
      if (!updated) prefsOk = false;
    }

    /* Whatever happened, show what the server now holds. */
    if (didSomething) {
      try {
        const fresh = await qc.fetchQuery({
          queryKey: keys.preferences(),
          queryFn: fetchPreferences,
          staleTime: 0,
        });
        if (scope === "appearance") {
          applyBackground(fresh.background);
          applyDimming(fresh.background_dimming);
          syncHeaderDimming(fresh.background_dimming);
        }
        applyPrefs(fresh);
        if (prefsOk) setPrefsD((draft) => {
          const next = prefsDraft(fresh);
          return { ...draft, ...Object.fromEntries(DRAFT_SCOPE[scope].map((key) => [key, draft[key] === prefsD[key] ? next[key] : draft[key]])) };
        });
        if (scope === "account" && avatarFile === null) applyAvatar(fresh.avatar_url);
        await refreshBootstrapProfile();
      } catch {
        /* the next page load will catch up */
      }
    }

    setErrors(found);
    setSaving(false);
    if (Object.keys(found).length || general.length || !accountOk) {
      setSaveFailed(true);
      toast.error(general[0] ?? "Some changes could not be saved. Check the highlighted fields.");
    } else if (didSomething && !automatic) {
      toast.success({ account: "Account saved.", appearance: "Appearance saved.", defaults: "Reporting defaults saved.", search: "Search preferences saved.", ai: "AI connections saved." }[scope]);
    } else if (!automatic) {
      toast.info("No changes to save.");
    }
  };

  const customAvatar = hasCustomAvatar(prefs.avatar_url);
  const dirty = (scope: SaveScope) => DRAFT_SCOPE[scope].some(key => prefsD[key] !== prefsDraft(prefs)[key]) || (scope === "account" && !!(accountChanges(accountD, account) || avatarFile)) || (scope === "appearance" && !!(backgroundFile || removeBg));
  const lastAttempt = useRef("");
  const fingerprint = JSON.stringify([accountD, prefsD, avatarFile?.name, avatarFile?.lastModified, backgroundFile?.name, backgroundFile?.lastModified, removeBg]);
  const pendingScope = (["account", "appearance", "defaults", "search", "ai"] as const).find(dirty);
  useEffect(() => {
    if (saving || !pendingScope || lastAttempt.current === `${pendingScope}:${fingerprint}`) return;
    const timer = window.setTimeout(() => {
      lastAttempt.current = `${pendingScope}:${fingerprint}`;
      void onSubmit(undefined, pendingScope, true);
    }, 800);
    return () => window.clearTimeout(timer);
  }, [section, saving, fingerprint, pendingScope, retryVersion]);
  const Defaults = "form";
  const Root = section === "ai" ? "form" : "div";
  const dateRanges = [
    {
      id: "default_filter",
      label: "Date range",
      valueKey: "filterValue",
      unitKey: "filterUnit",
      error: "default_filter_value",
      hint: "Review and other date-filtered pages",
    },
    {
      id: "insights_default_filter",
      label: "Insights date range",
      valueKey: "insightsValue",
      unitKey: "insightsUnit",
      error: "insights_default_filter_value",
    },
  ] as const;

  return (
    <>
      <Root className="fields profile-page" onSubmit={section === "ai" ? (event: FormEvent) => void onSubmit(event, "ai") : undefined}>
        {saveFailed || saving || pendingScope || lastAttempt.current ? <div className="settings-autosave" role="status">{saveFailed ? "Not saved" : saving ? "Saving" : pendingScope ? "Waiting to save" : "Saved automatically"}{saveFailed || Object.keys(errors).length ? <button className="btn btn--quiet" type="button" onClick={() => { lastAttempt.current = ""; setErrors({}); setSaveFailed(false); setRetryVersion(value => value + 1); }}>Retry saving</button> : null}</div> : null}
        {section === "account" ? <>
        <form className="slab slab-pad" onSubmit={(event) => void onSubmit(event, "account")} noValidate>
          <div className="profile-account-grid">
            <div className="profile-avatar-panel">
              {avatarPreview || customAvatar ? <img
                className="profile-pic profile-avatar-large"
                src={avatarPreview ?? prefs.avatar_url}
                alt={`${account.username} profile picture`}
              /> : <span className="profile-avatar-monogram">{account.username.slice(0, 1).toUpperCase()}</span>}
              <div className="field">
                <button type="button" className="btn btn--quiet profile-avatar-upload" onClick={() => document.getElementById("avatar_image")?.click()}>Change photo</button>
                <input
                  id="avatar_image"
                  aria-label="Profile photo"
                  hidden
                  type="file"
                  accept="image/*"
                  onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)}
                />
                {avatarFile ? <small className="muted">{avatarFile.name}</small> : null}
                <FieldErrors lines={errors.avatar_image} />
              </div>
              {customAvatar && !avatarFile ? (
                <div className="profile-avatar-actions">
                  <button type="button" className="btn btn--quiet" onClick={onRemoveAvatar}>
                    <Icon icon={faTrash} /> Remove image
                  </button>
                </div>
              ) : null}
            </div>

            <div>
              <div className="two-up">
                <div className="field">
                  <label htmlFor="username">Username</label>
                  <input
                    id="username"
                    type="text"
                    autoComplete="username"
                    value={accountD.username}
                    onChange={(event) => setAccountD({ ...accountD, username: event.target.value })}
                  />
                  <FieldErrors lines={errors.username} />
                </div>
                <div className="field">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    value={accountD.email}
                    onChange={(event) => setAccountD({ ...accountD, email: event.target.value })}
                  />
                  <FieldErrors lines={errors.email} />
                </div>
              </div>
              <div className="two-up">
                <div className="field">
                  <label htmlFor="first_name">First name</label>
                  <input
                    id="first_name"
                    type="text"
                    autoComplete="given-name"
                    value={accountD.first_name}
                    onChange={(event) =>
                      setAccountD({
                        ...accountD,
                        first_name: event.target.value,
                      })
                    }
                  />
                  <FieldErrors lines={errors.first_name} />
                </div>
                <div className="field">
                  <label htmlFor="last_name">Last name</label>
                  <input
                    id="last_name"
                    type="text"
                    autoComplete="family-name"
                    value={accountD.last_name}
                    onChange={(event) =>
                      setAccountD({
                        ...accountD,
                        last_name: event.target.value,
                      })
                    }
                  />
                  <FieldErrors lines={errors.last_name} />
                </div>
              </div>
              <div className="field">
                <label htmlFor="timezone">Timezone</label>
                <input
                  id="timezone"
                  type="text"
                  list="timezone-names"
                  maxLength={64}
                  autoComplete="off"
                  value={prefsD.timezone}
                  onChange={(event) => patchPrefsDraft({ timezone: event.target.value })}
                />
                <datalist id="timezone-names">
                  {zones.map((zone) => (
                    <option key={zone} value={zone} />
                  ))}
                </datalist>
                <small className="muted">
                  Used for your day, dates and reminders.
                  {device && device !== prefsD.timezone ? (
                    <>
                      {" "}
                      <button
                        type="button"
                        className="btn btn--quiet"
                        onClick={() => patchPrefsDraft({ timezone: device })}
                      >
                        Use this device ({device})
                      </button>
                    </>
                  ) : null}
                </small>
                <FieldErrors lines={errors.timezone} />
              </div>
            </div>
          </div>
        </form>

        <SocialSection social={social} />
        </> : null}

        {section === "appearance" ? <form className="profile-appearance" onSubmit={(event) => void onSubmit(event, "appearance")} noValidate>
        <BackgroundSection
          prefs={prefs}
          draft={prefsD}
          onDraft={patchPrefsDraft}
          file={backgroundFile}
          onFile={setBackgroundFile}
          removeCurrent={removeBg}
          onRemoveCurrent={setRemoveBg}
          errors={errors}
        />
        </form> : null}

        {section === "defaults" || (section === "search" && prefs.ai_features_enabled && prefs.configured_api_keys.openai) ? <Defaults className="slab slab-pad" onSubmit={(event: FormEvent) => { event.stopPropagation(); void onSubmit(event, section === "search" ? "search" : "defaults"); }}>
          {section === "search" ? <SlabHead title="Related search" /> : null}
          <div className="profile-defaults-grid">
            {section === "defaults" ? dateRanges.map((range) => {
              const unit = prefsD[range.unitKey];
              return (
                <div key={range.id} className="profile-default-item">
                  <label htmlFor={`${range.id}_value`}>{range.label}</label>
                  <div className={`profile-default-control${isToDate(unit) ? " to-date-range" : ""}`}>
                    <input
                      id={`${range.id}_value`}
                      type="number"
                      min={1}
                      max={1000}
                      className="profile-default-number profile-default-value"
                      value={prefsD[range.valueKey]}
                      disabled={isToDate(unit)}
                      onChange={(event) =>
                        patchPrefsDraft({
                          [range.valueKey]: event.target.value,
                        })
                      }
                    />
                    <select
                      aria-label={`${range.label} unit`}
                      className="profile-default-select profile-default-unit"
                      value={unit}
                      onChange={(event) =>
                        patchPrefsDraft({
                          [range.unitKey]: event.target.value,
                        } as Partial<PrefsDraft>)
                      }
                    >
                      {FILTER_UNITS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {!isToDate(option.value) && Number(prefsD[range.valueKey]) === 1 ? option.label.replace(/s$/, "") : option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  {"hint" in range ? <p className="muted">{range.hint}</p> : null}
                  <FieldErrors lines={[...(errors[range.error] ?? []), ...(errors[`${range.id}_unit`] ?? [])]} />
                </div>
              );
            }) : null}

            {section === "defaults" ? <div className="profile-default-item">
              <label htmlFor="default_chart_project_count">Projects per chart</label>
              <div className="profile-default-control">
                <input
                  id="default_chart_project_count"
                  type="number"
                  min={1}
                  max={100}
                  className="profile-default-number"
                  value={prefsD.chartCount}
                  onChange={(event) => patchPrefsDraft({ chartCount: event.target.value })}
                />
                <span className="muted">projects</span>
              </div>
              <p className="muted">The rest are grouped as Other (max 100)</p>
              <FieldErrors lines={errors.default_chart_project_count} />
            </div> : null}

            {section === "search" && prefs.ai_features_enabled && prefs.configured_api_keys.openai ? (
              <div className="profile-default-item profile-default-item--wide">
                <SimilaritySlider
                  title="Related search closeness"
                  value={prefsD.similarity}
                  defaultValue={prefs.related_similarity_default}
                  defaultLabel="Autumn's default"
                  scale={{
                    ...similarityScale(),
                    floor: prefs.related_similarity_min,
                    ceiling: prefs.related_similarity_max,
                  }}
                  immediate
                  onCommit={(similarity) => patchPrefsDraft({ similarity })}
                />
                <p className="muted">
                  Where the Related slider starts on every search. Lower finds more, looser matches; higher keeps only
                  close ones.
                </p>
                <FieldErrors lines={errors.related_similarity} />
              </div>
            ) : null}
          </div>
        </Defaults> : null}

        {section === "search" && (!prefs.ai_features_enabled || !prefs.configured_api_keys.openai) ? <p className="slab slab-pad">Connect an OpenAI API key in <AppLink className="btn btn--quiet" href="/settings/ai/">AI connections</AppLink> to find related sessions by meaning.</p> : null}
        {section === "ai" && !prefs.ai_features_enabled ? <p className="slab slab-pad">AI features are turned off on this Autumn instance. Connected apps can still be managed below.</p> : null}
        {section === "ai" && prefs.ai_features_enabled ? (
          <AiSection
            prefs={prefs}
            luna={prefsD.luna}
            onLuna={(luna) => patchPrefsDraft({ luna })}
            errors={errors}
          />
        ) : null}

      </Root>

      {section === "ai" ? <section className="slab slab-pad">
        <div className="profile-codex-panel">
          <div>
            <h2 className="disclose-title">Autumn MCP</h2>
            <p className="focus-lede">Let ChatGPT, Claude and other MCP apps use your Autumn data.</p>
          </div>
          <div className="form-actions">
            <AppLink className="btn btn--ghost" href={urls.mcpConnections()}>
              <Icon icon={faPlug} /> Manage connections
            </AppLink>
          </div>
        </div>
      </section> : null}
      <SocialConnectForms accounts={social.accounts} />
    </>
  );
}
