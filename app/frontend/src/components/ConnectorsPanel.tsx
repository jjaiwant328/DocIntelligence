"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api-config";

interface Connector {
  provider:        string;
  display_name:    string;
  client_id_last4: string;
  status:          string;
  redirect_uri:    string;
  scopes:          string[];
}

const CONNECTOR_STATUS_STYLE: Record<string, { badge: string; label: string }> = {
  connected:    { badge: "bg-green-100 text-green-700", label: "Connected"    },
  configured:   { badge: "bg-amber-100 text-amber-700", label: "Configured"   },
  unconfigured: { badge: "bg-gray-100 text-gray-500",   label: "Unconfigured" },
  error:        { badge: "bg-red-100 text-red-700",     label: "Error"        },
};

const DEFAULT_REDIRECT_BASE =
  "https://docintel-sources-4101016551133680.0.azure.databricksapps.com/oauth";

const PROVIDERS = [
  { value: "gdrive",     label: "Google Drive"          },
  { value: "sharepoint", label: "SharePoint / OneDrive" },
];

export default function ConnectorsPanel() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [msg,        setMsg]        = useState<string | null>(null);
  const [msgKind,    setMsgKind]    = useState<"ok" | "err">("ok");
  const [showForm,   setShowForm]   = useState(false);

  // Form state
  const [formIsEdit,       setFormIsEdit]       = useState(false);
  const [formProvider,     setFormProvider]     = useState("gdrive");
  const [formDisplayName,  setFormDisplayName]  = useState("");
  const [formClientId,     setFormClientId]     = useState("");
  const [formClientSecret, setFormClientSecret] = useState(""); // write-only, cleared on submit
  const [formScopes,       setFormScopes]       = useState("");
  const [formRedirectUri,  setFormRedirectUri]  = useState(
    `${DEFAULT_REDIRECT_BASE}/gdrive/callback`
  );
  const [saving, setSaving] = useState(false);

  // Per-connector notes for when authorize-url is empty
  const [authNotes, setAuthNotes] = useState<Record<string, string>>({});

  function showMsg(text: string, kind: "ok" | "err") {
    setMsgKind(kind);
    setMsg(text);
  }

  const fetchConnectors = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiCall<{ connectors: Connector[] }>("/api/connectors");
      setConnectors(r.connectors ?? []);
    } catch (e) {
      showMsg(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { fetchConnectors(); }, [fetchConnectors]);

  function openForm(connector?: Connector) {
    if (connector) {
      setFormIsEdit(true);
      setFormProvider(connector.provider);
      setFormDisplayName(connector.display_name);
      setFormClientId("");       // never pre-fill from server
      setFormClientSecret("");   // never pre-fill from server
      setFormScopes(connector.scopes.join(", "));
      // Seed the redirect URI from the stored value so the user sees what their
      // OAuth provider's console has registered — showing the wrong value here
      // causes a silent redirect-mismatch at OAuth time.
      setFormRedirectUri(connector.redirect_uri);
    } else {
      setFormIsEdit(false);
      setFormProvider("gdrive");
      setFormDisplayName("");
      setFormClientId("");
      setFormClientSecret("");
      setFormScopes("");
      setFormRedirectUri(`${DEFAULT_REDIRECT_BASE}/gdrive/callback`);
    }
    setShowForm(true);
    setMsg(null);
  }

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = {
        provider:  formProvider,
        client_id: formClientId.trim(),
      };
      if (formDisplayName.trim()) body.display_name = formDisplayName.trim();
      // Omit client_secret when empty — backend preserves the stored one
      if (formClientSecret) body.client_secret = formClientSecret;
      // Parse scopes: split on commas or whitespace, drop empties
      const scopesList = formScopes.trim()
        ? formScopes.trim().split(/[\s,]+/).filter(Boolean)
        : undefined;
      if (scopesList && scopesList.length > 0) body.scopes = scopesList;
      // In edit mode send the stored redirect_uri so it is preserved rather than
      // silently reset to the backend default. For new connectors omit it — the
      // backend will default it to the correct value.
      if (formIsEdit) body.redirect_uri = formRedirectUri;

      await apiCall<{ connector: Connector }>("/api/connectors", {
        method: "POST",
        body: JSON.stringify(body),
      });

      setFormClientSecret(""); // clear write-only field on success
      setShowForm(false);
      showMsg(`Connector "${formDisplayName || formProvider}" saved.`, "ok");
      fetchConnectors();
    } catch (e) {
      showMsg(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setSaving(false);
    }
  }

  async function authorize(provider: string) {
    setMsg(null); // clear any stale message before fetching
    setAuthNotes(n => ({ ...n, [provider]: "" }));
    try {
      const r = await apiCall<{ auth_url: string }>(
        `/api/connectors/${provider}/authorize-url`
      );
      if (r.auth_url) {
        window.open(r.auth_url, "_blank");
      } else {
        setAuthNotes(n => ({
          ...n,
          [provider]:
            "OAuth URL unavailable — DOCINTEL_MCP_SOURCES_URL may not be configured on the server.",
        }));
      }
    } catch (e) {
      showMsg(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function remove(provider: string) {
    setMsg(null);
    try {
      await apiCall<{ provider: string; deleted: boolean }>(
        `/api/connectors/${provider}`,
        { method: "DELETE" }
      );
      showMsg(`Connector "${provider}" removed.`, "ok");
      fetchConnectors();
    } catch (e) {
      showMsg(e instanceof Error ? e.message : String(e), "err");
    }
  }

  return (
    <div className="mt-10">
      {/* Section header */}
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-lg font-bold text-gray-900">Connector Credentials</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            OAuth credentials for document source providers. Shared across all users of this app.
          </p>
        </div>
        <button
          onClick={() => (showForm ? setShowForm(false) : openForm())}
          className="flex-shrink-0 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
        >
          <span className="text-base leading-none">+</span> Add / Configure
        </button>
      </div>

      {/* Sensitive-data notice */}
      <div className="mb-4 flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
        <span className="flex-shrink-0 mt-0.5">⚠️</span>
        <span>
          These credentials are <strong>shared across everyone using this app</strong> and stored
          securely in Databricks Secrets. Client secrets are{" "}
          <strong>write-only</strong> — they are never returned by the API.
        </span>
      </div>

      {/* Add / Configure form */}
      {showForm && (
        <div className="mb-4 bg-white border border-blue-200 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-800 mb-4">Configure a connector</h3>
          <div className="grid grid-cols-2 gap-3 mb-4">
            {/* Provider */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Provider
              </label>
              <select
                value={formProvider}
                onChange={e => {
                  const v = e.target.value;
                  setFormProvider(v);
                  // For new connectors keep the redirect preview in sync with the
                  // selected provider; leave it alone in edit mode.
                  if (!formIsEdit) {
                    setFormRedirectUri(`${DEFAULT_REDIRECT_BASE}/${v}/callback`);
                  }
                }}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                {PROVIDERS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            {/* Display Name */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Display Name
              </label>
              <input
                value={formDisplayName}
                onChange={e => setFormDisplayName(e.target.value)}
                placeholder="My Google Drive App"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            {/* Client ID */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Client ID
              </label>
              <input
                value={formClientId}
                onChange={e => setFormClientId(e.target.value)}
                placeholder="OAuth client ID"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            {/* Client Secret — write-only */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Client Secret{" "}
                <span className="font-normal text-gray-400">(write-only)</span>
              </label>
              <input
                type="password"
                value={formClientSecret}
                onChange={e => setFormClientSecret(e.target.value)}
                placeholder="Leave blank to preserve existing"
                autoComplete="new-password"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            {/* Scopes */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Scopes{" "}
                <span className="font-normal text-gray-400">(comma or space separated)</span>
              </label>
              <input
                value={formScopes}
                onChange={e => setFormScopes(e.target.value)}
                placeholder="https://www.googleapis.com/auth/drive.readonly"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            {/* Redirect URI — read-only; shows stored value in edit mode, computed default for new */}
            <div>
              <label className="text-[11px] font-semibold text-gray-500 block mb-1">
                Redirect URI{" "}
                <span className="font-normal text-gray-400">(auto-configured)</span>
              </label>
              <input
                readOnly
                value={formRedirectUri}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-gray-50 text-gray-400 cursor-not-allowed"
              />
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={saving || !formClientId.trim()}
              className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-4 py-1.5 rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg cursor-pointer"
            >
              Cancel
            </button>
          </div>

          <p className="mt-3 text-[11px] text-gray-400">
            After saving, click <strong>Authorize</strong> on the connector row to begin the OAuth
            flow for this app.
          </p>
        </div>
      )}

      {msg && (
        <div
          className={`mb-4 text-sm rounded-lg p-3 ${
            msgKind === "ok"
              ? "text-green-700 bg-green-50 border border-green-200"
              : "text-red-700 bg-red-50 border border-red-200"
          }`}
        >
          {msg}
        </div>
      )}

      {loading ? (
        <div className="text-center text-gray-400 py-10 text-sm">Loading connectors…</div>
      ) : connectors.length === 0 ? (
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl py-12 flex flex-col items-center text-center">
          <span className="text-4xl mb-3">🔑</span>
          <h3 className="text-base font-bold text-gray-800 mb-1.5">No connectors configured</h3>
          <p className="text-sm text-gray-500 max-w-sm mb-5">
            Add OAuth credentials for Google Drive or SharePoint to enable delegated
            authentication in document sources.
          </p>
          <button
            onClick={() => openForm()}
            className="text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 px-5 py-2.5 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            <span className="text-base leading-none">+</span> Add connector credentials
          </button>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Column headers */}
          <div className="grid grid-cols-12 bg-gray-50 border-b border-gray-200 px-4 py-2 text-[10px] font-bold text-gray-500 uppercase tracking-wide">
            <span className="col-span-3">Provider</span>
            <span className="col-span-3">Display Name</span>
            <span className="col-span-2">Client ID</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-2">Actions</span>
          </div>

          {connectors.map((c, i) => {
            const st = CONNECTOR_STATUS_STYLE[c.status] ?? CONNECTOR_STATUS_STYLE.unconfigured;
            return (
              <div
                key={c.provider}
                className={`grid grid-cols-12 px-4 py-3 border-b border-gray-50 last:border-0 items-start text-sm ${
                  i % 2 === 0 ? "bg-white" : "bg-gray-50/40"
                }`}
              >
                <span className="col-span-3 text-xs text-gray-600 font-mono self-center">
                  {c.provider}
                </span>
                <span className="col-span-3 text-sm text-gray-800 self-center">
                  {c.display_name}
                </span>
                <span className="col-span-2 text-xs text-gray-400 font-mono self-center">
                  {c.client_id_last4 ? `••••${c.client_id_last4}` : "—"}
                </span>
                <span className="col-span-2 self-center">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${st.badge}`}>
                    {st.label}
                  </span>
                </span>
                <div className="col-span-2 flex flex-col gap-1.5">
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      onClick={() => authorize(c.provider)}
                      className="text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      Authorize
                    </button>
                    <button
                      onClick={() => openForm(c)}
                      className="text-xs font-semibold text-gray-600 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => remove(c.provider)}
                      className="text-xs font-semibold text-red-600 hover:text-red-800 bg-red-50 hover:bg-red-100 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      Remove
                    </button>
                  </div>
                  {authNotes[c.provider] && (
                    <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1">
                      {authNotes[c.provider]}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
