const modelForm = document.getElementById("model-form");
const questionProviderEl = document.getElementById("question-provider");
const questionModelEl = document.getElementById("question-model");
const gradingProviderEl = document.getElementById("grading-provider");
const gradingModelEl = document.getElementById("grading-model");
const saveModelBtn = document.getElementById("save-model-btn");
const modelFeedbackEl = document.getElementById("model-feedback");

let providerSpecs = [];

function showFeedback(el, ok, text) {
  el.className = `feedback ${ok ? "ok" : "error"}`;
  el.textContent = text;
}

function clearFeedback(el) {
  el.className = "feedback";
  el.textContent = "";
}

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

function renderProviderOptions() {
  const providerList = Array.isArray(providerSpecs) ? providerSpecs : [];
  const renderTo = [questionProviderEl, gradingProviderEl];

  renderTo.forEach((selectEl) => {
    selectEl.innerHTML = "";
    providerList.forEach((spec) => {
      const opt = document.createElement("option");
      opt.value = spec.provider;
      opt.textContent = `${spec.label} (${spec.provider})`;
      selectEl.appendChild(opt);
    });
  });
}

async function loadModelSettings() {
  try {
    const [providersResp, channelsResp] = await Promise.all([
      fetch("/api/models/providers"),
      fetch("/api/settings/models"),
    ]);
    providerSpecs = await parseJsonOrThrow(providersResp);
    const channels = await parseJsonOrThrow(channelsResp);
    renderProviderOptions();

    questionProviderEl.value = channels.question_provider || "";
    questionModelEl.value = channels.question_model || "";
    gradingProviderEl.value = channels.grading_provider || "";
    gradingModelEl.value = channels.grading_model || "";

    clearFeedback(modelFeedbackEl);
  } catch (err) {
    showFeedback(modelFeedbackEl, false, `加载模型配置失败：${toErrorMessage(err)}`);
  }
}

modelForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  saveModelBtn.disabled = true;

  const payload = {
    question_provider: questionProviderEl.value.trim(),
    question_model: questionModelEl.value.trim(),
    grading_provider: gradingProviderEl.value.trim(),
    grading_model: gradingModelEl.value.trim(),
  };

  if (!payload.question_provider || !payload.question_model || !payload.grading_provider || !payload.grading_model) {
    showFeedback(modelFeedbackEl, false, "出题与评分的 Provider/Model 都不能为空。");
    saveModelBtn.disabled = false;
    return;
  }

  try {
    const resp = await fetch("/api/settings/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await parseJsonOrThrow(resp);

    questionProviderEl.value = data.question_provider;
    questionModelEl.value = data.question_model;
    gradingProviderEl.value = data.grading_provider;
    gradingModelEl.value = data.grading_model;
    showFeedback(modelFeedbackEl, true, "模型配置已保存。");
  } catch (err) {
    showFeedback(modelFeedbackEl, false, `保存模型配置失败：${toErrorMessage(err)}`);
  } finally {
    saveModelBtn.disabled = false;
  }
});

loadModelSettings();
