let sessionId = null;
let totalQuestions = 0;
let currentIndex = 1;
let currentQuestionId = null;

const progressEl = document.getElementById("progress");
const titleEl = document.getElementById("title");
const questionEl = document.getElementById("question");
const answerEl = document.getElementById("answer");
const resultEl = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");

function toErrorMessage(err) {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return "请求失败，请稍后重试";
}

async function parseJsonOrThrow(resp) {
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求失败，请稍后重试";
    throw new Error(detail);
  }
  return data;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderMissingParts(parts) {
  if (!Array.isArray(parts) || parts.length === 0) {
    return "<p class=\"result-empty\">未发现明显遗漏要点。</p>";
  }
  return `<ul class="missing-list">${parts.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
}

function updateProgress() {
  if (!totalQuestions) {
    progressEl.textContent = "当前没有待复习知识点，稍后再来。";
    return;
  }
  progressEl.textContent = `第 ${currentIndex} / ${totalQuestions} 题`;
}

async function startSession() {
  let data;
  try {
    const resp = await fetch("/api/review/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    data = await parseJsonOrThrow(resp);
  } catch (err) {
    progressEl.textContent = `加载失败：${toErrorMessage(err)}`;
    answerEl.style.display = "none";
    submitBtn.style.display = "none";
    return;
  }

  sessionId = data.session_id;
  totalQuestions = data.total_questions;
  currentQuestionId = data.question_id;
  if (!currentQuestionId) {
    updateProgress();
    titleEl.textContent = "";
    questionEl.textContent = "";
    answerEl.style.display = "none";
    submitBtn.style.display = "none";
    return;
  }

  titleEl.textContent = data.title || "知识点";
  questionEl.textContent = "";
  updateProgress();
}

async function submitAnswer() {
  const answer = answerEl.value.trim();
  if (!answer) {
    alert("请先输入答案");
    return;
  }

  submitBtn.disabled = true;
  let data;
  try {
    const resp = await fetch(`/api/review/session/${sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    data = await parseJsonOrThrow(resp);
  } catch (err) {
    resultEl.style.display = "block";
    resultEl.innerHTML = `<strong>提交失败：</strong>${toErrorMessage(err)}`;
    submitBtn.disabled = false;
    return;
  }

  resultEl.style.display = "block";
  resultEl.innerHTML = `
    <div><strong>得分：</strong>${data.score_0_100} / 100（${data.star_0_5} 星）</div>
    <div class="result-group">
      <strong>纠错建议（未回答部分）：</strong>
      ${renderMissingParts(data.missing_parts)}
    </div>
    <div class="result-group">
      <strong>正确答案：</strong>
      <div class="answer-scroll">${escapeHtml(data.correct_answer || "-")}</div>
    </div>
  `;

  if (data.completed) {
    titleEl.textContent = "本次复习已完成";
    questionEl.textContent = "";
    answerEl.style.display = "none";
    submitBtn.style.display = "none";
    progressEl.textContent = `已完成 ${totalQuestions} / ${totalQuestions}`;
    return;
  }

  currentIndex += 1;
  currentQuestionId = data.next_question_id;
  titleEl.textContent = data.next_title || "知识点";
  questionEl.textContent = "";
  answerEl.value = "";
  submitBtn.disabled = false;
  updateProgress();
}

submitBtn.addEventListener("click", submitAnswer);
startSession();
