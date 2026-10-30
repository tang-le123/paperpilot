import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API =
  import.meta.env.VITE_API_BASE ||
  (window.location.port === "5173"
    ? "http://127.0.0.1:8001/api/v1"
    : "/api/v1");

const MODES = [
  ["auto", "自动"],
  ["single", "内容问答"],
  ["compare", "论文对比"],
  ["innovate", "创新点"],
  ["explain", "术语解释"],
  ["summary", "总结"],
];

function statusLabel(status) {
  return {
    pending: "排队中",
    parsing: "解析中",
    indexing: "建索引",
    ready: "就绪",
    failed: "失败",
  }[status] || status;
}

async function openProtected(path, token, download = false) {
  const response = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    alert(`打开失败：${response.status}`);
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  if (download) {
    const link = document.createElement("a");
    link.href = url;
    link.download = path.split("/").pop() || "paper";
    link.click();
  } else {
    window.open(url, "_blank");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function Citation({ citation, token }) {
  const supportLabel = {
    yes: "✅ 已支持",
    partial: "⚠️ 部分支持",
    no: "❌ 不支持",
    unknown: "❔ 未校验",
  }[citation.support || "unknown"];
  return (
    <div className="citation">
      <div className="citation-title">
        📎 {citation.title} · 第 {citation.page} 页 · {citation.section}
      </div>
      <div className={`citation-support ${citation.support || "unknown"}`}>
        {supportLabel}
        {citation.support_reason ? ` · ${citation.support_reason}` : ""}
      </div>
      <div className="citation-actions">
        <button
          className="link-button"
          onClick={() =>
            openProtected(
              `/papers/${citation.paper_id}/page/${citation.page}?chunk_id=${citation.chunk_id}`,
              token
            )
          }
        >
          打开原文页（高亮）
        </button>
        <button
          className="link-button"
          onClick={() => openProtected(`/papers/${citation.paper_id}/file`, token, true)}
        >
          下载原文
        </button>
      </div>
      <div className="citation-snippet">{citation.snippet}</div>
    </div>
  );
}

function AuthScreen({ onAuth }) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/auth/${isRegister ? "register" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "认证失败");
      onAuth(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <h1>📚 PaperPilot</h1>
        <p>{isRegister ? "创建账号" : "登录后管理你的论文集合"}</p>
        <label>
          用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "处理中…" : isRegister ? "注册" : "登录"}
        </button>
        <button type="button" className="ghost" onClick={() => setIsRegister(!isRegister)}>
          {isRegister ? "已有账号，去登录" : "没有账号，去注册"}
        </button>
        <p className="hint">本地演示账号：demo / demo1234</p>
      </form>
    </div>
  );
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("paperpilot_token") || "");
  const [username, setUsername] = useState("");
  const [authReady, setAuthReady] = useState(false);
  const [papers, setPapers] = useState([]);
  const [collections, setCollections] = useState([]);
  const [collectionId, setCollectionId] = useState("");
  const [moveTarget, setMoveTarget] = useState("");
  const [newCollection, setNewCollection] = useState("");
  const [selected, setSelected] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("zh");
  const [mode, setMode] = useState("auto");
  const [allowGeneral, setAllowGeneral] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const fileRef = useRef(null);

  function authHeaders() {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function refreshSession() {
    const refreshToken = localStorage.getItem("paperpilot_refresh");
    if (!refreshToken) return "";
    try {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return "";
      const data = await response.json();
      localStorage.setItem("paperpilot_token", data.token);
      localStorage.setItem("paperpilot_refresh", data.refresh_token);
      setToken(data.token);
      setUsername(data.username || username);
      return data.token;
    } catch {
      return "";
    }
  }

  async function request(path, options = {}, retry = true) {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: { ...(options.headers || {}), ...authHeaders() },
    });
    if (response.status === 401 && retry) {
      const refreshed = await refreshSession();
      if (refreshed) {
        return fetch(`${API}${path}`, {
          ...options,
          headers: { ...(options.headers || {}), Authorization: `Bearer ${refreshed}` },
        });
      }
      logout();
      throw new Error("登录已失效");
    }
    return response;
  }

  function logout() {
    localStorage.removeItem("paperpilot_token");
    localStorage.removeItem("paperpilot_refresh");
    setToken("");
    setUsername("");
    setPapers([]);
    setCollections([]);
    setCollectionId("");
    setMoveTarget("");
    setSelected([]);
    setMessages([]);
  }

  async function loadUser() {
    if (!token) {
      setAuthReady(true);
      return;
    }
    try {
      let response = await fetch(`${API}/auth/me`, { headers: authHeaders() });
      if (response.status === 401 && (await refreshSession())) {
        response = await fetch(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${localStorage.getItem("paperpilot_token")}` },
        });
      }
      if (!response.ok) throw new Error("unauthorized");
      const data = await response.json();
      setUsername(data.username);
      setAuthReady(true);
    } catch {
      localStorage.removeItem("paperpilot_token");
      localStorage.removeItem("paperpilot_refresh");
      setToken("");
      setAuthReady(true);
    }
  }

  async function refreshCollections() {
    if (!token) return;
    try {
      const response = await request("/collections");
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setCollections(data);
      setCollectionId((current) => current || String(data[0]?.id || ""));
      setMoveTarget((current) => current || String(data[0]?.id || ""));
    } catch (error) {
      setNotice(`集合读取失败：${error.message}`);
    }
  }

  async function refreshPapers() {
    if (!token) return;
    try {
      const query = collectionId ? `?collection_id=${collectionId}` : "";
      const response = await request(`/papers${query}`);
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setPapers(data);
      setSelected((current) =>
        current.filter((id) => data.some((paper) => paper.id === id && paper.status === "ready"))
      );
    } catch (error) {
      setNotice(`论文读取失败：${error.message}`);
    }
  }

  useEffect(() => {
    loadUser();
  }, []);

  useEffect(() => {
    if (!token) return;
    refreshCollections();
  }, [token]);

  useEffect(() => {
    if (!token) return;
    refreshPapers();
    const timer = setInterval(refreshPapers, 5000);
    return () => clearInterval(timer);
  }, [token, collectionId]);

  function applyAuth(data) {
    localStorage.setItem("paperpilot_token", data.token);
    localStorage.setItem("paperpilot_refresh", data.refresh_token);
    setToken(data.token);
    setUsername(data.username);
    setAuthReady(true);
  }

  async function createCollection() {
    if (!newCollection.trim()) return;
    const response = await request("/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newCollection.trim() }),
    });
    if (!response.ok) {
      setNotice(await response.text());
      return;
    }
    setNewCollection("");
    await refreshCollections();
  }

  async function renameCollection() {
    const current = collections.find((item) => String(item.id) === String(collectionId));
    if (!current) return;
    const name = window.prompt("新的集合名称", current.name);
    if (!name || !name.trim()) return;
    const response = await request(`/collections/${current.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    if (!response.ok) {
      setNotice(await response.text());
      return;
    }
    await refreshCollections();
  }

  async function deleteCollection() {
    const current = collections.find((item) => String(item.id) === String(collectionId));
    if (!current) return;
    if (!window.confirm(`删除集合「${current.name}」？其中的论文会移到其他集合。`)) return;
    const response = await request(`/collections/${current.id}`, { method: "DELETE" });
    if (!response.ok) {
      setNotice(await response.text());
      return;
    }
    setCollectionId("");
    await refreshCollections();
    await refreshPapers();
  }

  async function moveSelected() {
    if (!selected.length || !moveTarget) return;
    for (const paperId of selected) {
      const response = await request(`/papers/${paperId}/collection`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ collection_id: Number(moveTarget) }),
      });
      if (!response.ok) {
        setNotice(await response.text());
        return;
      }
    }
    setSelected([]);
    await refreshPapers();
  }

  async function upload() {
    const files = Array.from(fileRef.current?.files || []);
    if (!files.length) return;
    setBusy(true);
    setNotice("");
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      if (collectionId) form.append("collection_id", collectionId);
      try {
        const response = await request("/papers/upload", { method: "POST", body: form });
        if (!response.ok) throw new Error(await response.text());
        setNotice(`已上传 ${file.name}，后台解析中…`);
      } catch (error) {
        setNotice(`上传 ${file.name} 失败：${error.message}`);
      }
    }
    fileRef.current.value = "";
    setBusy(false);
    refreshPapers();
  }

  function togglePaper(id) {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    );
  }

  async function send() {
    const question = input.trim();
    if (!question || !selected.length || busy) return;
    setInput("");
    setBusy(true);
    setMessages((current) => [
      ...current,
      { role: "user", content: question },
      { role: "assistant", content: "", citations: [], meta: "正在检索…" },
    ]);
    const updateLast = (patch) =>
      setMessages((current) => {
        const copy = [...current];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = { ...last, ...patch };
        return copy;
      });

    try {
      const response = await request("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paper_ids: selected,
          question,
          answer_language: language,
          mode,
          allow_general_knowledge: allowGeneral,
        }),
      });
      if (!response.ok || !response.body) throw new Error(await response.text());

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf("\n\n");

          let event = "message";
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          const parsed = JSON.parse(data);

          if (event === "route") {
            updateLast({ meta: `策略：${parsed.strategy} · ${parsed.reason}` });
          } else if (event === "token") {
            answer += parsed.text || "";
            updateLast({ content: answer });
          } else if (event === "final") {
            updateLast({
              content: parsed.answer,
              citations: parsed.citations || [],
              claims: parsed.claims || [],
              meta: `策略：${parsed.strategy} · ${parsed.route_reason} · 来源：${parsed.source_scope} · 引用支持：${parsed.citation_support_rate ?? "N/A"} · claim 支持：${parsed.claim_support_rate ?? "N/A"} · ${parsed.latency_ms} ms${parsed.answer_suppressed ? " · 已抑制回答" : ""}`,
            });
          } else if (event === "error") {
            updateLast({ content: `生成失败：${parsed.detail}` });
          }
        }
      }
    } catch (error) {
      updateLast({ content: `请求失败：${error.message}` });
    } finally {
      setBusy(false);
    }
  }

  async function summarize() {
    if (!selected.length || busy) return;
    setBusy(true);
    setMessages((current) => [...current, { role: "user", content: "请总结选中的论文" }]);
    try {
      const response = await request("/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: selected.slice(0, 5), answer_language: language }),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setMessages((current) => [
        ...current,
        { role: "assistant", content: data.summary, citations: [], meta: `总结 · ${data.latency_ms} ms` },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: `总结失败：${error.message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  if (!authReady) return <div className="loading">加载中…</div>;
  if (!token) return <AuthScreen onAuth={applyAuth} />;

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>📚 PaperPilot</h1>
          <p>{username} · 论文阅读与证据问答</p>
        </div>
        <div className="header-actions">
          <span className="badge">React</span>
          <button className="ghost" onClick={logout}>退出</button>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <h2>论文库</h2>
          <div className="collection-row">
            <select value={collectionId} onChange={(e) => setCollectionId(e.target.value)}>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>{collection.name}</option>
              ))}
            </select>
          </div>
          <div className="collection-actions">
            <button className="ghost" onClick={renameCollection}>重命名</button>
            <button className="ghost" onClick={deleteCollection}>删除集合</button>
          </div>
          <div className="collection-row">
            <input
              value={newCollection}
              onChange={(e) => setNewCollection(e.target.value)}
              placeholder="新建集合"
            />
            <button className="ghost" onClick={createCollection}>新建</button>
          </div>
          <div className="collection-row">
            <select value={moveTarget} onChange={(e) => setMoveTarget(e.target.value)}>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>{collection.name}</option>
              ))}
            </select>
            <button className="ghost" onClick={moveSelected} disabled={!selected.length}>
              移动选中
            </button>
          </div>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.md" multiple />
          <button className="primary" onClick={upload} disabled={busy}>上传</button>
          <button className="ghost" onClick={refreshPapers}>刷新列表</button>
          {notice && <p className="notice">{notice}</p>}

          <div className="paper-list">
            {papers.map((paper) => (
              <button
                key={paper.id}
                className={`paper ${selected.includes(paper.id) ? "selected" : ""}`}
                onClick={() => paper.status === "ready" && togglePaper(paper.id)}
                disabled={paper.status !== "ready"}
              >
                <strong>{paper.title}</strong>
                <span>{paper.file_type.toUpperCase()} · {paper.page_count} 页 · {paper.chunk_count} 块</span>
                <em className={`status ${paper.status}`}>{statusLabel(paper.status)}</em>
              </button>
            ))}
            {!papers.length && <p className="empty">这个集合还没有论文。</p>}
          </div>
        </aside>

        <main className="main">
          <div className="toolbar">
            <label>
              回答语言
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </label>
            <label>
              分析模式
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={allowGeneral}
                onChange={(e) => setAllowGeneral(e.target.checked)}
              />
              允许术语库/通用知识
            </label>
            <button className="ghost" onClick={summarize} disabled={!selected.length || busy}>
              总结选中论文
            </button>
          </div>

          <div className="chat">
            {messages.length === 0 && (
              <div className="welcome">
                <h2>选择论文开始</h2>
                <p>内容问答 → single；比较论文 → compare；提出创新点 → innovate。</p>
              </div>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`message ${message.role}`}>
                <div className="bubble">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
                {message.meta && <div className="meta">{message.meta}</div>}
                {message.claims?.length > 0 && (
                  <div className="claims">
                    <strong>Claim 级检查</strong>
                    {message.claims.map((claim, claimIndex) => (
                      <div key={claimIndex} className={`claim-item ${claim.support}`}>
                        <span>{claim.support === "yes" ? "✅" : claim.support === "partial" ? "⚠️" : claim.support === "uncited" ? "❔" : "❌"}</span>
                        <span>{claim.claim}</span>
                        <em>{claim.reason}</em>
                      </div>
                    ))}
                  </div>
                )}
                {message.citations?.map((citation) => (
                  <Citation key={`${citation.chunk_id}-${index}`} citation={citation} token={token} />
                ))}
              </div>
            ))}
          </div>

          <div className="composer">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="例如：这篇论文的方法是什么？比较这两篇论文，再提出创新点"
            />
            <button className="primary" onClick={send} disabled={busy || !selected.length}>
              {busy ? "处理中…" : "发送"}
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
