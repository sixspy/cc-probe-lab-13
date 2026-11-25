
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? "{}" : JSON.stringify(body),
  });
  const t = await r.text();
  let data;
  try { data = JSON.parse(t); } catch { data = { 原文: t }; }
  if (!r.ok) throw new Error((data && (data.错误 || data.detail)) || t || String(r.status));
  return data;
}
function 行(html) {
  const tr = document.createElement("tr");
  tr.innerHTML = html;
  return tr;
}
function 徽章(文, 类) {
  const tone = 类 || 命运色(文);
  return `<span class="徽章 ${tone || ""}">${安全文本(文)}</span>`;
}
function 空态(文) { return `<p class="说明">${安全文本(文)}</p>`; }
function 安全文本(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
function 命运色(f) {
  if (["已入栏", "在栏", "已汇总", "对齐"].includes(f)) return "ok";
  if (["已坏点", "撕裂"].includes(f)) return "warn";
  if (["影子结栏", "强制结"].includes(f)) return "影";
  return "";
}
async function 渲染强制结闸(el) {
  if (!el) return;
  const s = await getJSON("/api/强制结栏/闸态");
  const 过阈 = !!s["过阈"];
  const 封印 = s["封印"];
  let 状态;
  if (封印) {
    状态 = `<span class="徽章 警">已封印 · ${安全文本(封印["闸形态"])}</span>
            <span class="说明">指纹 ${安全文本((封印["指纹"] || "").slice(0, 12))}… · 水位 ${封印["水位"]}</span>`;
  } else if (过阈) {
    状态 = `<span class="徽章 好">水位过阈可正式结</span><span class="说明">水位 ${s["在栏"]} ≥ 阈 ${s["水位阈"]}</span>`;
  } else {
    状态 = `<span class="徽章 警">未过阈只可强制结（影子归档）</span><span class="说明">水位 ${s["在栏"]} &lt; 阈 ${s["水位阈"]}</span>`;
  }
  const 禁 = 封印 ? "disabled" : "";
  el.innerHTML = `
    <div class="闸卡">
      <div class="闸头"><b class="铜字">强制结闸</b> ${状态}</div>
      <div class="说明 上距8">正式结把汇总写入站点汇总账；未过阈强制结只写只读归档凭证，正式汇总不增行。无闸/野闸回刷一律 400。</div>
      <div class="工具 上距8">
        <button class="按钮 青" id="正式结按钮" ${过阈 && !封印 ? "" : "disabled"}>正式结（过阈写闸）</button>
        <button class="按钮 影钮" id="强制结按钮" ${!过阈 && !封印 ? "" : "disabled"}>强制结（未过阈影子归档）</button>
      </div>
      <pre class="回执 上距8" id="强制结回执">未操作</pre>
    </div>`;
  const 回执 = el.querySelector("#强制结回执");
  el.querySelector("#正式结按钮").onclick = async () => {
    try {
      回执.textContent = JSON.stringify(await postJSON("/api/结栏/跑", {"闸形态": "正式结"}), null, 2);
    } catch (e) { 回执.textContent = String(e); }
    await 渲染强制结闸(el);
  };
  el.querySelector("#强制结按钮").onclick = async () => {
    try {
      回执.textContent = JSON.stringify(await postJSON("/api/结栏/跑", {"闸形态": "强制结"}), null, 2);
    } catch (e) { 回执.textContent = String(e); }
    await 渲染强制结闸(el);
  };
}
async function 渲染凭证表(el) {
  if (!el) return;
  const rows = await getJSON("/api/强制结栏/凭证");
  if (!rows.length) { el.innerHTML = 空态("尚无影子凭证（未过阈强制结后在此只读留痕）。"); return; }
  el.innerHTML = rows.map((v) => `
    <tr><td>${安全文本(v["凭证编号"])}</td><td>${安全文本(v["栏号"])}</td>
    <td>${v["报文数"]}</td><td>${v["水位"]}/${v["阈值"]}</td>
    <td><span class="徽章 影">影子结栏</span></td>
    <td class="字小">${安全文本((v["指纹"] || "").slice(0, 16))}…</td></tr>`).join("");
}
function 渲染水位(el, o) {
  if (!el) return;
  el.innerHTML = "";
  for (const [标, 键] of [["观测报文","观测报文"],["在栏","在栏"],["站点汇总","站点汇总"],["坏点","坏点"]]) {
    const d = document.createElement("div");
    d.className = "水卡";
    d.innerHTML = `<div class="数">${o[键] ?? 0}</div><div class="标">${标}</div>`;
    el.appendChild(d);
  }
}
function 渲染门槛(el, 规) {
  if (!el) return;
  const r = 规 || {};
  el.innerHTML = `
    <div class="门槛卡"><div class="k">当前栏</div><div class="v">${安全文本(r["当前栏号"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 上限</div><div class="v">${安全文本(r["PM25上限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">PM25 下限</div><div class="v">${安全文本(r["PM25下限"] || "—")}</div></div>
    <div class="门槛卡"><div class="k">标定偏移</div><div class="v">${安全文本(r["标定偏移上限"] || "—")}</div></div>
  `;
}
function 渲染批次表(el, rows, cols) {
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = `<tr><td colspan="${cols.length}">${空态("尚无批次。")}</td></tr>`;
    return;
  }
  el.innerHTML = "";
  for (const r of rows) {
    const cells = cols.map((c) => `<td>${安全文本(r[c])}</td>`).join("");
    el.appendChild(行(cells));
  }
}
function 装载摘要文(r) {
  if (!r) return "";
  return `入流 ${r["入流"]||0} · 入栏 ${r["入栏"]||0} · 坏点 ${r["坏点"]||0} · 驳回 ${r["驳回"]||0}`;
}
function 结栏摘要文(r) {
  if (!r) return "";
  return `栏 ${r["栏号"]||"?"} · 汇总 ${r["汇总数"]||0} · 缓冲消耗 ${r["缓冲消耗"]||0}`;
}
function 贯验摘要文(r) {
  if (!r) return "";
  return `${r["是否对齐"]?"对齐":"撕裂"} · 在栏 ${r["在栏"]} · 汇总报文 ${r["汇总报文"]} · 坏点 ${r["坏点"]}`;
}
function 填命运字典(el, dict) {
  if (!el || !dict) return;
  el.innerHTML = Object.entries(dict).map(([k, v]) =>
    `<div class="只读框 上距8"><b class="铜字">${安全文本(k)}</b> · ${安全文本(v)}</div>`
  ).join("");
}
window.探栏 = {
  getJSON, postJSON, 行, 徽章, 空态, 安全文本, 命运色,
  渲染水位, 渲染门槛, 渲染批次表, 渲染强制结闸, 渲染凭证表,
  装载摘要文, 结栏摘要文, 贯验摘要文, 填命运字典,
};
