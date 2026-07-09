const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res;
}

export async function uploadCatalog(file, sourceName = "government") {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload/catalog?source_name=${encodeURIComponent(sourceName)}`, {
    method: "POST",
    body: form,
  });
  await handle(res);
  return res.json();
}

export async function uploadItems(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload/items`, { method: "POST", body: form });
  await handle(res);
  return res.json();
}

export async function fetchCatalogSources() {
  const res = await fetch(`${BASE}/catalog-sources`);
  await handle(res);
  return res.json();
}

export async function fetchMatchCapabilities() {
  const res = await fetch(`${BASE}/match/capabilities`);
  await handle(res);
  return res.json();
}

export async function runMatching(options = {}) {
  const {
    sourceName = "government",
    matchingMode = "balanced",
    topKCandidates = null,
    topNResults = null,
    minSimilarityScore = null,
    useCodeMatching = null,
    useTfidf = null,
    useFuzzyText = null,
    useEmbeddings = null,
    embeddingModel = null,
    embedCatalogIfMissing = true,
  } = options;

  const body = {
    source_name: sourceName,
    matching_mode: matchingMode,
    embed_catalog_if_missing: embedCatalogIfMissing,
  };
  if (topKCandidates != null) body.top_k_candidates = topKCandidates;
  if (topNResults != null) body.top_n_results = topNResults;
  if (minSimilarityScore != null) body.min_similarity_score = minSimilarityScore;
  if (useCodeMatching != null) body.use_code_matching = useCodeMatching;
  if (useTfidf != null) body.use_tfidf = useTfidf;
  if (useFuzzyText != null) body.use_fuzzy_text = useFuzzyText;
  if (useEmbeddings != null) body.use_embeddings = useEmbeddings;
  if (embeddingModel != null) body.embedding_model = embeddingModel;

  const res = await fetch(`${BASE}/match/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await handle(res);
  return res.json();
}

export async function fetchItems() {
  const res = await fetch(`${BASE}/items`);
  await handle(res);
  return res.json();
}

export async function selectMatch(itemId, catalogProductId) {
  const res = await fetch(`${BASE}/match/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: itemId, catalog_product_id: catalogProductId }),
  });
  await handle(res);
  return res.json();
}

export async function searchCatalogProducts(q, sourceName = "government") {
  const res = await fetch(
    `${BASE}/catalog-products/search?q=${encodeURIComponent(q)}&source_name=${encodeURIComponent(sourceName)}`
  );
  await handle(res);
  return res.json();
}

function downloadBlobResponse(res, fallbackFilename) {
  return res.blob().then((blob) => {
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : fallbackFilename;

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  });
}

export async function exportResults(minConfidence = null) {
  const qs = minConfidence != null ? `?min_confidence=${minConfidence}` : "";
  const res = await fetch(`${BASE}/export${qs}`, { method: "POST" });
  await handle(res);
  await downloadBlobResponse(res, "Export.xlsx");
}

export async function exportResultsBatched(minConfidence = 0.8, batchSize = 100) {
  const params = new URLSearchParams({
    min_confidence: minConfidence,
    batch_size: batchSize,
  });
  const res = await fetch(`${BASE}/export/batches?${params.toString()}`, { method: "POST" });
  await handle(res);
  await downloadBlobResponse(res, "Best_Matches_batches.zip");
}
