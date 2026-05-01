const state = {
  mode: "text",
  user: null,
  currentSubmissionId: null,
  pollingTimer: null,
};

const elements = {
  identityBox: document.getElementById("identityBox"),
  telegramIdInput: document.getElementById("telegramIdInput"),
  essayForm: document.getElementById("essayForm"),
  essayText: document.getElementById("essayText"),
  essayImage: document.getElementById("essayImage"),
  imagePreview: document.getElementById("imagePreview"),
  textFieldGroup: document.getElementById("textFieldGroup"),
  imageFieldGroup: document.getElementById("imageFieldGroup"),
  submitBtn: document.getElementById("submitBtn"),
  resultStatus: document.getElementById("resultStatus"),
  emptyState: document.getElementById("emptyState"),
  resultContent: document.getElementById("resultContent"),
  scoreValue: document.getElementById("scoreValue"),
  cefrValue: document.getElementById("cefrValue"),
  providerValue: document.getElementById("providerValue"),
  rubricList: document.getElementById("rubricList"),
  grammarErrors: document.getElementById("grammarErrors"),
  spellingErrors: document.getElementById("spellingErrors"),
  suggestionList: document.getElementById("suggestionList"),
  improvedVersion: document.getElementById("improvedVersion"),
  improvedCard: document.getElementById("improvedCard"),
  ocrCard: document.getElementById("ocrCard"),
  ocrText: document.getElementById("ocrText"),
  limitCount: document.getElementById("limitCount"),
  referralBadge: document.getElementById("referralBadge"),
  userName: document.getElementById("userName"),
  referralCode: document.getElementById("referralCode"),
  referralInput: document.getElementById("referralInput"),
  referralBtn: document.getElementById("referralBtn"),
  historyList: document.getElementById("historyList"),
  refreshHistoryBtn: document.getElementById("refreshHistoryBtn"),
};

const telegramApp = window.Telegram?.WebApp;
if (telegramApp) {
  telegramApp.ready();
  telegramApp.expand();
}

document.querySelectorAll(".mode-btn").forEach((button) => {
  button.addEventListener("click", () => switchMode(button.dataset.mode));
});

elements.essayImage.addEventListener("change", handleImagePreview);
elements.essayForm.addEventListener("submit", handleSubmit);
elements.referralBtn.addEventListener("click", handleReferralClaim);
elements.refreshHistoryBtn.addEventListener("click", () => {
  if (state.user?.telegram_id) {
    fetchHistory(state.user.telegram_id);
  }
});

bootstrap();

async function bootstrap() {
  const identity = resolveIdentity();
  if (!identity.telegramId) {
    elements.identityBox.classList.remove("hidden");
    elements.telegramIdInput.addEventListener("change", () => bootstrapUserFromInput());
    return;
  }
  await bootstrapUser(identity);
}

function resolveIdentity() {
  const tgUser = telegramApp?.initDataUnsafe?.user;
  if (tgUser?.id) {
    return {
      telegramId: String(tgUser.id),
      fullName: [tgUser.first_name, tgUser.last_name].filter(Boolean).join(" "),
      username: tgUser.username || "",
    };
  }
  return {
    telegramId: elements.telegramIdInput.value.trim(),
    fullName: "",
    username: "",
  };
}

async function bootstrapUserFromInput() {
  const telegramId = elements.telegramIdInput.value.trim();
  if (!telegramId) {
    return;
  }
  await bootstrapUser({ telegramId, fullName: "Demo user", username: "" });
}

async function bootstrapUser(identity) {
  const payload = {
    telegram_id: identity.telegramId,
    full_name: identity.fullName || "",
    username: identity.username || "",
  };
  const user = await api("/api/users/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.user = user;
  elements.identityBox.classList.add("hidden");
  renderUser(user);
  await fetchHistory(user.telegram_id);
}

function switchMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  elements.textFieldGroup.classList.toggle("hidden", mode !== "text");
  elements.imageFieldGroup.classList.toggle("hidden", mode !== "image");
}

function handleImagePreview(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    elements.imagePreview.classList.add("hidden");
    elements.imagePreview.innerHTML = "";
    return;
  }
  elements.imagePreview.classList.remove("hidden");
  elements.imagePreview.innerHTML = files
    .map((file, index) => {
      const imageUrl = URL.createObjectURL(file);
      return `
        <figure>
          <img src="${imageUrl}" alt="${index + 1}-rasm preview" />
          <figcaption>${index + 1}-rasm</figcaption>
        </figure>
      `;
    })
    .join("");
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!state.user?.telegram_id) {
    await bootstrapUserFromInput();
    if (!state.user?.telegram_id) {
      updateStatus("Avval Telegram ID kiriting.", "warning");
      return;
    }
  }

  const formData = new FormData();
  formData.append("telegram_id", state.user.telegram_id);
  formData.append("full_name", state.user.full_name || "");
  formData.append("username", state.user.username || "");

  if (state.mode === "text") {
    formData.append("text", elements.essayText.value.trim());
  } else {
    Array.from(elements.essayImage.files || []).forEach((file) => {
      formData.append("images", file);
    });
  }

  elements.submitBtn.disabled = true;
  updateStatus("Tekshiruv navbatga olindi", "neutral");
  try {
    const submission = await api("/api/submissions", {
      method: "POST",
      body: formData,
    });
    state.currentSubmissionId = submission.id;
    renderSubmission(submission);
    startPolling(submission.id);
    await refreshUserAndHistory();
  } catch (error) {
    updateStatus(error.message, "warning");
  } finally {
    elements.submitBtn.disabled = false;
  }
}

function startPolling(submissionId) {
  stopPolling();
  state.pollingTimer = window.setInterval(async () => {
    const submission = await api(`/api/submissions/${submissionId}`);
    renderSubmission(submission);
    if (["completed", "failed"].includes(submission.status)) {
      stopPolling();
      await refreshUserAndHistory();
    }
  }, 1800);
}

function stopPolling() {
  if (state.pollingTimer) {
    window.clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

async function fetchHistory(telegramId) {
  const history = await api(`/api/submissions?telegram_id=${encodeURIComponent(telegramId)}`);
  renderHistory(history);
}

async function refreshUserAndHistory() {
  if (!state.user?.telegram_id) {
    return;
  }
  const user = await api(`/api/users/${state.user.telegram_id}`);
  state.user = user;
  renderUser(user);
  await fetchHistory(user.telegram_id);
}

async function handleReferralClaim() {
  const code = elements.referralInput.value.trim().toUpperCase();
  if (!state.user?.telegram_id || !code) {
    updateStatus("Referral kodni kiriting.", "warning");
    return;
  }
  try {
    const user = await api("/api/referrals/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        telegram_id: state.user.telegram_id,
        referral_code: code,
      }),
    });
    state.user = user;
    renderUser(user);
    elements.referralInput.value = "";
    updateStatus("Referral muvaffaqiyatli qo'llandi.", "success");
  } catch (error) {
    updateStatus(error.message, "warning");
  }
}

function renderUser(user) {
  elements.limitCount.textContent = user.available_limit;
  elements.referralBadge.textContent = `Kod: ${user.referral_code}`;
  elements.userName.textContent = user.full_name || `Telegram #${user.telegram_id}`;
  elements.referralCode.textContent = user.referral_code;
}

function renderSubmission(submission) {
  elements.emptyState.classList.add("hidden");
  elements.resultContent.classList.remove("hidden");
  updateStatus(mapStatus(submission.status), mapStatusTone(submission.status));

  if (submission.status !== "completed") {
    elements.scoreValue.textContent = "-";
    elements.cefrValue.textContent = "-";
    elements.providerValue.textContent = "...";
    elements.rubricList.innerHTML = "";
    elements.grammarErrors.innerHTML = "";
    elements.spellingErrors.innerHTML = "";
    elements.suggestionList.innerHTML = "";
    elements.ocrCard.classList.add("hidden");
    elements.improvedCard.classList.add("hidden");
    if (submission.status === "failed") {
      elements.improvedVersion.textContent = submission.error_message || "Xatolik yuz berdi.";
    } else {
      elements.improvedVersion.textContent = "Essay tekshirilmoqda. Natija shu yerda chiqadi.";
    }
    return;
  }

  const analysis = submission.analysis || {};
  elements.scoreValue.textContent = submission.score ?? analysis.score ?? "-";
  elements.cefrValue.textContent = submission.cefr ?? analysis.cefr ?? "-";
  elements.providerValue.textContent = analysis.provider || "demo";
  const improvedVersion = (analysis.improved_version || "").trim();
  elements.improvedVersion.textContent = improvedVersion;
  elements.improvedCard.classList.toggle("hidden", !improvedVersion);

  renderRubric(analysis.rubric || {});
  renderGrammarErrors(analysis.grammar_errors || []);
  renderSpellingErrors(analysis.spelling_errors || []);
  renderSuggestions(analysis.suggestions || []);

  if (submission.ocr_text) {
    elements.ocrCard.classList.remove("hidden");
    elements.ocrText.textContent = submission.ocr_text;
  } else {
    elements.ocrCard.classList.add("hidden");
  }
}

function renderRubric(rubric) {
  const items = Object.entries(rubric);
  elements.rubricList.innerHTML = items
    .map(
      ([key, value]) => `
        <div class="stack-item">
          <strong>${formatKey(key)}: ${value.score}</strong>
          <small>${value.comment}</small>
        </div>
      `,
    )
    .join("");
}

function renderGrammarErrors(errors) {
  if (!errors.length) {
    elements.grammarErrors.innerHTML =
      '<div class="stack-item"><strong>Jiddiy grammatika xatosi topilmadi</strong></div>';
    return;
  }
  elements.grammarErrors.innerHTML = errors
    .map(
      (item) => `
        <div class="stack-item">
          <strong>${item.wrong} -> ${item.corrected}</strong>
          <small>${item.explanation}</small>
        </div>
      `,
    )
    .join("");
}

function renderSpellingErrors(errors) {
  if (!errors.length) {
    elements.spellingErrors.innerHTML = "";
    return;
  }
  elements.spellingErrors.innerHTML = errors
    .map(
      (item) => `
        <div class="stack-item">
          <strong>Imlo: ${item.wrong} -> ${item.corrected}</strong>
        </div>
      `,
    )
    .join("");
}

function renderSuggestions(suggestions) {
  elements.suggestionList.innerHTML = suggestions
    .map((item) => `<div class="stack-item"><strong>${item}</strong></div>`)
    .join("");
}

function renderHistory(history) {
  if (!history.length) {
    elements.historyList.innerHTML =
      '<div class="history-item"><strong>Hali history yo\'q</strong><p>Birinchi essay yuboring.</p></div>';
    return;
  }

  elements.historyList.innerHTML = history
    .map(
      (item) => `
        <button class="history-item" type="button" data-id="${item.id}">
          <strong>#${item.id} | ${item.source_type.toUpperCase()}</strong>
          <p>Status: ${mapStatus(item.status)}</p>
          <p>Ball: ${item.score ?? "-"} | Daraja: ${item.cefr ?? "-"}</p>
        </button>
      `,
    )
    .join("");

  document.querySelectorAll(".history-item[data-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const submission = await api(`/api/submissions/${button.dataset.id}`);
      renderSubmission(submission);
    });
  });
}

function updateStatus(text, tone) {
  elements.resultStatus.textContent = text;
  elements.resultStatus.className = `pill ${tone}`;
}

function mapStatus(status) {
  const mapping = {
    queued: "Navbatda",
    processing: "Tekshirilmoqda",
    completed: "Tayyor",
    failed: "Xatolik",
  };
  return mapping[status] || status;
}

function mapStatusTone(status) {
  const mapping = {
    queued: "neutral",
    processing: "warning",
    completed: "success",
    failed: "warning",
  };
  return mapping[status] || "neutral";
}

function formatKey(key) {
  const labels = {
    grammar: "Grammatika",
    vocabulary: "Lug'at",
    coherence: "Izchillik",
    task_response: "Mavzuga javob",
  };
  if (labels[key]) {
    return labels[key];
  }
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = "So'rov bajarilmadi.";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}
