import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { faCheckCircle, faPlug, faTrash } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ErrorState, Skeleton } from "@/components/states";
import { AppLink, urls } from "@/app/links";
import { useToast } from "@/app/toasts";
import { bootstrap } from "@/bootstrap";
import { keys } from "@/api/keys";
import { ApiError, errorMessage } from "@/api/errors";
import {
  deleteApiKey,
  fetchPreferences,
  meKeys,
  patchAccount,
  patchPreferences,
  putApiKey,
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
  keyActions,
  prefsChanges,
  prefsDraft,
  timeZoneNames,
  validatePrefs,
  type Account,
  type AccountDraft,
  type KeyDraft,
  type KeyProvider,
  type Prefs,
  type PrefsDraft,
} from "./model";
import { AiSection } from "./AiSection";
import { BackgroundSection } from "./BackgroundSection";
import { FieldErrors, SlabHead } from "./Parts";
import { applyAvatar, applyBackground, applyDimming, applyPrefs, refreshBootstrapProfile, syncHeaderDimming } from "./shell";
import { SocialConnectForms, SocialSection } from "./SocialSection";
import "./profile.css";

/* Profile (users/templates/users/profile.html): account, avatar, backdrop,
   defaults, LLM connections, connected logins. */
export default function ProfilePage() {
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
          <h1 className="page-title">Profile</h1>
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
        <ProfileEditor account={account.data} prefs={prefs.data} social={social.data ?? { accounts: [], has_usable_password: true }} />
      ) : (
        <section className="slab slab-pad">
          <Skeleton lines={6} />
        </section>
      )}
    </>
  );
}

const EMPTY_KEYS: Record<KeyProvider, KeyDraft> = {
  gemini: { value: "", clear: false },
  openai: { value: "", clear: false },
  claude: { value: "", clear: false },
};

function ProfileEditor({
  account,
  prefs,
  social,
}: {
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
  const [keyDrafts, setKeyDrafts] = useState(EMPTY_KEYS);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);

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

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (saving) return;

    const invalid = validatePrefs(prefsD);
    if (Object.keys(invalid).length) {
      setErrors(Object.fromEntries(Object.entries(invalid).map(([field, message]) => [field, [message]])));
      toast.error("Please fix the highlighted fields.");
      return;
    }

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

    if (avatarFile) {
      const result = await attempt("avatar_image", () => uploadAvatar(avatarFile));
      if (result) {
        applyAvatar(result.url ?? "");
        setAvatarFile(null);
      }
    }

    const accountPatch = accountChanges(accountD, account);
    let newAccount: Account | undefined;
    if (accountPatch) {
      newAccount = await attempt(null, () => patchAccount(accountPatch));
      accountOk = !!newAccount;
      if (newAccount) {
        qc.setQueryData(meKeys.account(), newAccount);
        bootstrap().user.username = newAccount.username;
        bootstrap().user.email = newAccount.email;
        setAccountD(accountDraft(newAccount));
      }
    }

    if (!prefsD.automatic) {
      if (backgroundFile) {
        const result = await attempt("background_image", () => uploadBackground(backgroundFile));
        if (result) setBackgroundFile(null);
        else prefsOk = false;
      } else if (removeBg && prefs.background.mode === "upload") {
        const result = await attempt(null, () => removeBackground());
        if (result !== undefined) setRemoveBg(false);
        else prefsOk = false;
      }
    }

    const prefsPatch = prefsChanges(prefsD, prefs);
    if (prefsPatch) {
      const updated = await attempt(null, () => patchPreferences(prefsPatch));
      if (!updated) prefsOk = false;
    }

    if (prefs.ai_features_enabled) {
      for (const item of keyActions(keyDrafts)) {
        const result = await attempt(`key_${item.provider}`, () =>
          item.action === "clear" ? deleteApiKey(item.provider) : putApiKey(item.provider, item.key ?? ""),
        );
        if (result)
          setKeyDrafts((current) => ({
            ...current,
            [item.provider]: { value: "", clear: false },
          }));
      }
    }

    /* Whatever happened, show what the server now holds. */
    if (didSomething) {
      try {
        const fresh = await qc.fetchQuery({
          queryKey: keys.preferences(),
          queryFn: fetchPreferences,
          staleTime: 0,
        });
        applyBackground(fresh.background);
        applyDimming(fresh.background_dimming);
        syncHeaderDimming(fresh.background_dimming);
        applyPrefs(fresh);
        if (prefsOk) setPrefsD(prefsDraft(fresh));
        if (avatarFile === null) applyAvatar(fresh.avatar_url);
        await refreshBootstrapProfile();
      } catch {
        /* the next page load will catch up */
      }
    }

    setErrors(found);
    setSaving(false);
    if (Object.keys(found).length || general.length || !accountOk) {
      toast.error(general[0] ?? "Some changes could not be saved. Check the highlighted fields.");
    } else if (didSomething) {
      toast.success("Profile updated successfully.");
    } else {
      toast.info("No changes to save.");
    }
  };

  const customAvatar = hasCustomAvatar(prefs.avatar_url);
  const dateRanges = [
    {
      id: "default_filter",
      label: "Date range",
      valueKey: "filterValue",
      unitKey: "filterUnit",
      error: "default_filter_value",
      hint: "Charts and other date-filtered pages",
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
      <form className="fields profile-page" onSubmit={onSubmit} noValidate>
        <section className="slab slab-pad">
          <div className="profile-account-grid">
            <div className="profile-avatar-panel">
              <img
                className="profile-pic profile-avatar-large"
                src={avatarPreview ?? prefs.avatar_url}
                alt={`${account.username} profile picture`}
              />
              <div className="field">
                <label htmlFor="avatar_image">Profile image</label>
                <input
                  id="avatar_image"
                  type="file"
                  accept="image/*"
                  onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)}
                />
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
                  IANA timezone name, for example Europe/Prague.
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
        </section>

        <SocialSection social={social} />

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

        <section className="slab slab-pad">
          <SlabHead title="Defaults" />
          <div className="profile-defaults-grid">
            {dateRanges.map((range) => {
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
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  {"hint" in range ? <p className="muted">{range.hint}</p> : null}
                  <FieldErrors lines={[...(errors[range.error] ?? []), ...(errors[`${range.id}_unit`] ?? [])]} />
                </div>
              );
            })}

            <div className="profile-default-item">
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
            </div>
          </div>
        </section>

        {prefs.ai_features_enabled ? (
          <AiSection
            prefs={prefs}
            keyDrafts={keyDrafts}
            onKeyDraft={(provider, patch) =>
              setKeyDrafts((current) => ({
                ...current,
                [provider]: { ...current[provider], ...patch },
              }))
            }
            luna={prefsD.luna}
            onLuna={(luna) => patchPrefsDraft({ luna })}
            errors={errors}
          />
        ) : null}

        <div className="form-actions profile-submit-row">
          <button type="submit" className="btn btn--primary btn--lg" disabled={saving}>
            <Icon icon={faCheckCircle} /> {saving ? "Saving..." : "Update profile"}
          </button>
        </div>
      </form>

      <section className="slab slab-pad">
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
      </section>
      <SocialConnectForms accounts={social.accounts} />
    </>
  );
}
