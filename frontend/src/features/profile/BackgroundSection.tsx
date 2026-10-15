import { useEffect, useMemo } from "react";
import { faDownload, faExternalLinkAlt, faPlay } from "@fortawesome/free-solid-svg-icons";
import { Icon } from "@/components/Icon";
import { useToast } from "@/app/toasts";
import { errorMessage } from "@/api/errors";
import { downloadBackground } from "./api";
import { applyDimming } from "./shell";
import { backgroundCredit, backgroundLinkLabel, DIM_MAX, type BackgroundChoice, type Prefs, type PrefsDraft } from "./model";
import { FieldErrors, SlabHead } from "./Parts";

/* Workspace backdrop: automatic Bing / NASA picture, or an uploaded image,
   plus dimming. Mirrors the "Background" slab of users/profile.html. */
export function BackgroundSection({
  prefs,
  draft,
  onDraft,
  file,
  onFile,
  removeCurrent,
  onRemoveCurrent,
  errors,
}: {
  prefs: Prefs;
  draft: PrefsDraft;
  onDraft: (patch: Partial<PrefsDraft>) => void;
  file: File | null;
  onFile: (file: File | null) => void;
  removeCurrent: boolean;
  onRemoveCurrent: (value: boolean) => void;
  errors: Record<string, string[]>;
}) {
  const toast = useToast();
  const mode = prefs.background.mode;
  const credit = backgroundCredit(prefs.background);
  const uploaded = mode === "upload" ? prefs.background.image_url : null;

  const download = async () => {
    try {
      await downloadBackground();
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const choices: { value: Exclude<BackgroundChoice, "">; label: string }[] = [
    { value: "bing", label: "Bing daily wallpaper" },
    { value: "nasa", label: "NASA picture of the day" },
  ];

  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => (preview ? URL.revokeObjectURL(preview) : undefined), [preview]);

  return (
    <section className="slab slab-pad">
      <SlabHead
        title="Background"
        aside={
          <div>
            <div className="check-row">
              <input
                type="checkbox"
                id="automatic_background"
                checked={draft.automatic}
                onChange={(event) => onDraft({ automatic: event.target.checked })}
              />
              <label htmlFor="automatic_background">Automatic background</label>
            </div>
            <FieldErrors lines={errors.automatic_background} />
          </div>
        }
      />

      {draft.automatic ? (
        <div id="automatic_background_options" className="profile-background-options">
          {choices.map((choice) => (
            <label key={choice.value} className="profile-choice-pill">
              <input
                type="radio"
                name="background_choice"
                value={choice.value}
                checked={draft.choice === choice.value}
                onChange={() => onDraft({ choice: choice.value })}
              />
              <span>{choice.label}</span>
            </label>
          ))}
          <FieldErrors lines={errors.background ?? errors.bing_background ?? errors.nasa_apod_background} />
        </div>
      ) : null}

      <div className="profile-background-tuning">
        <div className="u-between u-gap-3">
          <label htmlFor="background_dimming">Dimming</label>
          <output id="background-dimming-value" className="mono text-cyan" htmlFor="background_dimming">
            {draft.dimming}%
          </output>
        </div>
        <input
          type="range"
          id="background_dimming"
          className="background-dimming-slider"
          min={0}
          max={DIM_MAX}
          step={5}
          value={draft.dimming}
          onChange={(event) => {
            const value = Number(event.target.value);
            onDraft({ dimming: value });
            applyDimming(value);
          }}
        />
        <FieldErrors lines={errors.background_dimming} />
      </div>

      {draft.automatic && prefs.automatic_background ? (
        <div className="background-context profile-background-context">
          {mode === "bing" || mode === "apod" ? (
            <>
              <h3 className="disclose-title">
                {prefs.background.title ?? (mode === "bing" ? "Bing daily wallpaper" : "NASA picture of the day")}
              </h3>
              {credit ? <p className="focus-lede">{credit}</p> : null}
              {prefs.background.source_url ? (
                <a
                  className="btn btn--ghost u-mt-4"
                  href={prefs.background.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Icon icon={prefs.background.video_url ? faPlay : faExternalLinkAlt} /> {backgroundLinkLabel(prefs.background)}
                </a>
              ) : null}
              {prefs.background.image_url ? (
                <>
                  <img
                    className="profile-background-thumb u-mt-4"
                    src={prefs.background.image_url}
                    alt="Today's background"
                  />
                  <div>
                    <button
                      type="button"
                      className="btn btn--ghost u-mt-4"
                      onClick={download}
                      aria-label="Download current background"
                    >
                      <Icon icon={faDownload} /> {prefs.background.video_url ? "Download preview" : "Download background"}
                    </button>
                  </div>
                </>
              ) : !credit && !prefs.background.source_url ? (
                <p className="focus-lede">No image is available right now, so the page shows no backdrop.</p>
              ) : null}
            </>
          ) : (
            <p className="empty">
              No automatic background source is selected. Choose Bing or NASA above, then save changes.
            </p>
          )}
        </div>
      ) : null}

      {!draft.automatic ? (
        <div className="uploaded_backgrounds profile-background-upload">
          <div className="field">
            <label htmlFor="background_image">Upload background</label>
            <input
              id="background_image"
              type="file"
              accept="image/*"
              onChange={(event) => {
                const picked = event.target.files?.[0] ?? null;
                onFile(picked);
                if (picked) onRemoveCurrent(false);
              }}
            />
            <FieldErrors lines={errors.background_image} />
          </div>

          {preview || uploaded ? (
            <div className="profile-current-background">
              <img src={preview ?? uploaded ?? ""} alt={preview ? "New background" : "Current background"} />
              <div>
                {!preview && uploaded ? (
                  <>
                    <div className="check-row">
                      <input
                        type="checkbox"
                        id="remove_background_image"
                        checked={removeCurrent}
                        onChange={(event) => onRemoveCurrent(event.target.checked)}
                      />
                      <label htmlFor="remove_background_image">Remove current background image</label>
                    </div>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={download}
                      aria-label="Download current background image"
                    >
                      <Icon icon={faDownload} /> Download
                    </button>
                  </>
                ) : (
                  <p className="muted">Not saved yet. Update profile to use it.</p>
                )}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
