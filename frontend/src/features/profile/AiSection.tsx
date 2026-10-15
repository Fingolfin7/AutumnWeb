import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  faCheckCircle,
  faCircle,
  faKey,
  faLock,
  faSignInAlt,
  faSyncAlt,
  faUnlink,
} from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { ErrorState } from "@/components/states";
import { useToast } from "@/app/toasts";
import { keys } from "@/api/keys";
import { errorMessage } from "@/api/errors";
import { disconnectChatGPT, meKeys, startChatGPTLogin, useChatGPTLogin, useOnCodexConnected } from "./api";
import { KEY_PROVIDERS, LUNA_EFFORTS, type KeyDraft, type KeyProvider, type LunaEffort, type Prefs } from "./model";
import { FieldErrors, SlabHead } from "./Parts";

const KEY_LABELS: Record<KeyProvider, string> = {
  gemini: "Gemini",
  openai: "OpenAI API key",
  claude: "Claude",
};

/* "LLM connections": the Codex device login and write-only API keys. Keys are
   never shown, only whether one is stored. They are sent with Update profile;
   the Codex buttons act immediately, as they did. */
export function AiSection({
  prefs,
  keyDrafts,
  onKeyDraft,
  luna,
  onLuna,
  errors,
}: {
  prefs: Prefs;
  keyDrafts: Record<KeyProvider, KeyDraft>;
  onKeyDraft: (provider: KeyProvider, patch: Partial<KeyDraft>) => void;
  luna: LunaEffort;
  onLuna: (value: LunaEffort) => void;
  errors: Record<string, string[]>;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const login = useChatGPTLogin(true);
  const configured = prefs.configured_api_keys;

  const onConnected = useCallback(() => toast.success("Connected Codex login for Insights."), [toast]);
  useOnCodexConnected(login.data, onConnected);

  const setLogin = (data: unknown) => qc.setQueryData(meKeys.chatgpt(), data);
  const refreshPrefs = () => void qc.invalidateQueries({ queryKey: keys.preferences() });

  const start = useMutation({
    mutationFn: startChatGPTLogin,
    onSuccess: (data) => {
      setLogin(data);
      toast.success("Codex login started. Use the code shown below, then complete the login.");
    },
    onError: (error) => toast.error(`Could not start Codex login: ${errorMessage(error)}`),
  });
  const disconnect = useMutation({
    mutationFn: disconnectChatGPT,
    onSuccess: () => {
      setLogin({ status: "disconnected" });
      refreshPrefs();
      toast.success("Disconnected OpenAI Codex login.");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const complete = useMutation({
    mutationFn: async () => {
      const result = await login.refetch({ throwOnError: true });
      return result.data;
    },
    onSuccess: (data) => {
      if (data?.status === "pending") {
        toast.info("Still waiting for OpenAI authorization. Try Complete again after entering the code.");
      }
    },
    onError: (error) => toast.error(`Could not complete Codex login: ${errorMessage(error)}`),
  });

  const status = login.data?.status;
  const connected = status === "connected" || (status === undefined && configured.openai_chatgpt);
  const pending = status === "pending" ? login.data : null;

  return (
    <section className="slab slab-pad">
      <SlabHead
        title="LLM connections"
        aside={
          <span className="muted">
            <Icon icon={faLock} /> Encrypted at rest
          </span>
        }
      />

      <div className="profile-codex-panel">
        <div>
          <h3 className="disclose-title">Codex login</h3>
          <p className="focus-lede">OpenAI models use Codex first, then the API key below.</p>
          {connected ? (
            <span className="context-chip text-green">
              <Icon icon={faCheckCircle} /> Codex connected
              {login.data?.email ? ` as ${login.data.email}` : ""}
              {login.data?.plan ? ` (${login.data.plan})` : ""}
            </span>
          ) : (
            <span className="context-chip">
              <Icon icon={faCircle} /> Codex not connected
            </span>
          )}
        </div>
        <div className="form-actions">
          {connected ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
            >
              <Icon icon={faUnlink} /> Disconnect Codex
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => start.mutate()}
              disabled={start.isPending || login.isPending}
            >
              <Icon icon={faSignInAlt} /> {pending ? "Start over" : "Use Codex login"}
            </button>
          )}
        </div>
      </div>

      {login.isError && !pending ? (
        <div className="u-mt-4">
          <ErrorState error={login.error} />
        </div>
      ) : null}

      {pending ? (
        <div className="msg msg--info u-mt-4">
          <Icon icon={faKey} className="msg-icon" />
          <div>
            <span>
              Open{" "}
              <a className="text-cyan" href={pending.verification_url} target="_blank" rel="noopener noreferrer">
                {pending.verification_url}
              </a>{" "}
              and enter:
            </span>{" "}
            <strong className="mono text-orange">{pending.user_code}</strong>
            <p className="muted profile-codex-code">Autumn checks for the authorization every few seconds.</p>
            <button
              type="button"
              className="btn btn--primary u-mt-4"
              onClick={() => complete.mutate()}
              disabled={complete.isPending}
            >
              <Icon icon={faSyncAlt} spin={complete.isPending} /> Complete Codex login
            </button>
          </div>
        </div>
      ) : null}

      <div className="profile-keys-grid">
        {KEY_PROVIDERS.map((provider) => {
          const stored = configured[provider];
          const draft = keyDrafts[provider];
          return (
            <div key={provider} className="profile-key-item">
              <div className="u-between u-gap-3">
                <label htmlFor={`${provider}_api_key`}>{KEY_LABELS[provider]}</label>
                <span>
                  {stored ? (
                    <span className="text-green">{provider === "openai" ? "Fallback stored" : "Stored"}</span>
                  ) : (
                    <span className="text-red">None</span>
                  )}
                </span>
              </div>
              <input
                type="password"
                id={`${provider}_api_key`}
                autoComplete="new-password"
                placeholder={`${provider === "openai" ? "OpenAI" : provider === "gemini" ? "Gemini" : "Claude"} API Key`}
                value={draft.value}
                disabled={draft.clear}
                onChange={(event) => onKeyDraft(provider, { value: event.target.value })}
              />
              {provider === "openai" ? (
                <small className="muted">
                  {connected
                    ? "Used after Codex if the Codex bucket is unavailable."
                    : "Paste an OpenAI API key to enable OpenAI models."}
                </small>
              ) : null}
              <div className="check-row">
                <input
                  type="checkbox"
                  id={`clear_${provider}_api_key`}
                  checked={draft.clear}
                  onChange={(event) =>
                    onKeyDraft(provider, {
                      clear: event.target.checked,
                      value: "",
                    })
                  }
                />
                <label htmlFor={`clear_${provider}_api_key`}>Clear key</label>
              </div>
              <FieldErrors lines={errors[`key_${provider}`]} />
            </div>
          );
        })}
      </div>

      <div className="profile-default-item profile-luna">
        <label htmlFor="luna_recommendation_effort">Luna recommendation effort</label>
        <select
          id="luna_recommendation_effort"
          value={luna}
          onChange={(event) => onLuna(event.target.value as LunaEffort)}
        >
          {LUNA_EFFORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="muted">How hard Luna thinks when suggesting timers</p>
        <FieldErrors lines={errors.luna_recommendation_effort} />
      </div>
    </section>
  );
}
