/* The JSON blob Django renders into spa.html (core/spa.py: bootstrap_payload).
   Read once at startup; anything that can change while the app is open is
   fetched through the API instead. */
export interface Bootstrap {
  user: { id: number; username: string; email: string };
  profile: {
    avatar_url: string;
    timezone: string;
    background_dimming: number;
    insights_access_enabled: boolean;
    ai_features_enabled: boolean;
    default_chart_project_count: number;
    default_chart_start_date: string;
    default_chart_end_date: string;
    openai_key_configured: boolean;
  };
  contexts: { id: number; name: string }[];
  active_context_id: number | null;
  csrf_token: string;
  static: { leaf: string; insights_empty: string };
  push: { vapid_public_key: string };
  debug: boolean;
  /** Django flash messages from the redirect that opened the app. */
  messages?: { kind: "success" | "info" | "warning" | "error"; text: string }[];
}

const FALLBACK: Bootstrap = {
  user: { id: 0, username: "", email: "" },
  profile: {
    avatar_url: "",
    timezone: "UTC",
    background_dimming: 55,
    insights_access_enabled: false,
    ai_features_enabled: false,
    default_chart_project_count: 7,
    default_chart_start_date: "",
    default_chart_end_date: "",
    openai_key_configured: false,
  },
  contexts: [],
  active_context_id: null,
  csrf_token: "",
  static: { leaf: "", insights_empty: "" },
  push: { vapid_public_key: "" },
  debug: false,
};

let cached: Bootstrap | null = null;

export function bootstrap(): Bootstrap {
  if (cached) return cached;
  const node = document.getElementById("autumn-bootstrap");
  try {
    cached = node?.textContent ? (JSON.parse(node.textContent) as Bootstrap) : FALLBACK;
  } catch {
    cached = FALLBACK;
  }
  return cached;
}

/* Tests replace the bootstrap without a DOM blob. */
export function setBootstrapForTests(value: Bootstrap | null) {
  cached = value;
}

export { FALLBACK as EMPTY_BOOTSTRAP };
