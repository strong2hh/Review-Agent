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
  questionEl.textContent = data.question || "";
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
    <strong>得分：</strong>${data.score_0_100} / 100（${data.star_0_5} 星）<br/>
    <strong>纠错建议：</strong>${data.correction}<br/>
    <strong>关键要点：</strong>${data.key_points || "-"}
  `;

  if (data.completed) {
    titleEl.textContent = "本次复习已完成";
    questionEl.textContent = "辛苦了，你已经完成所有待复习知识点。";
    answerEl.style.display = "none";
    submitBtn.style.display = "none";
    progressEl.textContent = `已完成 ${totalQuestions} / ${totalQuestions}`;
    return;
  }

  currentIndex += 1;
  currentQuestionId = data.next_question_id;
  questionEl.textContent = data.next_question || "";
  answerEl.value = "";
  submitBtn.disabled = false;
  updateProgress();
}

submitBtn.addEventListener("click", submitAnswer);
startSession();
