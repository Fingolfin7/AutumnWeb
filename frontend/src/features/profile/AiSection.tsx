import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
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
import { deleteApiKey, disconnectChatGPT, meKeys, putApiKey, startChatGPTLogin, useChatGPTLogin, useOnCodexConnected } from "./api";
import {
  KEY_PROVIDERS,
  LUNA_EFFORTS,
  openaiKeyBadge,
  openaiKeyNote,
  type KeyProvider,
  type LunaEffort,
  type Prefs,
} from "./model";
import { FieldErrors, SlabHead } from "./Parts";

const KEY_LABELS: Record<KeyProvider, string> = {
  gemini: "Gemini",
  openai: "OpenAI API key",
  claude: "Claude",
};

/* Keys are write-only and each provider has its own explicit action. */
export function AiSection({
  prefs,
  luna,
  onLuna,
  errors,
}: {
  prefs: Prefs;
  luna: LunaEffort;
  onLuna: (value: LunaEffort) => void;
  errors: Record<string, string[]>;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const login = useChatGPTLogin(true);
  const configured = prefs.configured_api_keys;
  const [keyDrafts, setKeyDrafts] = useState<Record<KeyProvider, string>>({ gemini: "", openai: "", claude: "" });
  const [keyErrors, setKeyErrors] = useState<Partial<Record<KeyProvider, string>>>({});
  const keyChange = useMutation({
    mutationFn: ({ provider, clear }: { provider: KeyProvider; clear: boolean }) => clear ? deleteApiKey(provider) : putApiKey(provider, keyDrafts[provider].trim()),
    onSuccess: (_result, { provider, clear }) => {
      setKeyDrafts(current => ({ ...current, [provider]: "" }));
      setKeyErrors(current => ({ ...current, [provider]: undefined }));
      void qc.invalidateQueries({ queryKey: keys.preferences() });
      toast.success(clear ? `${KEY_LABELS[provider]} removed.` : `${KEY_LABELS[provider]} connected.`);
    },
    onError: (error, { provider }) => setKeyErrors(current => ({ ...current, [provider]: errorMessage(error) })),
  });

  const onConnected = useCallback(() => toast.success("Connected Codex for Insights."), [toast]);
  useOnCodexConnected(login.data, onConnected);

  const setLogin = (data: unknown) => qc.setQueryData(meKeys.chatgpt(), data);
  const refreshPrefs = () => void qc.invalidateQueries({ queryKey: keys.preferences() });

  const start = useMutation({
    mutationFn: startChatGPTLogin,
    onSuccess: (data) => {
      setLogin(data);
      toast.success("Use the code below to connect Codex.");
    },
    onError: (error) => toast.error(`Could not connect Codex: ${errorMessage(error)}`),
  });
  const disconnect = useMutation({
    mutationFn: disconnectChatGPT,
    onSuccess: () => {
      setLogin({ status: "disconnected" });
      refreshPrefs();
      toast.success("Disconnected Codex.");
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
    onError: (error) => toast.error(`Could not finish connecting Codex: ${errorMessage(error)}`),
  });

  const status = login.data?.status;
  const connected = status === "connected" || (status === undefined && configured.openai_chatgpt);
  const pending = status === "pending" ? login.data : null;
  const openaiBadge = openaiKeyBadge(configured, prefs.openai_source);
  const openaiNote = openaiKeyNote(configured, prefs.openai_source, connected);

  return (
    <section className="slab slab-pad">
      <SlabHead
        title="AI providers"
        aside={
          <span className="muted">
            <Icon icon={faLock} /> Encrypted at rest
          </span>
        }
      />

      <div className="profile-provider-list" aria-label="Provider connections">{KEY_PROVIDERS.map(provider => <details className="profile-provider" key={provider}>
        <summary><strong>{KEY_LABELS[provider]}</strong><span>{configured[provider] ? "Connected" : provider === "openai" && connected ? "Via Codex" : "Not connected"}</span><span className="profile-provider-action">{configured[provider] ? "Manage" : "Connect"}</span></summary>
        <div className="field"><label htmlFor={`${provider}_api_key`}>API key</label><input type="password" id={`${provider}_api_key`} autoComplete="new-password" value={keyDrafts[provider]} onChange={event => setKeyDrafts(current => ({ ...current, [provider]: event.target.value }))} placeholder={`Paste ${KEY_LABELS[provider]} key`} />
          {provider === "openai" ? <small className="muted">{openaiNote === "after-codex" ? "Used after Codex if its quota is unavailable." : openaiNote === "server-needs-profile" ? "The server key is available, but Insights needs a profile key or Codex login." : openaiNote === "server-available" ? "Insights can use the server key; your own key overrides it." : "A profile key can be used for Insights and related search."} {openaiBadge.label}</small> : null}
          {keyErrors[provider] ? <p role="alert" className="text-red">{keyErrors[provider]}</p> : null}
          <div className="form-actions"><button type="button" className="btn btn--secondary" disabled={!keyDrafts[provider].trim() || keyChange.isPending} onClick={() => keyChange.mutate({ provider, clear: false })}>Save key</button>{configured[provider] ? <button type="button" className="btn btn--quiet" disabled={keyChange.isPending} onClick={() => keyChange.mutate({ provider, clear: true })}>Remove key</button> : null}</div>
        </div></details>)}</div>
      <div className="profile-codex-row">
          <strong>Codex</strong>
          <span>{connected ? `Connected${login.data?.email ? ` as ${login.data.email}` : ""}${login.data?.plan ? ` (${login.data.plan})` : ""}` : "Not connected"}</span>
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
              <Icon icon={faSignInAlt} /> {pending ? "Start over" : "Connect Codex"}
            </button>
          )}
      </div>
      <p className="muted profile-codex-hint">OpenAI models use Codex first, then your API key.</p>

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
              className="btn btn--secondary u-mt-4"
              onClick={() => complete.mutate()}
              disabled={complete.isPending}
            >
              <Icon icon={faSyncAlt} spin={complete.isPending} /> Finish connecting
            </button>
          </div>
        </div>
      ) : null}

      <details className="profile-ai-advanced"><summary>Model effort</summary>
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
    </details>
    </section>
  );
}
