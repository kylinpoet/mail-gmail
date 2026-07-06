import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AtSign,
  CheckCircle2,
  CircleOff,
  Database,
  Edit3,
  KeyRound,
  Mail,
  Play,
  Plus,
  RefreshCcw,
  Search,
  Server,
  Shield,
  Trash2,
  Wifi,
  X,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
const SYNC_ALL_ACCOUNTS = "__all_accounts__";
const SYNC_FIRST_ACCOUNT = "__first_account__";

function useStoredState(key, initial) {
  const [value, setValue] = useState(() => localStorage.getItem(key) || initial);
  useEffect(() => {
    localStorage.setItem(key, value);
  }, [key, value]);
  return [value, setValue];
}

function App() {
  const [adminToken, setAdminToken] = useStoredState("adminToken", "");
  const [tab, setTab] = useState("accounts");
  const [accounts, setAccounts] = useState([]);
  const [proxies, setProxies] = useState([]);
  const [apiKeys, setApiKeys] = useState([]);
  const [messages, setMessages] = useState([]);
  const [aliases, setAliases] = useState([]);
  const [selectedAccountId, setSelectedAccountId] = useStoredState("selectedAccountId", "");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const headers = useMemo(() => {
    const value = { "Content-Type": "application/json" };
    if (adminToken) value["X-Admin-Token"] = adminToken;
    return value;
  }, [adminToken]);

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
    });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      throw new Error(typeof data === "string" ? data : data.detail || "Request failed");
    }
    return data;
  }

  async function refreshAll() {
    setBusy(true);
    try {
      const [nextAccounts, nextProxies, nextKeys, nextMessages] = await Promise.all([
        request("/admin/accounts"),
        request("/admin/proxies"),
        request("/admin/api-keys"),
        request("/admin/messages?limit=50"),
      ]);
      setAccounts(nextAccounts);
      setProxies(nextProxies);
      setApiKeys(nextKeys);
      setMessages(nextMessages);
      const activeAccount = selectedAccountId || nextAccounts[0]?.id || "";
      if (activeAccount) {
        setSelectedAccountId(String(activeAccount));
        setAliases(await request(`/admin/accounts/${activeAccount}/aliases`));
      } else {
        setAliases([]);
      }
      setNotice("Updated");
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refreshAll();
    const params = new URLSearchParams(window.location.search);
    const oauth = params.get("oauth");
    if (oauth) {
      setNotice(oauth === "success" ? "OAuth connected" : params.get("message") || "OAuth failed");
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  async function loadAliases(accountId) {
    setSelectedAccountId(String(accountId));
    setAliases(await request(`/admin/accounts/${accountId}/aliases`));
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Mail size={22} />
          <span>Gmail Manager</span>
        </div>
        <NavItem active={tab === "accounts"} icon={<AtSign />} label="Accounts" onClick={() => setTab("accounts")} />
        <NavItem active={tab === "aliases"} icon={<Shield />} label="Aliases" onClick={() => setTab("aliases")} />
        <NavItem active={tab === "proxies"} icon={<Wifi />} label="Proxies" onClick={() => setTab("proxies")} />
        <NavItem active={tab === "messages"} icon={<Mail />} label="Messages" onClick={() => setTab("messages")} />
        <NavItem active={tab === "keys"} icon={<KeyRound />} label="API Keys" onClick={() => setTab("keys")} />
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <h1>{tabTitle(tab)}</h1>
            <div className="status-line">
              <Database size={15} />
              <span>SQLite</span>
              <span className="dot" />
              <span>{accounts.length} accounts</span>
              <span className="dot" />
              <span>{messages.length} recent messages</span>
            </div>
          </div>
          <div className="top-actions">
            <input
              className="token-input"
              type="password"
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
              placeholder="X-Admin-Token"
            />
            <button className="icon-button" onClick={refreshAll} title="Refresh" aria-label="Refresh">
              <RefreshCcw size={18} className={busy ? "spin" : ""} />
            </button>
          </div>
        </header>

        {notice ? <div className="notice">{notice}</div> : null}
        {tab === "accounts" && <AccountsView accounts={accounts} proxies={proxies} request={request} refresh={refreshAll} setNotice={setNotice} />}
        {tab === "aliases" && (
          <AliasesView
            accounts={accounts}
            aliases={aliases}
            selectedAccountId={selectedAccountId}
            onAccountChange={loadAliases}
            request={request}
            refresh={() => loadAliases(selectedAccountId)}
          />
        )}
        {tab === "proxies" && <ProxiesView proxies={proxies} request={request} refresh={refreshAll} setNotice={setNotice} />}
        {tab === "messages" && <MessagesView messages={messages} accounts={accounts} request={request} setMessages={setMessages} setNotice={setNotice} />}
        {tab === "keys" && <ApiKeysView apiKeys={apiKeys} request={request} refresh={refreshAll} />}
      </main>
    </div>
  );
}

function tabTitle(tab) {
  return {
    accounts: "Accounts",
    aliases: "Aliases",
    proxies: "Proxies",
    messages: "Messages",
    keys: "API Keys",
  }[tab];
}

function NavItem({ active, icon, label, onClick }) {
  return (
    <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>
      {React.cloneElement(icon, { size: 18 })}
      <span>{label}</span>
    </button>
  );
}

function AccountsView({ accounts, proxies, request, refresh, setNotice }) {
  const [email, setEmail] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [proxyChoice, setProxyChoice] = useState("auto");
  const [workingId, setWorkingId] = useState("");

  function proxyPayloadFromChoice(value) {
    if (value === "direct") return { proxy_mode: "direct", proxy_id: null };
    if (value.startsWith("proxy:")) return { proxy_mode: "fixed", proxy_id: Number(value.replace("proxy:", "")) };
    return { proxy_mode: "auto", proxy_id: null };
  }

  function proxyChoiceForAccount(account) {
    if (account.proxy_mode === "direct") return "direct";
    if (account.proxy_id) return `proxy:${account.proxy_id}`;
    return "auto";
  }

  async function saveAccount() {
    await request("/admin/accounts", {
      method: "POST",
      body: JSON.stringify({
        email,
        app_password: appPassword,
        ...proxyPayloadFromChoice(proxyChoice),
        sync_enabled: true,
      }),
    });
    setEmail("");
    setAppPassword("");
    setProxyChoice("auto");
    await refresh();
  }

  async function syncAccount(id) {
    setWorkingId(`sync-${id}`);
    try {
      const job = await request(`/admin/accounts/${id}/sync`, { method: "POST" });
      await refresh();
      setNotice(job.status === "success" ? `Sync completed. Inserted ${job.inserted_count} new messages.` : `Sync failed: ${job.error || "unknown error"}`);
    } finally {
      setWorkingId("");
    }
  }

  async function testAccount(id) {
    setWorkingId(`test-${id}`);
    try {
      const result = await request(`/admin/accounts/${id}/test`, { method: "POST" });
      await refresh();
      setNotice(result.ok ? "Connection test passed. Gmail IMAP login works." : `Connection test failed: ${result.error || "unknown error"}`);
    } finally {
      setWorkingId("");
    }
  }

  async function updateAccountProxy(account, value) {
    setWorkingId(`proxy-${account.id}`);
    try {
      await request(`/admin/accounts/${account.id}`, {
        method: "PATCH",
        body: JSON.stringify(proxyPayloadFromChoice(value)),
      });
      await refresh();
      const label = value === "direct" ? "direct" : value === "auto" ? "auto / pool" : "fixed proxy";
      setNotice(`Proxy mode set to ${label} for ${account.email}.`);
    } finally {
      setWorkingId("");
    }
  }

  async function revokeAccount(account) {
    const ok = window.confirm(`Remove the saved app password for ${account.email}? Sync will stop until you add the password again.`);
    if (!ok) return;
    setWorkingId(`revoke-${account.id}`);
    try {
      await request(`/admin/accounts/${account.id}/revoke`, { method: "POST" });
      await refresh();
      setNotice("Saved app password removed and sync disabled.");
    } finally {
      setWorkingId("");
    }
  }

  return (
    <section className="work">
      <form className="toolbar" onSubmit={(event) => { event.preventDefault(); saveAccount(); }}>
        <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="gmail address" type="email" required />
        <input
          value={appPassword}
          onChange={(event) => setAppPassword(event.target.value)}
          placeholder="app password"
          type="password"
          required
        />
        <select value={proxyChoice} onChange={(event) => setProxyChoice(event.target.value)}>
          <option value="auto">auto / pool</option>
          <option value="direct">direct</option>
          {proxies.map((proxy) => (
            <option key={proxy.id} value={`proxy:${proxy.id}`}>{proxy.name}</option>
          ))}
        </select>
        <button className="primary" type="submit"><Plus size={16} />Add Gmail</button>
      </form>
      <div className="table">
        <div className="row head">
          <span>Email</span><span>Status</span><span>Last Sync</span><span>Proxy</span><span>Actions</span>
        </div>
        {accounts.map((account) => (
          <div className="row" key={account.id}>
            <span className="strong">{account.email}</span>
            <Status value={account.status} />
            <span>{formatDate(account.last_sync_at)}</span>
            <select
              className="row-select"
              value={proxyChoiceForAccount(account)}
              disabled={Boolean(workingId)}
              title="Change the proxy used by this Gmail account."
              onChange={(event) => updateAccountProxy(account, event.target.value)}
            >
              <option value="auto">auto / pool</option>
              <option value="direct">direct</option>
              {proxies.map((proxy) => (
                <option key={proxy.id} value={`proxy:${proxy.id}`}>{proxy.name}</option>
              ))}
            </select>
            <span className="account-actions">
              <button
                className="action-button"
                disabled={Boolean(workingId)}
                title="Test Gmail IMAP login with the saved app password and selected proxy."
                onClick={() => testAccount(account.id)}
              >
                <Activity size={16} />{workingId === `test-${account.id}` ? "Testing" : "Test"}
              </button>
              <button
                className="action-button"
                disabled={Boolean(workingId) || account.status === "disabled"}
                title="Fetch new messages now. This reads Gmail only and does not mark messages as read."
                onClick={() => syncAccount(account.id)}
              >
                <Play size={16} />{workingId === `sync-${account.id}` ? "Syncing" : "Sync"}
              </button>
              <button
                className="action-button danger"
                disabled={Boolean(workingId) || !account.app_password_configured}
                title="Remove the saved app password and disable future sync for this account."
                onClick={() => revokeAccount(account)}
              >
                <CircleOff size={16} />Remove Password
              </button>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function AliasesView({ accounts, aliases, selectedAccountId, onAccountChange, request, refresh }) {
  const [pattern, setPattern] = useState("shop-{n}");
  const [count, setCount] = useState(10);
  const [selectedIds, setSelectedIds] = useState([]);
  const aliasTemplates = [
    { label: "1,2,3", pattern: "shop-{n}" },
    { label: "01,02", pattern: "shop-{n:00}" },
    { label: "001,002", pattern: "shop-{n:000}" },
    { label: "random 5", pattern: "shop-{rand:5}" },
    { label: "random 8", pattern: "shop-{rand:8}" },
  ];

  useEffect(() => {
    setSelectedIds([]);
  }, [selectedAccountId]);

  async function generate(event) {
    event.preventDefault();
    if (!selectedAccountId) return;
    await request(`/admin/accounts/${selectedAccountId}/aliases/generate`, {
      method: "POST",
      body: JSON.stringify({ pattern, count: Number(count) }),
    });
    setSelectedIds([]);
    await refresh();
  }

  function toggleSelected(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleAll(checked) {
    setSelectedIds(checked ? aliases.map((alias) => alias.id) : []);
  }

  async function batchUpdate(enabled) {
    if (!selectedAccountId || selectedIds.length === 0) return;
    await request(`/admin/accounts/${selectedAccountId}/aliases/batch`, {
      method: "PATCH",
      body: JSON.stringify({ ids: selectedIds, enabled }),
    });
    await refresh();
  }

  async function deleteSelected() {
    if (!selectedAccountId || selectedIds.length === 0) return;
    const ok = window.confirm(`Delete ${selectedIds.length} selected aliases? Existing messages stay in the inbox, but future matching for these aliases is removed.`);
    if (!ok) return;
    await request(`/admin/accounts/${selectedAccountId}/aliases/batch`, {
      method: "DELETE",
      body: JSON.stringify({ ids: selectedIds }),
    });
    setSelectedIds([]);
    await refresh();
  }

  async function deleteOne(alias) {
    const ok = window.confirm(`Delete alias ${alias.alias_address}?`);
    if (!ok) return;
    await request(`/admin/accounts/${selectedAccountId}/aliases/${alias.id}`, { method: "DELETE" });
    setSelectedIds((current) => current.filter((id) => id !== alias.id));
    await refresh();
  }

  const selectedCount = selectedIds.length;

  return (
    <section className="work">
      <form className="toolbar" onSubmit={generate}>
        <select value={selectedAccountId} onChange={(event) => onAccountChange(event.target.value)}>
          <option value="">account</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>{account.email}</option>
          ))}
        </select>
        <input
          value={pattern}
          onChange={(event) => setPattern(event.target.value)}
          placeholder="shop-{n:00} or promo-{rand:5}"
          title="{n}=1,2,3; {n:00}=01,02; {n:000}=001,002; {rand:5}=random 5 chars"
        />
        <input type="number" min="0" max="10000" value={count} onChange={(event) => setCount(event.target.value)} />
        <button className="primary" type="submit"><AtSign size={16} />Generate</button>
      </form>
      <div className="hintbar">
        {aliasTemplates.map((template) => (
          <button
            key={template.pattern}
            type="button"
            title={template.pattern}
            onClick={() => setPattern(template.pattern)}
          >
            {template.label}
          </button>
        ))}
        <span>{`{n:00}=01, {n:000}=001, {rand:5}=abc12`}</span>
      </div>
      <div className="bulkbar">
        <label className="check">
          <input
            type="checkbox"
            checked={aliases.length > 0 && selectedCount === aliases.length}
            onChange={(event) => toggleAll(event.target.checked)}
          />
          {selectedCount ? `${selectedCount} selected` : "Select all"}
        </label>
        <button type="button" disabled={!selectedCount} onClick={() => batchUpdate(true)}>Enable</button>
        <button type="button" disabled={!selectedCount} onClick={() => batchUpdate(false)}>Disable</button>
        <button type="button" className="danger" disabled={!selectedCount} onClick={deleteSelected}><Trash2 size={16} />Delete</button>
      </div>
      <div className="alias-table">
        <div className="alias-row alias-head">
          <span></span><span>Alias</span><span>Status</span><span>Messages</span><span>Last Seen</span><span>Actions</span>
        </div>
        {aliases.map((alias) => (
          <div className="alias-row" key={alias.id}>
            <input type="checkbox" checked={selectedIds.includes(alias.id)} onChange={() => toggleSelected(alias.id)} />
            <div className="strong">{alias.alias_address}</div>
            <span className={`pill ${alias.enabled ? "ok" : "warn"}`}>{alias.enabled ? "enabled" : "disabled"}</span>
            <span>{alias.message_count}</span>
            <span>{formatDate(alias.last_seen_at)}</span>
            <span className="row-actions">
              <button
                className="icon-button"
                title={alias.enabled ? "Disable this alias" : "Enable this alias"}
                onClick={() => {
                  request(`/admin/accounts/${selectedAccountId}/aliases/batch`, {
                    method: "PATCH",
                    body: JSON.stringify({ ids: [alias.id], enabled: !alias.enabled }),
                  }).then(refresh);
                }}
              >
                {alias.enabled ? <CircleOff size={16} /> : <CheckCircle2 size={16} />}
              </button>
              <button className="icon-button danger" title="Delete this alias" onClick={() => deleteOne(alias)}><Trash2 size={16} /></button>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProxiesView({ proxies, request, refresh, setNotice }) {
  const emptyForm = { name: "", type: "http", host: "", port: 8080, username: "", password: "", region: "", timeout_seconds: 20, enabled: true, is_global: false, remark: "" };
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [workingId, setWorkingId] = useState("");

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save(event) {
    event.preventDefault();
    const payload = {
      ...form,
      port: Number(form.port),
      timeout_seconds: Number(form.timeout_seconds),
    };
    if (editingId && !payload.password) delete payload.password;
    await request(editingId ? `/admin/proxies/${editingId}` : "/admin/proxies", {
      method: editingId ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    setForm(emptyForm);
    setEditingId(null);
    await refresh();
  }

  function edit(proxy) {
    setEditingId(proxy.id);
    setForm({
      name: proxy.name || "",
      type: proxy.type || "http",
      host: proxy.host || "",
      port: proxy.port || 8080,
      username: proxy.username || "",
      password: "",
      region: proxy.region || "",
      timeout_seconds: proxy.timeout_seconds || 20,
      enabled: Boolean(proxy.enabled),
      is_global: Boolean(proxy.is_global),
      remark: proxy.remark || "",
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(emptyForm);
  }

  async function testWeb(proxy) {
    setWorkingId(`web-${proxy.id}`);
    try {
      const result = await request(`/admin/proxies/${proxy.id}/test`, { method: "POST" });
      await refresh();
      setNotice(result.ok ? `Proxy web test passed in ${result.elapsed_ms} ms.` : `Proxy web test failed: ${result.error || "unknown error"}`);
    } finally {
      setWorkingId("");
    }
  }

  async function testImap(proxy) {
    setWorkingId(`imap-${proxy.id}`);
    try {
      const result = await request(`/admin/proxies/${proxy.id}/test-imap`, { method: "POST" });
      const message = result.ok
        ? `Gmail IMAP proxy test passed at ${result.stage} in ${result.elapsed_ms} ms. ${result.detail || ""}`
        : `Gmail IMAP proxy test failed at ${result.stage}: ${result.error || "unknown error"}`;
      setNotice(message);
    } finally {
      setWorkingId("");
    }
  }

  async function deleteProxy(proxy) {
    const ok = window.confirm(`Delete proxy ${proxy.name}? Accounts using it will be set back to auto / pool.`);
    if (!ok) return;
    setWorkingId(`delete-${proxy.id}`);
    try {
      const result = await request(`/admin/proxies/${proxy.id}`, { method: "DELETE" });
      await refresh();
      const affected = result.affected_account_ids?.length || 0;
      setNotice(affected ? `Proxy deleted. ${affected} account(s) moved to auto / pool.` : "Proxy deleted.");
    } finally {
      setWorkingId("");
    }
  }

  return (
    <section className="work">
      <form className="toolbar proxy-form" onSubmit={save}>
        <input value={form.name} onChange={(event) => update("name", event.target.value)} placeholder="name" />
        <select value={form.type} onChange={(event) => update("type", event.target.value)}>
          <option value="http">HTTP</option>
          <option value="socks5">SOCKS5</option>
        </select>
        <input value={form.host} onChange={(event) => update("host", event.target.value)} placeholder="host" required />
        <input type="number" value={form.port} onChange={(event) => update("port", event.target.value)} />
        <input value={form.username} onChange={(event) => update("username", event.target.value)} placeholder="username" />
        <input type="password" value={form.password} onChange={(event) => update("password", event.target.value)} placeholder={editingId ? "password unchanged" : "password"} />
        <input type="number" min="1" max="120" value={form.timeout_seconds} onChange={(event) => update("timeout_seconds", event.target.value)} />
        <label className="check"><input type="checkbox" checked={form.enabled} onChange={(event) => update("enabled", event.target.checked)} />enabled</label>
        <label className="check"><input type="checkbox" checked={form.is_global} onChange={(event) => update("is_global", event.target.checked)} />global</label>
        <button className="primary" type="submit"><Server size={16} />{editingId ? "Update" : "Save"}</button>
        {editingId ? <button className="icon-button" type="button" title="Cancel" onClick={cancelEdit}><X size={16} /></button> : null}
      </form>
      <div className="table">
        <div className="row head proxy-row">
          <span>Name</span><span>Endpoint</span><span>Enabled</span><span>Last Test</span><span>Actions</span>
        </div>
        {proxies.map((proxy) => (
          <div className="row proxy-row" key={proxy.id}>
            <span className="strong">{proxy.name}</span>
            <span>{proxy.type}://{proxy.host}:{proxy.port}</span>
            <span>{proxy.enabled ? "yes" : "no"}</span>
            <span>{proxy.last_test_ok === null ? "none" : proxy.last_test_ok ? "ok" : "failed"}</span>
            <span className="row-actions">
              <button className="icon-button" title="Edit" onClick={() => edit(proxy)}><Edit3 size={16} /></button>
              <button className="icon-button" title="Test web proxy" disabled={Boolean(workingId)} onClick={() => testWeb(proxy)}>
                <Activity size={16} className={workingId === `web-${proxy.id}` ? "spin" : ""} />
              </button>
              <button className="icon-button" title="Test Gmail IMAP proxy" disabled={Boolean(workingId)} onClick={() => testImap(proxy)}>
                <Mail size={16} className={workingId === `imap-${proxy.id}` ? "spin" : ""} />
              </button>
              <button className="icon-button danger" title="Delete proxy" disabled={Boolean(workingId)} onClick={() => deleteProxy(proxy)}>
                <Trash2 size={16} className={workingId === `delete-${proxy.id}` ? "spin" : ""} />
              </button>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function MessagesView({ messages, accounts, request, setMessages, setNotice }) {
  const [q, setQ] = useState("");
  const [accountId, setAccountId] = useState("");
  const [syncAccountId, setSyncAccountId] = useState(SYNC_FIRST_ACCOUNT);
  const [syncLimit, setSyncLimit] = useState(1);
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [working, setWorking] = useState("");

  useEffect(() => {
    if (syncAccountId === SYNC_FIRST_ACCOUNT && accounts[0]) {
      setSyncAccountId(String(accounts[0].id));
    }
  }, [accounts, syncAccountId]);

  useEffect(() => {
    const visibleIds = new Set(messages.map((message) => message.id));
    setSelectedIds((current) => current.filter((id) => visibleIds.has(id)));
  }, [messages]);

  async function search(event) {
    event.preventDefault();
    const params = new URLSearchParams({ limit: "100" });
    if (q) params.set("q", q);
    if (accountId) params.set("account_id", accountId);
    setMessages(await request(`/admin/messages?${params.toString()}`));
  }

  async function refreshMessages(nextAccountId = accountId) {
    const params = new URLSearchParams({ limit: "100" });
    if (q) params.set("q", q);
    if (nextAccountId) params.set("account_id", nextAccountId);
    setMessages(await request(`/admin/messages?${params.toString()}`));
  }

  async function syncMessages(event) {
    event.preventDefault();
    const limit = Math.max(1, Number(syncLimit) || 1);
    const syncAll = syncAccountId === SYNC_ALL_ACCOUNTS;
    const targets = syncAll ? accounts : accounts.filter((account) => String(account.id) === syncAccountId);
    if (!targets.length) {
      setNotice("No account selected for sync.");
      return;
    }
    setWorking("sync");
    try {
      let fetched = 0;
      let inserted = 0;
      const failures = [];
      for (const account of targets) {
        const job = await request(`/admin/accounts/${account.id}/sync`, {
          method: "POST",
          body: JSON.stringify({ limit }),
        });
        fetched += job.fetched_count || 0;
        inserted += job.inserted_count || 0;
        if (job.status !== "success") failures.push(`${account.email}: ${job.error || "unknown error"}`);
      }
      await refreshMessages(syncAll ? accountId : syncAccountId);
      setNotice(
        failures.length
          ? `Sync finished with ${failures.length} failure(s). ${failures.join(" | ")}`
          : `Sync completed. Fetched ${fetched}, inserted ${inserted}.`
      );
    } finally {
      setWorking("");
    }
  }

  async function openMessage(message) {
    setWorking(`message-${message.id}`);
    try {
      setSelectedMessage(await request(`/admin/messages/${message.id}`));
    } finally {
      setWorking("");
    }
  }

  async function deleteMessage(message) {
    const ok = window.confirm(`Delete the local synced copy of "${message.subject || "(no subject)"}"? This will not delete the original message from Gmail.`);
    if (!ok) return;
    setWorking(`delete-${message.id}`);
    try {
      const result = await request(`/admin/messages/${message.id}`, { method: "DELETE" });
      setMessages((current) => current.filter((item) => item.id !== message.id));
      setSelectedIds((current) => current.filter((id) => id !== message.id));
      if (selectedMessage?.id === message.id) setSelectedMessage(null);
      const removed = result.removed_cached_files || 0;
      setNotice(removed ? `Local message deleted. ${removed} cached attachment file(s) removed.` : "Local message deleted.");
    } finally {
      setWorking("");
    }
  }

  function toggleSelected(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleAllVisible(checked) {
    setSelectedIds(checked ? messages.map((message) => message.id) : []);
  }

  async function deleteSelectedMessages() {
    if (!selectedIds.length) return;
    const ok = window.confirm(`Delete ${selectedIds.length} local synced message(s)? This will not delete the originals from Gmail.`);
    if (!ok) return;
    setWorking("delete-batch");
    try {
      const result = await request("/admin/messages/batch", {
        method: "DELETE",
        body: JSON.stringify({ ids: selectedIds }),
      });
      const deleted = new Set(result.deleted_ids || selectedIds);
      setMessages((current) => current.filter((message) => !deleted.has(message.id)));
      if (selectedMessage && deleted.has(selectedMessage.id)) setSelectedMessage(null);
      setSelectedIds([]);
      const removed = result.removed_cached_files || 0;
      setNotice(`Deleted ${result.deleted_count || deleted.size} local message(s). Removed ${removed} cached attachment file(s).`);
    } finally {
      setWorking("");
    }
  }

  const allVisibleSelected = messages.length > 0 && selectedIds.length === messages.length;

  return (
    <section className="work">
      <form className="toolbar" onSubmit={syncMessages}>
        <select value={syncAccountId} onChange={(event) => setSyncAccountId(event.target.value)}>
          <option value={SYNC_ALL_ACCOUNTS}>sync all accounts</option>
          {accounts.map((account) => <option key={account.id} value={account.id}>{account.email}</option>)}
        </select>
        <input
          className="count-input"
          type="number"
          min="1"
          max="5000"
          value={syncLimit}
          onChange={(event) => setSyncLimit(event.target.value)}
          title="Number of latest messages to sync"
        />
        <button className="primary" type="submit" disabled={working === "sync" || accounts.length === 0}>
          <RefreshCcw size={16} className={working === "sync" ? "spin" : ""} />Sync Latest
        </button>
      </form>
      <form className="toolbar" onSubmit={search}>
        <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
          <option value="">all accounts</option>
          {accounts.map((account) => <option key={account.id} value={account.id}>{account.email}</option>)}
        </select>
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="search" />
        <button className="primary" type="submit"><Search size={16} />Search</button>
      </form>
      <div className="bulkbar">
        <label className="check">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={(event) => toggleAllVisible(event.target.checked)}
          />
          {selectedIds.length ? `${selectedIds.length} selected` : "Select visible"}
        </label>
        <button
          type="button"
          className="danger"
          disabled={!selectedIds.length || Boolean(working)}
          onClick={deleteSelectedMessages}
        >
          <Trash2 size={16} />Delete Selected
        </button>
      </div>
      <div className="message-workspace">
        <div className="message-list">
          {messages.map((message) => (
            <div
              className={`message-row ${selectedMessage?.id === message.id ? "selected" : ""}`}
              key={message.id}
            >
              <input
                type="checkbox"
                checked={selectedIds.includes(message.id)}
                title="Select message"
                onChange={() => toggleSelected(message.id)}
              />
              <button className="message-open" type="button" onClick={() => openMessage(message)}>
                <div>
                  <div className="strong">{message.subject || "(no subject)"}</div>
                  <div className="muted">{message.sender}</div>
                </div>
                <div className="muted">{message.alias_address || "main inbox"}</div>
                <div>{working === `message-${message.id}` ? "Loading" : formatDate(message.received_at)}</div>
              </button>
              <button
                className="icon-button danger"
                type="button"
                title="Delete local synced copy"
                disabled={Boolean(working)}
                onClick={() => deleteMessage(message)}
              >
                <Trash2 size={16} className={working === `delete-${message.id}` ? "spin" : ""} />
              </button>
            </div>
          ))}
        </div>
        {selectedMessage ? (
          <article className="message-detail">
            <div className="detail-header">
              <div>
                <h2>{selectedMessage.subject || "(no subject)"}</h2>
                <div className="muted">{formatDate(selectedMessage.received_at)}</div>
              </div>
              <div className="detail-actions">
                <button
                  className="icon-button danger"
                  type="button"
                  title="Delete local synced copy"
                  disabled={Boolean(working)}
                  onClick={() => deleteMessage(selectedMessage)}
                >
                  <Trash2 size={16} className={working === `delete-${selectedMessage.id}` ? "spin" : ""} />
                </button>
                <button className="icon-button" type="button" title="Close" onClick={() => setSelectedMessage(null)}>
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="meta-grid">
              <span>From</span><div>{selectedMessage.sender || "-"}</div>
              <span>To</span><div>{(selectedMessage.recipients || []).join(", ") || "-"}</div>
              <span>Cc</span><div>{(selectedMessage.cc || []).join(", ") || "-"}</div>
              <span>Alias</span><div>{selectedMessage.alias_address || "main inbox"}</div>
            </div>
            {selectedMessage.text_body ? <pre className="message-body">{selectedMessage.text_body}</pre> : null}
            {!selectedMessage.text_body && selectedMessage.snippet ? <pre className="message-body">{selectedMessage.snippet}</pre> : null}
            {selectedMessage.html_body ? (
              <iframe className="html-preview" title="HTML body" sandbox="" srcDoc={selectedMessage.html_body} />
            ) : null}
            {selectedMessage.attachments?.length ? (
              <div className="attachment-list">
                {selectedMessage.attachments.map((attachment) => (
                  <div className="attachment-item" key={attachment.id}>
                    <span className="strong">{attachment.filename}</span>
                    <span className="muted">{attachment.mime_type || "application/octet-stream"} - {attachment.size || 0} bytes</span>
                  </div>
                ))}
              </div>
            ) : null}
            <details className="headers-detail">
              <summary>Headers</summary>
              <pre>{JSON.stringify(selectedMessage.raw_headers || {}, null, 2)}</pre>
            </details>
          </article>
        ) : null}
      </div>
    </section>
  );
}

function ApiKeysView({ apiKeys, request, refresh }) {
  const [name, setName] = useState("Default integration");
  const [created, setCreated] = useState("");

  async function create(event) {
    event.preventDefault();
    const data = await request("/admin/api-keys", {
      method: "POST",
      body: JSON.stringify({ name, rate_limit_per_minute: 120 }),
    });
    setCreated(data.api_key);
    await refresh();
  }

  return (
    <section className="work">
      <form className="toolbar" onSubmit={create}>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="name" />
        <button className="primary" type="submit"><KeyRound size={16} />Create</button>
      </form>
      {created ? <pre className="secret">{created}</pre> : null}
      <div className="table keys">
        <div className="row head key-row"><span>Name</span><span>Rate</span><span>Last Used</span><span>Status</span><span>Actions</span></div>
        {apiKeys.map((key) => (
          <div className="row key-row" key={key.id}>
            <span className="strong">{key.name}</span>
            <span>{key.rate_limit_per_minute}/min</span>
            <span>{formatDate(key.last_used_at)}</span>
            <span>{key.active ? "active" : "disabled"}</span>
            <button className="icon-button danger" title="Delete" onClick={() => request(`/admin/api-keys/${key.id}`, { method: "DELETE" }).then(refresh)}><Trash2 size={16} /></button>
          </div>
        ))}
      </div>
    </section>
  );
}

function Status({ value }) {
  const ok = value === "active";
  return (
    <span className={`pill ${ok ? "ok" : "warn"}`}>
      {ok ? <CheckCircle2 size={14} /> : <CircleOff size={14} />}
      {value}
    </span>
  );
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

createRoot(document.getElementById("root")).render(<App />);
