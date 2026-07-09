import { useState, useEffect, useCallback } from "react";
import {
  uploadCatalog, uploadItems, runMatching, fetchItems,
  selectMatch, searchCatalogProducts, exportResults, exportResultsBatched,
  fetchMatchCapabilities, fetchCatalogSources,
} from "./api.js";

const BEST_MATCH_THRESHOLD = 0.8;
const BATCH_SIZE = 100;

function tier(score) {
  if (score >= 0.6) return "high";
  if (score >= 0.3) return "medium";
  return "low";
}

function fmtPrice(v) {
  if (v == null) return null;
  return "₸ " + Number(v).toLocaleString("ru-RU");
}

/* ── Manual override search ──────────────────────────────────── */
function ManualOverride({ item, onPicked }) {
  const [open, setOpen] = useState(false);
  const [q, setQ]       = useState("");
  const [results, setResults] = useState([]);

  const search = async (val) => {
    setQ(val);
    if (val.trim().length < 2) { setResults([]); return; }
    const res = await searchCatalogProducts(val);
    setResults(res);
  };

  if (!open) return (
    <div className="override-section">
      <button className="override-trigger" onClick={() => setOpen(true)}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        Найти вручную
      </button>
    </div>
  );

  return (
    <div className="override-section">
      <div className="override-search-box">
        <input
          className="override-input"
          placeholder="Введите название или код…"
          value={q}
          autoFocus
          onChange={(e) => search(e.target.value)}
          onBlur={() => setTimeout(() => { setResults([]); setOpen(false); setQ(""); }, 200)}
        />
        {results.length > 0 && (
          <div className="override-results">
            {results.map((r) => (
              <div
                key={r.id}
                className="override-result-item"
                onMouseDown={() => {
                  onPicked(item.id, r.id);
                  setOpen(false);
                  setResults([]);
                  setQ("");
                }}
              >
                <strong>{r.code || "—"}</strong>&nbsp;&nbsp;
                {r.name}
                {r.brand ? <span style={{ color: "#94a3b8" }}> · {r.brand}</span> : null}
                {r.price ? <span style={{ float: "right", fontWeight: 600 }}>{fmtPrice(r.price)}</span> : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Single match option card ─────────────────────────────────── */
function MatchOption({ match, rank, itemId, onSelect }) {
  const t = tier(match.confidence_score);
  const pct = Math.round(match.confidence_score * 100);
  const p = match.catalog_product;

  return (
    <label className={`match-option ${match.is_selected ? "selected" : ""}`}>
      <input
        type="radio"
        name={`item-${itemId}`}
        checked={match.is_selected}
        onChange={() => onSelect(itemId, p.id)}
      />
      <div className="match-rank">Вариант {rank}</div>

      <div className="confidence-row">
        <span className={`conf-badge ${t}`}>{pct}%</span>
        <div className="conf-bar-wrap">
          <div className={`conf-bar ${t}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      {p.code && <div className="match-code">{p.code}</div>}
      <div className="match-name">{p.name}</div>

      <div className="match-detail">
        <span>{p.brand || ""}{p.model ? ` ${p.model}` : ""}</span>
        {p.price && <span className="match-price">{fmtPrice(p.price)}</span>}
      </div>

      {match.is_manual_override && (
        <div style={{ fontSize: 10.5, color: "#7c3aed", fontWeight: 600, marginTop: 2 }}>
          ✦ Выбрано вручную
        </div>
      )}
    </label>
  );
}

/* ── Item card ────────────────────────────────────────────────── */
function ItemCard({ item, index, onSelect }) {
  const matches = [...item.matches].sort((a, b) => a.rank - b.rank);
  const placeholders = Math.max(0, 3 - matches.length);

  return (
    <div className="item-card">
      {/* left: source item */}
      <div className="item-source">
        <div className="item-index">#{index + 1}</div>
        <div className="item-name">{item.item_name}</div>
        <div className="item-meta">
          {item.item_code && <span className="item-tag">{item.item_code}</span>}
          {item.quantity != null && (
            <span className="item-tag">Кол-во: {item.quantity}</span>
          )}
        </div>
      </div>

      {/* right: match options */}
      <div className="item-matches">
        {matches.length === 0 ? (
          <p className="no-matches-msg">Совпадений не найдено</p>
        ) : (
          <div className="matches-row">
            {matches.map((m, i) => (
              <MatchOption
                key={m.id}
                match={m}
                rank={i + 1}
                itemId={item.id}
                onSelect={onSelect}
              />
            ))}
            {Array.from({ length: placeholders }).map((_, i) => (
              <div key={`ph-${i}`} className="no-match-slot">—</div>
            ))}
          </div>
        )}
        <ManualOverride item={item} onPicked={onSelect} />
      </div>
    </div>
  );
}

/* ── File button ─────────────────────────────────────────────── */
function FileButton({ label, file, onChange }) {
  return (
    <label className={`file-label ${file ? "has-file" : ""}`}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
      </svg>
      {file ? file.name : label}
      <input type="file" accept=".xlsx" onChange={(e) => onChange(e.target.files[0])} />
    </label>
  );
}

/* ── Main app ─────────────────────────────────────────────────── */
export default function App() {
  const [catalogFile, setCatalogFile] = useState(null);
  const [itemsFile,   setItemsFile]   = useState(null);
  const [items,       setItems]       = useState([]);
  const [status,      setStatus]      = useState(null);
  const [loading,     setLoading]     = useState(false);
  const [filter,      setFilter]      = useState("all");
  const [matchMode,   setMatchMode]   = useState("balanced");
  const [capabilities, setCapabilities] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advOpts, setAdvOpts] = useState({
    topK: "",
    minScore: "",
    useEmbeddings: null,
  });
  const [catalogStats, setCatalogStats] = useState({ productCount: 0, sourceName: "government" });
  const [lastCatalogImport, setLastCatalogImport] = useState(null);
  const [lastItemsImport, setLastItemsImport] = useState(null);

  const toast = (type, text) => {
    setStatus({ type, text });
    setTimeout(() => setStatus(null), 5000);
  };

  const load = useCallback(async () => {
    try {
      setItems(await fetchItems());
      const sources = await fetchCatalogSources();
      const gov = sources.find((s) => s.name === "government") || sources[0];
      if (gov) {
        setCatalogStats({ productCount: gov.product_count, sourceName: gov.name });
      } else {
        setCatalogStats({ productCount: 0, sourceName: "government" });
      }
    }
    catch (e) { toast("error", e.message); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    fetchMatchCapabilities()
      .then((c) => {
        setCapabilities(c);
        setMatchMode(c.default_mode || "balanced");
      })
      .catch(() => {});
  }, []);

  const wrap = async (fn) => {
    setLoading(true);
    try { await fn(); }
    catch (e) { toast("error", e.message); }
    finally { setLoading(false); }
  };

  const handleUploadCatalog = () => wrap(async () => {
    if (!catalogFile) return;
    const r = await uploadCatalog(catalogFile);
    setLastCatalogImport({ rows: r.rows_imported, name: catalogFile.name });
    toast("success", `${r.message} — ${r.rows_imported} строк`);
    await load();
  });

  const handleUploadItems = () => wrap(async () => {
    if (!itemsFile) return;
    const r = await uploadItems(itemsFile);
    setLastItemsImport({ rows: r.rows_imported, name: itemsFile.name });
    toast("success", `${r.message} — ${r.rows_imported} строк`);
    await load();
  });

  const handleRunMatching = () => wrap(async () => {
    if (catalogStats.productCount === 0) {
      toast("error", "Сначала загрузите каталог");
      return;
    }
    const opts = { matchingMode: matchMode };
    if (advOpts.topK !== "") opts.topKCandidates = Number(advOpts.topK);
    if (advOpts.minScore !== "") opts.minSimilarityScore = Number(advOpts.minScore);
    if (advOpts.useEmbeddings !== null) opts.useEmbeddings = advOpts.useEmbeddings;

    const r = await runMatching(opts);
    toast("success", `Подбор завершён (${matchMode}) — ${r.items_processed} позиций`);
    await load();
  });

  const handleSelect = async (itemId, productId) => {
    try {
      await selectMatch(itemId, productId);
      await load();
    } catch (e) { toast("error", e.message); }
  };

  const handleExport = (minConf = null) => wrap(async () => {
    await exportResults(minConf);
    toast("success", "Файл экспортирован");
  });

  const handleExportBatched = () => wrap(async () => {
    await exportResultsBatched(BEST_MATCH_THRESHOLD, BATCH_SIZE);
    toast("success", "Архив батчей экспортирован");
  });

  // ── Stats ──────────────────────────────────────────────────────
  const total        = items.length;
  const catalogCount = catalogStats.productCount;
  const itemsCount   = total;
  const hasData      = catalogCount > 0 || itemsCount > 0;
  const matched   = items.filter(i =>
    i.matches.some(m => m.is_selected && m.confidence_score >= BEST_MATCH_THRESHOLD)).length;
  const needsWork = items.filter(i =>
    i.matches.length > 0 &&
    !i.matches.some(m => m.is_selected && m.confidence_score >= BEST_MATCH_THRESHOLD)).length;
  const noMatch   = items.filter(i => i.matches.length === 0).length;

  // ── Filtered items ─────────────────────────────────────────────
  const visible = items.filter(i => {
    if (filter === "matched")
      return i.matches.some(m => m.is_selected && m.confidence_score >= BEST_MATCH_THRESHOLD);
    if (filter === "needs-work")
      return i.matches.length > 0 &&
        !i.matches.some(m => m.is_selected && m.confidence_score >= BEST_MATCH_THRESHOLD);
    if (filter === "no-match")
      return i.matches.length === 0;
    return true;
  });

  return (
    <div className="page">

      {/* ── Header ── */}
      <header className="page-header">
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1>Catalog Matcher</h1>
          <span className="sub">гибрид: код · TF-IDF · fuzzy · семантика</span>
        </div>
        <div className="header-right">
          {loading && <div className="spinner" />}
          <span style={{ fontSize: 12, color: "rgba(255,255,255,.5)" }}>
            каталог: {catalogCount} · позиции: {itemsCount}
          </span>
        </div>
      </header>

      <div className="main">

        {/* ── Workflow steps ── */}
        <div className="workflow-card">

          <div className="workflow-step">
            <div className="step-body">
              <div className="step-label">
                <span className="step-num">1</span>Каталог (.xlsx)
                {catalogCount > 0 && (
                  <span className="step-badge step-badge-catalog">{catalogCount} в БД</span>
                )}
              </div>
              <div className="step-controls">
                <FileButton label="Выбрать файл" file={catalogFile} onChange={setCatalogFile} />
                <button className="btn btn-ghost btn-sm"
                  onClick={handleUploadCatalog} disabled={!catalogFile || loading}>
                  Загрузить
                </button>
              </div>
            </div>
          </div>

          <div className="step-divider" />

          <div className="workflow-step">
            <div className="step-body">
              <div className="step-label">
                <span className="step-num">2</span>Наши позиции (.xlsx)
                {itemsCount > 0 && (
                  <span className="step-badge step-badge-items">{itemsCount} в БД</span>
                )}
              </div>
              <div className="step-controls">
                <FileButton label="Выбрать файл" file={itemsFile} onChange={setItemsFile} />
                <button className="btn btn-ghost btn-sm"
                  onClick={handleUploadItems} disabled={!itemsFile || loading}>
                  Загрузить
                </button>
              </div>
            </div>
          </div>

          <div className="step-divider" />

          <div className="workflow-step">
            <div className="step-body">
              <div className="step-label">
                <span className="step-num">3</span>Запустить подбор
              </div>
              <div className="step-controls match-controls">
                <select
                  className="mode-select"
                  value={matchMode}
                  onChange={(e) => setMatchMode(e.target.value)}
                  disabled={loading}
                  title="Режим сопоставления"
                >
                  {(capabilities?.modes || [
                    { id: "fast", label: "Быстрый" },
                    { id: "balanced", label: "Сбалансированный" },
                    { id: "semantic", label: "Семантический" },
                  ]).map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
                <button className="btn btn-primary"
                  onClick={handleRunMatching} disabled={loading || total === 0}>
                  {loading
                    ? <><div className="spinner" style={{ borderTopColor: "#fff" }} /> Обработка…</>
                    : "▶ Запустить"}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowAdvanced((v) => !v)}
                >
                  {showAdvanced ? "Скрыть" : "Параметры"}
                </button>
              </div>
              {showAdvanced && (
                <div className="advanced-panel">
                  <label>
                    top_k
                    <input
                      type="number"
                      min="5"
                      max="200"
                      placeholder="авто"
                      value={advOpts.topK}
                      onChange={(e) => setAdvOpts({ ...advOpts, topK: e.target.value })}
                    />
                  </label>
                  <label>
                    min score
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.05"
                      placeholder="0.15"
                      value={advOpts.minScore}
                      onChange={(e) => setAdvOpts({ ...advOpts, minScore: e.target.value })}
                    />
                  </label>
                  <label>
                    эмбеддинги
                    <select
                      value={advOpts.useEmbeddings === null ? "" : advOpts.useEmbeddings ? "1" : "0"}
                      onChange={(e) => {
                        const v = e.target.value;
                        setAdvOpts({
                          ...advOpts,
                          useEmbeddings: v === "" ? null : v === "1",
                        });
                      }}
                    >
                      <option value="">из режима</option>
                      <option value="1">вкл</option>
                      <option value="0">выкл</option>
                    </select>
                  </label>
                  {capabilities && !capabilities.embeddings_available && (
                    <span className="adv-hint">Семантика: установите sentence-transformers на backend</span>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="step-divider" />

          <div className="workflow-step">
            <div className="step-body">
              <div className="step-label">
                <span className="step-num">4</span>Экспорт
              </div>
              <div className="step-controls export-btns">
                <button className="btn btn-ghost btn-sm"
                  onClick={() => handleExport()} disabled={loading || total === 0}>
                  Все позиции
                </button>
                <button className="btn btn-ghost btn-sm"
                  onClick={() => handleExport(BEST_MATCH_THRESHOLD)} disabled={loading || total === 0}>
                  ≥{BEST_MATCH_THRESHOLD * 100}%
                </button>
                <button className="btn btn-green btn-sm"
                  onClick={handleExportBatched} disabled={loading || total === 0}>
                  Батчи .zip
                </button>
              </div>
            </div>
          </div>

        </div>

        {/* ── Status bar ── */}
        {status && (
          <div className={`status-bar ${status.type}`}>
            {status.type === "success" ? "✓" : "✕"}&nbsp;{status.text}
          </div>
        )}

        {/* ── Loaded data summary ── */}
        {hasData && (
          <div className="data-summary">
            <div className="data-summary-title">Загружено в базу</div>
            <div className="data-summary-row">
              <div className={`data-card ${catalogCount > 0 ? "ok" : "empty"}`}>
                <div className="data-card-label">Каталог (шаг 1)</div>
                <div className="data-card-value">{catalogCount || "—"}</div>
                <div className="data-card-hint">
                  {lastCatalogImport
                    ? `${lastCatalogImport.name}: ${lastCatalogImport.rows} строк`
                    : catalogCount > 0 ? "готов к сопоставлению" : "загрузите файл"}
                </div>
              </div>
              <div className={`data-card ${itemsCount > 0 ? "ok" : "empty"}`}>
                <div className="data-card-label">Наши позиции (шаг 2)</div>
                <div className="data-card-value">{itemsCount || "—"}</div>
                <div className="data-card-hint">
                  {lastItemsImport
                    ? `${lastItemsImport.name}: ${lastItemsImport.rows} строк`
                    : itemsCount > 0 ? "готов к сопоставлению" : "загрузите файл"}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Matching results stats ── */}
        {itemsCount > 0 && (
          <div className="stats-strip">
            <div className="stat-pill">
              <div>
                <div className="sv">{itemsCount}</div>
                <div className="sl">Позиций для подбора</div>
              </div>
            </div>
            <div className="stat-pill green">
              <div>
                <div className="sv">{matched}</div>
                <div className="sl">Подобрано ≥{BEST_MATCH_THRESHOLD * 100}%</div>
              </div>
            </div>
            <div className="stat-pill amber">
              <div>
                <div className="sv">{needsWork}</div>
                <div className="sl">Требует проверки</div>
              </div>
            </div>
            <div className="stat-pill red">
              <div>
                <div className="sv">{noMatch}</div>
                <div className="sl">Без совпадений</div>
              </div>
            </div>
          </div>
        )}

        {/* ── Filter tabs ── */}
        {total > 0 && (
          <div className="filter-bar">
            {[
              { id: "all",        label: `Все (${total})` },
              { id: "matched",    label: `Подобраны (${matched})` },
              { id: "needs-work", label: `Проверить (${needsWork})` },
              { id: "no-match",   label: `Без совпадений (${noMatch})` },
            ].map(f => (
              <button key={f.id}
                className={`filter-tab ${filter === f.id ? "active" : ""}`}
                onClick={() => setFilter(f.id)}>
                {f.label}
              </button>
            ))}
          </div>
        )}

        {/* ── Items list ── */}
        {itemsCount === 0 && catalogCount > 0 ? (
          <div className="empty-state">
            <p>Каталог загружен ({catalogCount} товаров). Загрузите список позиций (шаг 2).</p>
          </div>
        ) : itemsCount === 0 ? (
          <div className="empty-state">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none"
              stroke="#94a3b8" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            <p>Загрузите каталог и список позиций, затем запустите подбор</p>
          </div>
        ) : visible.length === 0 ? (
          <div className="empty-state">
            <p>Нет позиций по выбранному фильтру</p>
          </div>
        ) : (
          visible.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              index={items.indexOf(item)}
              onSelect={handleSelect}
            />
          ))
        )}

      </div>
    </div>
  );
}
