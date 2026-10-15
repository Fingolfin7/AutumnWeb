import { useMutation, useQueryClient } from "@tanstack/react-query";
import { faCheckCircle, faExclamationCircle, faLink, faUnlink } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { csrfToken } from "@/lib/csrf";
import { disconnectSocial, meKeys, type SocialAccount } from "./api";
import { brandIcons } from "./brands";
import { SlabHead } from "./Parts";

/* Connected Google / GitHub logins. Changes apply immediately, as before.
   Connecting is a real form POST to the provider's login URL with
   process=connect (allauth refuses GET), which leaves the app for the
   provider's consent screen. */
export function SocialSection({ accounts }: { accounts: SocialAccount[] }) {
  const toast = useToast();
  const qc = useQueryClient();
  const disconnect = useMutation({
    mutationFn: (provider: string) => disconnectSocial(provider),
    onSuccess: (_data, provider) => {
      const name = accounts.find((account) => account.provider === provider)?.name ?? provider;
      toast.success(`${name} account disconnected.`);
      void qc.invalidateQueries({ queryKey: meKeys.social() });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!accounts.length) return null;
  return (
    <section className="slab slab-pad">
      <SlabHead title="Connected accounts" aside={<span className="muted">Changes apply immediately</span>} />
      <ul className="profile-auth-list">
        {accounts.map((account) => {
          const brand = brandIcons[account.provider];
          return (
            <li key={account.provider} className="profile-auth-panel">
              <div>
                <h3 className="disclose-title profile-auth-name">
                  {brand ? <Icon icon={brand} className="profile-auth-icon" /> : null}
                  {account.name}
                </h3>
                {account.connected ? (
                  <>
                    {!account.available ? (
                      <p className="focus-lede">
                        {account.name} is no longer configured on this Autumn instance, so it cannot log you in until an
                        administrator sets it up again.
                      </p>
                    ) : null}
                    <span
                      className={`context-chip profile-auth-chip ${account.available ? "text-green" : "text-yellow"}`}
                    >
                      <Icon icon={account.available ? faCheckCircle : faExclamationCircle} />
                      Connected
                      {account.identity ? ` as ${account.identity}` : ""}
                    </span>
                  </>
                ) : null}
              </div>
              <div className="form-actions">
                {account.connected ? (
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={disconnect.isPending}
                    onClick={() => disconnect.mutate(account.provider)}
                  >
                    <Icon icon={faUnlink} /> Disconnect {account.name}
                  </button>
                ) : account.available && account.login_url ? (
                  <button type="submit" form={`social-connect-${account.provider}`} className="btn btn--ghost">
                    <Icon icon={faLink} /> Connect {account.name}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* Owners for the Connect buttons, rendered outside the profile form (forms
   cannot nest); the buttons submit them through the `form` attribute, so an
   unsaved edit is never carried along. */
export function SocialConnectForms({ accounts }: { accounts: SocialAccount[] }) {
  return (
    <>
      {accounts
        .filter((account) => !account.connected && account.available && account.login_url)
        .map((account) => (
          <form
            key={account.provider}
            id={`social-connect-${account.provider}`}
            method="post"
            action={account.login_url ?? ""}
          >
            <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
            <input type="hidden" name="process" value="connect" />
          </form>
        ))}
    </>
  );
}
