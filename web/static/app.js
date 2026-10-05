const IBGE_TO_UF = {
  11: "ro", 12: "ac", 13: "am", 14: "rr", 15: "pa", 16: "ap", 17: "to",
  21: "ma", 22: "pi", 23: "ce", 24: "rn", 25: "pb", 26: "pe", 27: "al",
  28: "se", 29: "ba", 31: "mg", 32: "es", 33: "rj", 35: "sp", 41: "pr",
  42: "sc", 43: "rs", 50: "ms", 51: "mt", 52: "go", 53: "df",
};

const GEOJSON_URL =
  "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF";

const FALLBACK_GEO =
  "https://cdn.jsdelivr.net/gh/codeforamerica/click_that_hood@master/public/data/brazil-states.geojson";

const NAME_TO_UF = {
  acre: "ac", alagoas: "al", amapa: "ap", amapá: "ap", amazonas: "am", bahia: "ba",
  ceara: "ce", ceará: "ce", "distrito federal": "df", "espirito santo": "es",
  "espírito santo": "es", goias: "go", goiás: "go", maranhao: "ma", maranhão: "ma",
  "mato grosso": "mt", "mato grosso do sul": "ms", "minas gerais": "mg", para: "pa",
  pará: "pa", paraiba: "pb", paraíba: "pb", parana: "pr", paraná: "pr",
  pernambuco: "pe", piaui: "pi", piauí: "pi", "rio de janeiro": "rj",
  "rio grande do norte": "rn", "rio grande do sul": "rs", rondonia: "ro",
  rondônia: "ro", roraima: "rr", "santa catarina": "sc", "sao paulo": "sp",
  "são paulo": "sp", sergipe: "se", tocantins: "to",
};

const PRES_COLORS = [
  "#0f6b5c", "#c4a35a", "#1c4d7a", "#b45309", "#7aa89e",
  "#6b3fa0", "#8a8172", "#2f855a", "#9b2c2c", "#2b6cb0", "#744210", "#4a5568",
];

let charts = {};
let map, geoLayer, ufIndex = {}, voteUfIndex = {}, selectedUf = null;
let selectedModelo = null;
let lastPresNational = null;
let lastUfRows = [];

const fmt = new Intl.NumberFormat("pt-BR");
const fmtPct = (n) => `${(n * 100).toFixed(1)}%`;
const fmtBytes = (n) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
};

async function j(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path);
  return r.json();
}

function kpi(label, value) {
  return `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div></div>`;
}

function parseSortValue(text, type) {
  const t = (text || "").trim();
  if (!t || t === "—") return null;
  if (type === "text") return t.toLocaleLowerCase("pt-BR");
  if (type === "bytes") {
    const m = t.match(/^([\d.,]+)\s*([KMGT]?B)$/i);
    if (!m) return null;
    const n = Number(m[1].replace(",", "."));
    const mult = { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4 };
    return Number.isFinite(n) ? n * (mult[m[2].toUpperCase()] || 1) : null;
  }
  let s = t.replace(/%/g, "").trim();
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",") && !s.includes(".")) {
    s = s.replace(",", ".");
  } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, "");
  }
  const n = Number(s);
  if (type === "num" || type === "pct") return Number.isFinite(n) ? n : null;
  if (Number.isFinite(n) && /[\d%]/.test(t) && !/[a-zA-ZÀ-ú]{2,}/.test(t)) return n;
  return t.toLocaleLowerCase("pt-BR");
}

function applyTableSort(table, colIdx, dir) {
  const ths = table.querySelectorAll("thead th");
  const th = ths[colIdx];
  if (!th) return;
  table.dataset.sortCol = String(colIdx);
  table.dataset.sortDir = dir;
  ths.forEach((h, i) => {
    h.classList.toggle("sort-asc", i === colIdx && dir === "asc");
    h.classList.toggle("sort-desc", i === colIdx && dir === "desc");
  });
  const tbody = table.tBodies[0];
  if (!tbody) return;
  const type = th.dataset.type || "auto";
  const mult = dir === "asc" ? 1 : -1;
  const rows = Array.from(tbody.rows);
  rows.sort((a, b) => {
    const av = parseSortValue(a.cells[colIdx]?.textContent, type);
    const bv = parseSortValue(b.cells[colIdx]?.textContent, type);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
    return String(av).localeCompare(String(bv), "pt-BR", { numeric: true, sensitivity: "base" }) * mult;
  });
  rows.forEach((r) => tbody.appendChild(r));
}

function reapplyTableSort(tbodyId) {
  const tbody = document.getElementById(tbodyId);
  const table = tbody?.closest("table.sortable");
  if (!table || table.dataset.sortCol == null || table.dataset.sortCol === "") return;
  applyTableSort(table, Number(table.dataset.sortCol), table.dataset.sortDir || "asc");
}

function initSortableTables() {
  document.querySelectorAll("table.sortable").forEach((table) => {
    table.querySelectorAll("thead th").forEach((th, idx) => {
      th.title = "Clique para ordenar";
      th.addEventListener("click", (e) => {
        e.stopPropagation();
        const prev = table.dataset.sortCol;
        const prevDir = table.dataset.sortDir || "asc";
        let dir;
        if (prev === String(idx)) {
          dir = prevDir === "asc" ? "desc" : "asc";
        } else {
          const type = th.dataset.type || "auto";
          dir = type === "text" ? "asc" : "desc";
        }
        applyTableSort(table, idx, dir);
      });
    });
  });
}

function palette() {
  return { teal: "#0f6b5c", gold: "#c4a35a", ink: "#1c1914", muted: "#8a8172" };
}

function chartDefaults() {
  Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
  Chart.defaults.color = "#6b6458";
}

function upsertChart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function colorScale(t) {
  const a = [232, 239, 233];
  const b = [15, 107, 92];
  const mix = (i) => Math.round(a[i] + (b[i] - a[i]) * t);
  return `rgb(${mix(0)}, ${mix(1)}, ${mix(2)})`;
}

function metricValue(row, metric, uf = null) {
  const key = uf || row?.uf;
  if (metric === "lider_pct") return (voteUfIndex[key]?.lider?.pct || 0) / 100;
  if (metric === "votos_modelo") return voteUfIndex[key]?.votos_validos || 0;
  if (!row) return 0;
  if (metric === "secoes") return row.secoes;
  if (metric === "cobertura_log") return row.cobertura_log;
  if (metric === "cobertura_aux") return row.cobertura_aux;
  if (metric === "totalizada") return row.totalizada;
  return 0;
}

function ufFromFeature(feat) {
  const p = feat.properties || {};
  const cod = String(p.codarea || p.codigo || p.CD_GEOCUF || "").replace(/^0+/, "");
  if (IBGE_TO_UF[cod]) return IBGE_TO_UF[cod];
  const name = (p.name || p.NOME_UF || p.NM_UF || "").toLowerCase();
  return NAME_TO_UF[name] || null;
}

function paintMap() {
  if (!geoLayer) return;
  const metric = document.getElementById("mapMetric").value;
  const voteMetrics = metric === "votos_modelo" || metric === "lider_pct";
  const values = voteMetrics
    ? Object.keys(voteUfIndex).map((uf) => metricValue(null, metric, uf))
    : Object.values(ufIndex).map((r) => metricValue(r, metric));
  const max = Math.max(1e-9, ...values);
  geoLayer.setStyle((feat) => {
    const uf = ufFromFeature(feat);
    const row = ufIndex[uf];
    const vote = voteUfIndex[uf];
    const v = metricValue(row, metric, uf);
    const t = metric.startsWith("cobertura") || metric === "lider_pct" ? v : v / max;
    const hasData = voteMetrics
      ? !!(vote && (vote.votos_validos || vote.lider))
      : !!row;
    return {
      color: "#fffdf8",
      weight: selectedUf === uf ? 2.4 : 1,
      fillColor: hasData ? colorScale(Math.min(1, t)) : "#d9d0bf",
      fillOpacity: 0.92,
    };
  });
}

async function loadGeo() {
  try {
    const r = await fetch(GEOJSON_URL);
    if (!r.ok) throw new Error("ibge");
    return await r.json();
  } catch {
    const r = await fetch(FALLBACK_GEO);
    return r.json();
  }
}

function initMap(geo) {
  map = L.map("map", { zoomControl: true, attributionControl: true }).setView([-14.2, -52.2], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap · malha IBGE",
    maxZoom: 12,
  }).addTo(map);
  geoLayer = L.geoJSON(geo, {
    style: { color: "#fff", weight: 1, fillOpacity: 0.9 },
    onEachFeature: (feat, layer) => {
      const uf = ufFromFeature(feat);
      layer.on("click", () => selectUf(uf));
      layer.on("mouseover", () => {
        const row = ufIndex[uf];
        const vote = voteUfIndex[uf];
        const nome = row ? row.nome : (uf || "?").toUpperCase();
        const modeloNote = selectedModelo
          ? `<br><em>${selectedModelo}</em>: ${fmt.format(vote?.votos_validos || 0)} votos`
          : "";
        const lider = vote?.lider
          ? `<br>líder: ${vote.lider.nome} (${vote.lider.pct_str || vote.lider.pct}%)`
          : "";
        layer.bindTooltip(
          row
            ? `<strong>${nome}</strong><br>${fmt.format(row.secoes)} seções<br>logs ${fmtPct(row.cobertura_log)}${modeloNote}${lider}`
            : nome,
          { sticky: true, className: "info-box" }
        ).openTooltip();
      });
    },
  }).addTo(map);
  paintMap();
}

function munFilterLabel() {
  const base = selectedUf ? selectedUf.toUpperCase() : "Brasil";
  return selectedModelo ? `${base} · ${selectedModelo}` : base;
}

async function selectUf(uf) {
  selectedUf = uf && selectedUf === uf ? null : uf;
  document.getElementById("munFilter").textContent = munFilterLabel();
  paintMap();
  await renderMunicipios();
  highlightUfTable();
}

function highlightUfTable() {
  document.querySelectorAll("#ufBody tr").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.uf === selectedUf);
  });
}

function modeloQuerySuffix(prefix = "?") {
  if (!selectedModelo) return "";
  const sep = prefix.includes("?") ? "&" : prefix;
  return `${sep}modelo=${encodeURIComponent(selectedModelo)}`;
}

async function renderMunicipios() {
  const base = selectedUf ? `?uf=${selectedUf}&limit=40` : "?limit=40";
  const data = await j(`/api/municipios${base}${modeloQuerySuffix(base)}`);
  document.getElementById("munFilter").textContent = munFilterLabel();
  document.getElementById("munBody").innerHTML = data.municipios.length
    ? data.municipios
        .map(
          (m) => `<tr>
        <td>${m.uf.toUpperCase()}</td>
        <td>${m.municipio_nm || m.municipio_cd}</td>
        <td>${fmt.format(m.secoes)}</td>
        <td>${m.logs_ok ? fmt.format(m.logs_ok) : "—"}</td>
      </tr>`
        )
        .join("")
    : `<tr><td colspan="4">${
        selectedModelo
          ? `Nenhum município com seções do modelo ${selectedModelo}`
          : "sem municípios"
      }</td></tr>`;
  reapplyTableSort("munBody");
}

function renderKpis(ov) {
  const cobertura = ov.secoes ? ov.logs_ok / ov.secoes : 0;
  document.getElementById("kpis").innerHTML = [
    kpi("Seções", fmt.format(ov.secoes)),
    kpi("Municípios", fmt.format(ov.municipios)),
    kpi("Aux baixado", fmt.format(ov.aux_ok)),
    kpi("Logs ok", fmt.format(ov.logs_ok)),
    kpi("Cobertura logs", fmtPct(cobertura)),
    kpi("Volume logs", fmtBytes(ov.bytes_ok)),
  ].join("");
  const m = ov.meta || {};
  document.getElementById("metaLine").innerHTML =
    `${m.eleicao_nome || "Eleição"} · pleito ${m.pleito || "—"} · turno ${m.turno || "—"}<br>
     banco ${ov.db_name || "—"} · ${fmtBytes(ov.db_bytes || 0)}`;
}

function renderUfTable(rows) {
  document.getElementById("ufBody").innerHTML = rows
    .map((r) => {
      const lider = voteUfIndex[r.uf]?.lider;
      return `<tr data-uf="${r.uf}">
        <td>${r.uf.toUpperCase()}</td>
        <td>${r.nome}</td>
        <td>${fmt.format(r.municipios)}</td>
        <td>${fmt.format(r.secoes)}</td>
        <td>${fmt.format(r.aux_ok)}</td>
        <td>${fmt.format(r.totalizada)}</td>
        <td>${fmt.format(r.logs_ok)}</td>
        <td>${fmtBytes(r.bytes_ok)}</td>
        <td>${lider ? lider.nome : "—"}</td>
        <td>${lider ? `${lider.pct_str || lider.pct}%` : "—"}</td>
      </tr>`;
    })
    .join("");
  document.querySelectorAll("#ufBody tr").forEach((tr) => {
    tr.addEventListener("click", () => selectUf(tr.dataset.uf));
  });
  reapplyTableSort("ufBody");
  highlightUfTable();
}

function buUfCoverage(pres) {
  const fromApi = pres?.n_ufs ?? pres?.brasil?.n_ufs;
  if (fromApi != null) return Number(fromApi) || 0;
  return Object.keys(voteUfIndex).filter((uf) => (voteUfIndex[uf]?.votos_validos || 0) > 0).length;
}

function inventoryUfCoverage() {
  return lastUfRows.filter((r) => (r.secoes || 0) > 0).length;
}

function buCoverageNote(pres) {
  if (!selectedModelo) return "";
  const nUfs = buUfCoverage(pres);
  const nSec = pres?.n_secoes ?? pres?.brasil?.n_secoes ?? 0;
  const ufsLabel = nUfs === 1 ? "1 UF" : `${fmt.format(nUfs)} UFs`;
  return (
    `${ufsLabel} com BUs sincronizados para ${selectedModelo}` +
    ` (${fmt.format(nSec)} seções). Amostra parcial — não é cobertura nacional.`
  );
}

function inventoryCoverageNote() {
  if (!selectedModelo) return "";
  const nUfs = inventoryUfCoverage();
  const nSec = lastUfRows.reduce((s, r) => s + (r.secoes || 0), 0);
  const ufsLabel = nUfs === 1 ? "1 UF" : `${fmt.format(nUfs)} UFs`;
  return `${ufsLabel} com seções ${selectedModelo} no inventário (${fmt.format(nSec)} seções).`;
}

function updateBuCoverageHints(pres) {
  const invNote = inventoryCoverageNote();
  const buNote = buCoverageNote(pres);
  const chartHint = document.getElementById("chartUfsHint");
  const mapHint = document.getElementById("mapHint");
  const metric = document.getElementById("mapMetric")?.value;
  const voteMetric = metric === "votos_modelo" || metric === "lider_pct";
  if (chartHint) {
    chartHint.textContent = selectedModelo
      ? `${invNote}${buNote ? ` BUs (aba Presidente / métrica votos): ${buNote}` : ""}`
      : "";
  }
  if (selectedModelo && mapHint) {
    mapHint.textContent = voteMetric && buNote
      ? `${buNote} Mapa colorido só onde há BU; cinza = sem BU deste modelo. Clique em um estado para municípios.`
      : `${invNote || "Filtro de modelo ativo."} Clique em um estado para municípios.`;
  }
}

function updateGeoFilterChrome(pres) {
  const geoSub = document.getElementById("geoSub");
  const mapHint = document.getElementById("mapHint");
  const chartTitle = document.getElementById("chartUfsTitle");
  const chartHint = document.getElementById("chartUfsHint");
  const ufPill = document.getElementById("ufFilterPill");
  const metricSel = document.getElementById("mapMetric");
  const votosOpt = metricSel?.querySelector('option[value="votos_modelo"]');
  if (selectedModelo) {
    const invNote = inventoryCoverageNote();
    geoSub.textContent =
      `Filtro ${selectedModelo} ativo: mapa, gráfico e Detalhe por UF usam seções do inventário (modelo_urna). ` +
      `Votos de Presidente (BU) ficam na aba Presidente e na métrica “Votos (modelo filtrado)”. ` +
      (invNote || "Clique em outro modelo ou limpe o filtro.");
    chartTitle.textContent = `Seções por UF (${selectedModelo})`;
    if (ufPill) {
      const nUfs = inventoryUfCoverage();
      ufPill.textContent = nUfs ? `${selectedModelo} · ${nUfs} UF` : selectedModelo;
      ufPill.classList.remove("hidden");
    }
    if (votosOpt) votosOpt.disabled = false;
    updateBuCoverageHints(pres);
  } else {
    geoSub.textContent =
      "Clique em um modelo UE para filtrar votos, mapa, Detalhe por UF e municípios. A fatia “(faltando)” não aplica filtro.";
    mapHint.textContent =
      "Clique em um estado para filtrar municípios. Exterior (ZZ) não entra no mapa.";
    chartTitle.textContent = "Seções por UF";
    if (chartHint) chartHint.textContent = "";
    if (ufPill) {
      ufPill.textContent = "";
      ufPill.classList.add("hidden");
    }
    if (votosOpt) votosOpt.disabled = true;
    if (metricSel?.value === "votos_modelo") metricSel.value = "secoes";
  }
  const munEl = document.getElementById("munFilter");
  if (munEl) munEl.textContent = munFilterLabel();
}

function applyVoteUfIndex(pres) {
  voteUfIndex = Object.fromEntries((pres?.ufs || []).map((u) => [u.uf, u]));
}

function updateModeloFilterChrome(pres) {
  const pill = document.getElementById("modeloFilterPill");
  const btn = document.getElementById("btnClearModelo");
  const modelo = selectedModelo || pres?.filtro_modelo || null;
  if (!modelo) {
    pill.classList.add("hidden");
    btn.classList.add("hidden");
    pill.textContent = "";
    updateGeoFilterChrome(pres);
    return;
  }
  const nInv = lastUfRows.reduce((s, r) => s + (r.secoes || 0), 0);
  const nUfs = inventoryUfCoverage();
  const ufPart = nUfs ? ` · ${nUfs} UF` : "";
  const nBu = pres?.n_secoes ?? pres?.brasil?.n_secoes ?? 0;
  const buPart = nBu ? ` · ${fmt.format(nBu)} BU` : "";
  pill.textContent = `${modelo} · ${fmt.format(nInv)} seções${ufPart}${buPart}`;
  pill.classList.remove("hidden");
  btn.classList.remove("hidden");
  updateGeoFilterChrome(pres);
}

function renderPresidente(pres) {
  const br = pres?.brasil;
  if (!br || !(br.candidatos || []).length) {
    document.getElementById("presStamp").textContent = "sem dados";
    document.getElementById("presKpis").innerHTML = [
      kpi("Apurado", "—"),
      kpi("Votos válidos", "—"),
      kpi("Brancos", "—"),
      kpi("Nulos", "—"),
    ].join("");
    upsertChart("chartPres", {
      type: "bar",
      data: { labels: ["sem dados"], datasets: [{ data: [0], backgroundColor: ["#c4bbb0"], borderRadius: 6 }] },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { grid: { color: "#efe8d8" } }, y: { grid: { display: false } } },
      },
    });
    document.getElementById("presBody").innerHTML =
      `<tr><td colspan="6">${
        pres?.error
          || "Sem totais de Presidente neste banco. Para 2022, rode sync_votos_presidente_csv.py (CSV Dados Abertos)."
      }</td></tr>`;
    updateModeloFilterChrome(pres);
    applyVoteUfIndex(pres);
    return;
  }
  const filtered = !!(selectedModelo || pres?.filtro_modelo);
  document.getElementById("presStamp").textContent = filtered
    ? (pres.filtro_modelo || selectedModelo || "filtro")
    : (br.atualizado_em || "BR");
  updateModeloFilterChrome(pres);

  const kpis = filtered
    ? [
        kpi("Modelo", pres.filtro_modelo || selectedModelo || "—"),
        kpi("Seções com BU", fmt.format(pres.n_secoes ?? br.n_secoes ?? 0)),
        kpi("UFs com BU", fmt.format(pres.n_ufs ?? br.n_ufs ?? buUfCoverage(pres))),
        kpi("Votos válidos", fmt.format(br.votos_validos || 0)),
      ]
    : [
        kpi("Apurado", br.secoes_totalizadas_pct ? `${br.secoes_totalizadas_pct}%` : "—"),
        kpi("Votos válidos", fmt.format(br.votos_validos)),
        kpi("Brancos", fmt.format(br.votos_brancos)),
        kpi("Nulos", fmt.format(br.votos_nulos)),
      ];
  document.getElementById("presKpis").innerHTML = kpis.join("");

  const top = (br.candidatos || []).slice(0, 8);
  upsertChart("chartPres", {
    type: "bar",
    data: {
      labels: top.length ? top.map((c) => `${c.numero} · ${c.nome}`) : ["sem BU"],
      datasets: [{
        data: top.length ? top.map((c) => c.votos) : [0],
        backgroundColor: top.map((_, i) => PRES_COLORS[i % PRES_COLORS.length]),
        borderRadius: 6,
      }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { grid: { color: "#efe8d8" } }, y: { grid: { display: false } } },
    },
  });

  const body = br.candidatos || [];
  document.getElementById("presBody").innerHTML = body.length
    ? body
        .map(
          (c, i) => `<tr>
        <td>${i + 1}</td>
        <td>${c.numero}</td>
        <td>${c.nome}</td>
        <td>${c.partido}</td>
        <td>${fmt.format(c.votos)}</td>
        <td>${c.pct_str || c.pct}%</td>
      </tr>`
        )
        .join("")
    : `<tr><td colspan="6">${
        filtered
          ? `Nenhuma seção com BU parseado para ${selectedModelo || pres.filtro_modelo}. Rode sync_votos_secao_bu.py`
          : "sem candidatos"
      }</td></tr>`;
  reapplyTableSort("presBody");

  applyVoteUfIndex(pres);
  updateBuCoverageHints(pres);
  if (lastUfRows.length) {
    renderUfTable(lastUfRows);
  }
  renderUfChart(lastUfRows);
  paintMap();
}

async function loadUfRowsForFilter() {
  const q = selectedModelo ? `?modelo=${encodeURIComponent(selectedModelo)}` : "";
  const data = await j(`/api/ufs${q}`);
  ufIndex = Object.fromEntries((data.ufs || []).map((r) => [r.uf, r]));
  lastUfRows = data.ufs || [];
  return lastUfRows;
}

async function loadPresidenteForFilter() {
  if (!selectedModelo) {
    const [pres] = await Promise.all([
      lastPresNational ? Promise.resolve(lastPresNational) : j("/api/presidente"),
      loadUfRowsForFilter(),
    ]);
    if (!lastPresNational) lastPresNational = pres;
    renderPresidente(pres);
    await renderMunicipios();
    return pres;
  }
  const [pres] = await Promise.all([
    j(`/api/presidente?modelo=${encodeURIComponent(selectedModelo)}`),
    loadUfRowsForFilter(),
  ]);
  renderPresidente(pres);
  await renderMunicipios();
  return pres;
}

function alignMapMetricToInventory() {
  const metricSel = document.getElementById("mapMetric");
  if (!metricSel) return;
  // Ao ativar filtro de modelo, alinhar ao inventário (mesmo critério do Detalhe por UF).
  // Votos BU ficam na métrica opcional "votos_modelo" e na aba Presidente.
  if (metricSel.value === "votos_modelo" || metricSel.value === "lider_pct") {
    metricSel.value = "secoes";
  }
}

async function selectModelo(modelo, filterable = true) {
  if (!modelo || !filterable || modelo.startsWith("(")) {
    // fatia "(faltando)" / placeholders: não filtram mapa nem votos
    if (selectedModelo) {
      selectedModelo = null;
      highlightModeloTable();
      await loadPresidenteForFilter();
    }
    return;
  }
  const next = selectedModelo === modelo ? null : modelo;
  const activating = !!next && next !== selectedModelo;
  selectedModelo = next;
  highlightModeloTable();
  if (activating) alignMapMetricToInventory();
  await loadPresidenteForFilter();
}

function clearModeloFilter() {
  selectedModelo = null;
  highlightModeloTable();
  return loadPresidenteForFilter();
}

function highlightModeloTable() {
  document.querySelectorAll("#modBody tr").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.modelo === selectedModelo);
  });
}

function renderModelos(mod) {
  const items = mod.items || [];
  const missingColor = "#c4bbb0";
  let colorIdx = 0;
  const colors = items.map((i) => {
    if (i.missing) return missingColor;
    const c = PRES_COLORS[colorIdx % PRES_COLORS.length];
    colorIdx += 1;
    return c;
  });
  upsertChart("chartModelos", {
    type: "doughnut",
    data: {
      labels: items.map((i) => i.modelo),
      datasets: [{
        data: items.map((i) => i.votos ?? i.votos_validos ?? 0),
        backgroundColor: colors,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
      },
      cutout: "55%",
      onClick: (_evt, elements) => {
        if (!elements.length) return;
        const idx = elements[0].index;
        const row = items[idx];
        if (row) selectModelo(row.modelo, row.filterable !== false && !row.missing);
      },
    },
  });
  const atrib = mod.votos_atribuidos ?? items.filter((i) => !i.missing).reduce((s, i) => s + (i.votos || 0), 0);
  const falt = mod.votos_faltando ?? 0;
  const oficial = mod.votos_validos_br ?? 0;
  const invent = mod.source === "inventario";
  const votosTh = document.querySelector("#modelos table.sortable thead th:nth-child(2)");
  if (votosTh) votosTh.textContent = invent ? "Seções" : "Votos";
  document.getElementById("modHint").textContent = !items.length
    ? "Sem dados de modelo nesta eleição."
    : invent
      ? `${fmt.format(atrib)} seções com modelo identificado · ${fmt.format(mod.total_com_log || 0)} logs ok. ` +
        (mod.hint || "")
      : `${fmt.format(atrib)} votos atribuidos a modelos (BU/CSV) · ${fmt.format(falt)} faltando · ` +
        `oficial BR ${fmt.format(oficial)} validos` +
        (oficial > 0 && atrib > 0
          ? ` · cobertura ${(atrib / oficial * 100).toFixed(1).replace(".", ",")}% do Brasil`
          : "") +
        `. ` +
        (mod.hint || "Faltando = max(0, oficiais BR - soma por modelo).") +
        " Clique em um modelo UE para filtrar; a fatia (faltando) nao aplica filtro.";
  const fmtVotePct = (n) =>
    n == null || Number.isNaN(Number(n)) ? "—" : (Number(n).toFixed(1).replace(".", ",") + "%");
  const fmtSharePct = (n) => {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const pct = Number(n) * 100;
    const digits = pct >= 10 ? 1 : pct >= 1 ? 2 : 3;
    return pct.toFixed(digits).replace(".", ",") + "%";
  };
  document.getElementById("modBody").innerHTML = items
    .map(
      (i) => {
        const filterable = i.filterable !== false && !i.missing;
        const flag = filterable ? "1" : "0";
        const cls = i.missing ? " class=\"missing\"" : "";
        return (
          "<tr data-modelo=\"" + i.modelo + "\" data-filterable=\"" + flag + "\"" + cls + ">" +
          "<td>" + i.modelo + "</td>" +
          "<td>" + fmt.format(i.votos ?? i.votos_validos ?? 0) + "</td>" +
          "<td>" + fmtVotePct(i.pct_pl) + "</td>" +
          "<td>" + fmtVotePct(i.pct_pt) + "</td>" +
          "<td>" + fmtSharePct(i.pct) + "</td>" +
          "</tr>"
        );
      }
    )
    .join("");
  document.querySelectorAll("#modBody tr").forEach((tr) => {
    tr.addEventListener("click", () =>
      selectModelo(tr.dataset.modelo, tr.dataset.filterable !== "0")
    );
  });
  reapplyTableSort("modBody");
  highlightModeloTable();
}

function renderUfChart(ufRows) {
  // Mesma fonte do Detalhe por UF: inventário secoes (com ou sem filtro modelo).
  const c = palette();
  const rows = ufRows || lastUfRows || [];
  const top = [...rows].filter((r) => (r.secoes || 0) > 0).sort((a, b) => b.secoes - a.secoes);
  upsertChart("chartUfs", {
    type: "bar",
    data: {
      labels: top.length ? top.map((r) => r.uf.toUpperCase()) : ["sem dados"],
      datasets: [{
        data: top.length ? top.map((r) => r.secoes) : [0],
        backgroundColor: selectedModelo ? c.gold : c.teal,
        borderRadius: 6,
      }],
    },
    options: {
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: { x: { grid: { color: "#efe8d8" } }, y: { grid: { display: false } } },
    },
  });
}

function renderCharts(ufRows, aux, apu, tam) {
  const c = palette();
  renderUfChart(ufRows);

  upsertChart("chartAux", {
    type: "doughnut",
    data: {
      labels: aux.items.map((i) => i.status),
      datasets: [{ data: aux.items.map((i) => i.count), backgroundColor: [c.teal, c.gold, c.muted, "#7aa89e"] }],
    },
    options: { plugins: { legend: { position: "bottom" } }, cutout: "58%" },
  });

  upsertChart("chartDatas", {
    type: "bar",
    data: {
      labels: apu.por_data.map((d) => d.data),
      datasets: [{ data: apu.por_data.map((d) => d.count), backgroundColor: c.gold, borderRadius: 8 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: "#efe8d8" } } } },
  });

  upsertChart("chartHoras", {
    type: "line",
    data: {
      labels: apu.por_hora.map((h) => h.hora),
      datasets: [{
        data: apu.por_hora.map((h) => h.count),
        borderColor: c.teal,
        backgroundColor: "rgba(15,107,92,.15)",
        fill: true,
        tension: 0.35,
        pointRadius: 0,
      }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: "#efe8d8" } } } },
  });

  upsertChart("chartTam", {
    type: "bar",
    data: {
      labels: tam.histogram.map((b) => `${Math.round(b.from / 1024)}–${Math.round(b.to / 1024)} KB`),
      datasets: [{ data: tam.histogram.map((b) => b.count), backgroundColor: c.teal, borderRadius: 6 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { grid: { color: "#efe8d8" } } } },
  });
  document.getElementById("tamHint").textContent = tam.n
    ? `${fmt.format(tam.n)} arquivos · média ${fmtBytes(tam.avg)} · mediana ${fmtBytes(tam.p50)} · máx ${fmtBytes(tam.max)}`
    : "Nenhum log baixado ainda.";
}

function switchTab(tabId) {
  const tabs = Array.from(document.querySelectorAll(".nav-link[data-tab]"));
  const panels = Array.from(document.querySelectorAll(".tab-panel"));
  const valid = tabs.some((t) => t.dataset.tab === tabId);
  const id = valid ? tabId : "visao-geral";
  tabs.forEach((btn) => {
    const on = btn.dataset.tab === id;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  panels.forEach((panel) => {
    const on = panel.id === id;
    panel.classList.toggle("active", on);
    if (on) panel.removeAttribute("hidden");
    else panel.setAttribute("hidden", "");
  });
  history.replaceState(null, "", `#${id}`);
  if (id === "modelos" && map) {
    requestAnimationFrame(() => {
      map.invalidateSize();
      paintMap();
    });
  }
}

function initTabs() {
  const tabs = Array.from(document.querySelectorAll(".nav-link[data-tab]"));
  tabs.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
  const hash = (location.hash || "").replace(/^#/, "");
  switchTab(hash || "visao-geral");
  const glossary = document.querySelector(".glossary");
  const toggle = glossary?.querySelector(".glossary-toggle");
  if (glossary && toggle) {
    const sync = () => {
      toggle.textContent = glossary.open ? "ocultar" : "mostrar";
    };
    glossary.addEventListener("toggle", sync);
    sync();
  }
}

async function refresh() {
  const ufsUrl = selectedModelo
    ? `/api/ufs?modelo=${encodeURIComponent(selectedModelo)}`
    : "/api/ufs";
  const [ov, ufs, aux, apu, tam, mod, pres, elections] = await Promise.all([
    j("/api/overview"),
    j(ufsUrl),
    j("/api/aux-status"),
    j("/api/apuracao"),
    j("/api/tamanhos"),
    j("/api/modelos"),
    j("/api/presidente"),
    j("/api/elections").catch((err) => {
      console.warn("elections", err);
      return { elections: [], active_db: null, job: { status: "idle", message: "API de eleições indisponível — reinicie o dashboard" } };
    }),
  ]);
  ufIndex = Object.fromEntries(ufs.ufs.map((r) => [r.uf, r]));
  lastUfRows = ufs.ufs;
  lastPresNational = pres;
  renderKpis(ov);
  renderElections(elections);
  if (selectedModelo) {
    await loadPresidenteForFilter();
  } else {
    renderPresidente(pres);
  }
  renderModelos(mod);
  renderUfTable(lastUfRows);
  renderCharts(lastUfRows, aux, apu, tam);
  paintMap();
  await renderMunicipios();
}

function modeLabel(e) {
  if (e.mode === "regional") return "Por região / seção";
  if (e.mode === "bulk_zip") return "ZIP completo por UF";
  return e.mode;
}

function fmtDetail(detail, fallback) {
  if (detail == null) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "string" ? d : d.msg || JSON.stringify(d))).join("; ");
  }
  return detail.msg || JSON.stringify(detail);
}

function renderElections(payload) {
  const grid = document.getElementById("electionGrid");
  if (!grid) return;
  const job = payload.job || {};
  const jobLine = document.getElementById("downloadJobLine");
  const busy = ["running", "starting", "stopping"].includes(job.status);
  if (jobLine) {
    if (!busy) {
      jobLine.textContent = "Nenhum download em andamento.";
    } else {
      const parts = [
        job.message || job.status,
        job.election_id ? `eleição ${job.election_id}` : null,
      ].filter(Boolean);
      const uniq = [];
      for (const p of parts) {
        if (!uniq.includes(p)) uniq.push(p);
      }
      jobLine.textContent = uniq.join(" · ");
    }
  }
  if (busy) pollJob();

  grid.innerHTML = (payload.elections || [])
    .map((e) => {
      const canStart = !!e.can_start;
      const canContinue = !!e.can_continue;
      const canRemove = !!e.can_remove;
      const canView = !!e.can_view;
      const downloadable = !!e.can_download;
      const missingN = (e.ufs_missing || []).length;
      const isPartial = !!e.partial || !!e.downloading;
      const panelPill = e.active ? `<span class="pill">no painel</span>` : "";
      const mode = `<span class="pill muted-pill">${modeLabel(e)}</span>`;
      const dlPill = e.downloading
        ? `<span class="pill filter-pill">baixando…</span>`
        : isPartial
          ? `<span class="pill filter-pill">parcial</span>`
          : "";
      const size = e.db_exists ? fmtBytes(e.db_bytes) : "sem banco";
      const covParts = [];
      if (e.ufs_expected != null && e.ufs_done != null) {
        covParts.push(`${e.ufs_done}/${e.ufs_expected} UFs`);
      }
      if (e.mode === "regional" && e.secoes) {
        covParts.push(`${fmt.format(e.logs_ok || 0)}/${fmt.format(e.secoes)} logs`);
      } else if (e.logs_ok) {
        covParts.push(`${fmt.format(e.logs_ok)} logs`);
      }
      const cov = covParts.length ? ` · ${covParts.join(" · ")}` : "";
      const viewLabel = !canView
        ? "Sem dados ainda"
        : e.active
          ? isPartial
            ? "No painel (parcial)"
            : "No painel"
          : isPartial
            ? "Ver no painel (parcial)"
            : "Ver no painel";
      let actionBtns = "";
      if (e.downloading) {
        actionBtns = `<button type="button" class="btn-danger btn-stop-download" data-id="${e.id}">Parar download</button>`;
      } else if (canContinue || (e.has_data && isPartial && downloadable)) {
        const contLabel = missingN ? `Continuar (${missingN} UFs)` : "Continuar download";
        const contEnabled = canContinue;
        actionBtns = `
          <button type="button" class="btn-primary btn-continue-download" data-id="${e.id}" ${contEnabled ? "" : "disabled"} title="${contEnabled ? "Retomar download das UFs faltantes" : "Espere o download em andamento terminar"}">${contLabel}</button>
          <button type="button" class="btn-danger btn-remove-election" data-id="${e.id}" ${canRemove ? "" : "disabled"}>Remover</button>`;
      } else if (e.has_data) {
        actionBtns = `<button type="button" class="btn-danger btn-remove-election" data-id="${e.id}" ${canRemove ? "" : "disabled"}>Remover</button>`;
      } else if (downloadable) {
        const startLabel = busy ? "Aguarde o download atual" : "Iniciar download";
        actionBtns = `<button type="button" class="btn-primary btn-start-download" data-id="${e.id}" ${canStart ? "" : "disabled"} title="${canStart ? "Iniciar download" : "Espere o download em andamento terminar"}">${startLabel}</button>`;
      } else {
        actionBtns = `<button type="button" class="btn-primary" disabled title="${e.note || ""}">Indisponível</button>`;
      }
      return `<div class="election-card ${e.active ? "active" : ""} ${isPartial ? "partial" : ""}" data-id="${e.id}">
        <div class="election-top">
          <h4>${e.label}</h4>
          <div class="election-pills">${mode}${dlPill}${panelPill}</div>
        </div>
        <p class="election-note">${e.note || ""}</p>
        <p class="hint">DB: ${e.db_filename} · ${size}${cov}</p>
        <div class="election-actions">
          <button type="button" class="btn-secondary btn-select-election" data-id="${e.id}" ${canView && !e.active ? "" : "disabled"} title="${canView ? (e.active ? "Já está no painel" : "Carregar esta eleição no painel") : "Disponível após o download"}">${viewLabel}</button>
          ${actionBtns}
        </div>
      </div>`;
    })
    .join("");

  grid.querySelectorAll(".btn-select-election").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      btn.disabled = true;
      try {
        const r = await fetch("/api/elections/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ election_id: id }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(fmtDetail(data.detail, r.statusText));
        selectedModelo = null;
        selectedUf = null;
        voteUfIndex = {};
        lastPresNational = null;
        lastUfRows = [];
        updateGeoFilterChrome();
        await refresh();
      } catch (err) {
        alert(`Não foi possível selecionar: ${err.message || err}`);
        await refresh();
      }
    });
  });
  const startDownload = async (btn) => {
    const id = btn.dataset.id;
    btn.disabled = true;
    try {
      const r = await fetch("/api/downloads/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ election_id: id, store_blob: true, switch_db: false }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(fmtDetail(data.detail, r.statusText));
      pollJob();
      await refresh();
    } catch (err) {
      alert(`Não foi possível iniciar: ${err.message || err}`);
      await refresh();
    }
  };
  grid.querySelectorAll(".btn-start-download").forEach((btn) => {
    btn.addEventListener("click", () => startDownload(btn));
  });
  grid.querySelectorAll(".btn-continue-download").forEach((btn) => {
    btn.addEventListener("click", () => startDownload(btn));
  });
  grid.querySelectorAll(".btn-stop-download").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Parar o download em andamento?")) return;
      btn.disabled = true;
      try {
        const r = await fetch("/api/downloads/stop", { method: "POST" });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(fmtDetail(data.detail, r.statusText));
        pollJob();
        await refresh();
      } catch (err) {
        alert(`Não foi possível parar: ${err.message || err}`);
        await refresh();
      }
    });
  });
  grid.querySelectorAll(".btn-remove-election").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const label = btn.closest(".election-card")?.querySelector("h4")?.textContent || id;
      if (!confirm(`Remover os dados baixados de ${label}?\nO banco SQLite desta eleição será apagado.`)) {
        return;
      }
      btn.disabled = true;
      try {
        const r = await fetch("/api/elections/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ election_id: id, remove_zips: false }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(fmtDetail(data.detail, r.statusText));
        selectedModelo = null;
        selectedUf = null;
        voteUfIndex = {};
        lastPresNational = null;
        lastUfRows = [];
        updateGeoFilterChrome();
        await refresh();
      } catch (err) {
        alert(`Não foi possível remover: ${err.message || err}`);
        await refresh();
      }
    });
  });
}

let jobPollTimer = null;
function pollJob() {
  if (jobPollTimer) return;
  jobPollTimer = setInterval(async () => {
    try {
      const job = await j("/api/downloads/status");
      const busy = ["running", "starting", "stopping"].includes(job.status);
      const line = document.getElementById("downloadJobLine");
      if (line) {
        if (!busy) {
          line.textContent = "Nenhum download em andamento.";
        } else {
          const parts = [job.message || job.status, job.election_id ? `eleição ${job.election_id}` : null].filter(Boolean);
          line.textContent = [...new Set(parts)].join(" · ");
        }
      }
      if (!busy) {
        clearInterval(jobPollTimer);
        jobPollTimer = null;
        await refresh();
      }
    } catch (_) {
      /* ignore transient poll errors */
    }
  }, 3000);
}

async function boot() {
  chartDefaults();
  initSortableTables();
  initTabs();
  updateGeoFilterChrome();
  document.getElementById("mapMetric").addEventListener("change", () => {
    paintMap();
    updateBuCoverageHints(
      selectedModelo
        ? { n_ufs: buUfCoverage(), n_secoes: Object.values(voteUfIndex).reduce((s, u) => s + (u.n_secoes || 0), 0) }
        : null
    );
  });
  document.getElementById("btnClearModelo").addEventListener("click", () => {
    clearModeloFilter();
  });
  document.getElementById("btnRefresh")?.addEventListener("click", () => refresh());
  const geo = await loadGeo();
  initMap(geo);
  await refresh();
  // Mapa inicia em aba oculta — redimensiona se já estivermos em Modelos
  if (document.getElementById("modelos")?.classList.contains("active")) {
    requestAnimationFrame(() => map?.invalidateSize());
  }
  const job = await j("/api/downloads/status");
  if (["running", "starting", "stopping"].includes(job.status)) pollJob();
}

boot().catch((err) => {
  document.getElementById("metaLine").textContent = `Erro ao carregar: ${err}`;
});
