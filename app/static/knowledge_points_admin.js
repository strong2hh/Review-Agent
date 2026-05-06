const createForm = document.getElementById("create-form");
const importForm = document.getElementById("import-form");
const listEl = document.getElementById("list");
const createFeedbackEl = document.getElementById("create-feedback");
const importFeedbackEl = document.getElementById("import-feedback");
const createBtn = document.getElementById("create-btn");
const importBtn = document.getElementById("import-btn");
const cancelEditBtn = document.getElementById("cancel-edit-btn");
const titleInput = document.getElementById("title");
const contentInput = document.getElementById("content");
const tagsInput = document.getElementById("tags");

let editingKnowledgePointId = null;

function splitTags(raw) {
  return raw
    .split(/[,\n，]/)
    .map((x) => x.trim())
    .filter((x) => x.length > 0);
}

function showFeedback(el, ok, text) {
  el.className = `feedback ${ok ? "ok" : "error"}`;
  el.textContent = text;
}

function clearFeedback(el) {
  el.className = "feedback";
  el.textContent = "";
}

function formatDate(isoString) {
  try {
    return new Date(isoString).toLocaleString("zh-CN", { hour12: false });
  } catch (_err) {
    return isoString;
  }
}

function toErrorMessage(err) {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return "请求失败，请稍后重试";
}

function resetEditMode() {
  editingKnowledgePointId = null;
  createBtn.textContent = "保存知识点";
  cancelEditBtn.style.display = "none";
  createForm.reset();
}

function enterEditMode(item) {
  editingKnowledgePointId = item.id;
  createBtn.textContent = "保存修改";
  cancelEditBtn.style.display = "inline-block";
  titleInput.value = item.title || "";
  contentInput.value = item.content || "";
  tagsInput.value = Array.isArray(item.tags) ? item.tags.join(", ") : "";
  showFeedback(createFeedbackEl, true, `正在编辑：${item.title}`);
  titleInput.focus();
}

function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    listEl.innerHTML = "";
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "暂无知识点，先录入一条吧。";
    listEl.appendChild(empty);
    return;
  }

  listEl.innerHTML = "";
  items.forEach((item) => {
    const article = document.createElement("article");
    article.className = "item";

    const title = document.createElement("h3");
    title.textContent = item.title;
    article.appendChild(title);

    const content = document.createElement("p");
    content.textContent = item.content;
    article.appendChild(content);

    const meta = document.createElement("div");
    meta.className = "meta";
    const tags = Array.isArray(item.tags) && item.tags.length ? item.tags.join(", ") : "-";
    const mastery = Number.isFinite(item.mastery) ? item.mastery.toFixed(1) : "-";
    meta.textContent = `标签: ${tags} | 掌握度: ${mastery} | 下次复习: ${formatDate(item.next_review_at)}`;
    article.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "item-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "action-btn action-edit";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => enterEditMode(item));
    actions.appendChild(editBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "action-btn action-delete";
    deleteBtn.textContent = "删除";
    deleteBtn.addEventListener("click", () => deleteKnowledgePoint(item.id, item.title));
    actions.appendChild(deleteBtn);

    article.appendChild(actions);
    listEl.appendChild(article);
  });
}

async function parseJsonOrThrow(resp) {
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求失败，请稍后重试";
    throw new Error(detail);
  }
  return data;
}

async function deleteKnowledgePoint(knowledgePointId, title) {
  const ok = window.confirm(`确认删除知识点「${title}」吗？`);
  if (!ok) {
    return;
  }

  try {
    const resp = await fetch(`/api/knowledge-points/${knowledgePointId}`, { method: "DELETE" });
    await parseJsonOrThrow(resp);
    if (editingKnowledgePointId === knowledgePointId) {
      resetEditMode();
      clearFeedback(createFeedbackEl);
    }
    showFeedback(importFeedbackEl, true, "删除成功");
    await loadKnowledgePoints();
  } catch (err) {
    showFeedback(importFeedbackEl, false, `删除失败：${toErrorMessage(err)}`);
  }
}

async function loadKnowledgePoints() {
  try {
    const resp = await fetch("/api/knowledge-points?limit=50");
    const data = await parseJsonOrThrow(resp);
    renderList(data);
  } catch (err) {
    renderList([]);
    showFeedback(importFeedbackEl, false, `加载列表失败：${toErrorMessage(err)}`);
  }
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  createBtn.disabled = true;

  const title = titleInput.value.trim();
  const content = contentInput.value.trim();
  const tags = splitTags(tagsInput.value || "");

  if (!title || !content) {
    showFeedback(createFeedbackEl, false, "标题和内容不能为空");
    createBtn.disabled = false;
    return;
  }

  try {
    const isEdit = editingKnowledgePointId !== null;
    const url = isEdit ? `/api/knowledge-points/${editingKnowledgePointId}` : "/api/knowledge-points";
    const method = isEdit ? "PUT" : "POST";

    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content, tags }),
    });
    await parseJsonOrThrow(resp);
    resetEditMode();
    showFeedback(createFeedbackEl, true, isEdit ? "修改成功" : "保存成功");
    await loadKnowledgePoints();
  } catch (err) {
    showFeedback(createFeedbackEl, false, `保存失败：${toErrorMessage(err)}`);
  } finally {
    createBtn.disabled = false;
  }
});

cancelEditBtn.addEventListener("click", () => {
  resetEditMode();
  clearFeedback(createFeedbackEl);
});

importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  importBtn.disabled = true;

  const format = document.getElementById("import-format").value;
  const payload = document.getElementById("import-payload").value;

  if (!payload.trim()) {
    showFeedback(importFeedbackEl, false, "导入内容不能为空");
    importBtn.disabled = false;
    return;
  }

  try {
    const resp = await fetch("/api/knowledge-points/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format, payload }),
    });
    const data = await parseJsonOrThrow(resp);
    showFeedback(importFeedbackEl, true, `导入完成，新增 ${data.created || 0} 条`);
    await loadKnowledgePoints();
  } catch (err) {
    showFeedback(importFeedbackEl, false, `导入失败：${toErrorMessage(err)}`);
  } finally {
    importBtn.disabled = false;
  }
});

loadKnowledgePoints();
