const state = {
  mode: "text",
  user: null,
  currentSubmissionId: null,
  pollingTimer: null,
  scene3d: null,
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
  clearBtn: document.getElementById("clearBtn"),
  resultStatus: document.getElementById("resultStatus"),
  emptyState: document.getElementById("emptyState"),
  loadingState: document.getElementById("loadingState"),
  loadingText: document.getElementById("loadingText"),
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
  ocrReviewCard: document.getElementById("ocrReviewCard"),
  ocrReviewText: document.getElementById("ocrReviewText"),
  ocrReviewBtn: document.getElementById("ocrReviewBtn"),
  limitCount: document.getElementById("limitCount"),
  limitRing: document.getElementById("limitRing"),
  referralBadge: document.getElementById("referralBadge"),
  userName: document.getElementById("userName"),
  referralCode: document.getElementById("referralCode"),
  referralInput: document.getElementById("referralInput"),
  referralBtn: document.getElementById("referralBtn"),
  historyList: document.getElementById("historyList"),
  refreshHistoryBtn: document.getElementById("refreshHistoryBtn"),
  processStrip: document.getElementById("processStrip"),
};

const telegramApp = window.Telegram?.WebApp;
if (telegramApp) {
  telegramApp.ready();
  telegramApp.expand();
}
const telegramInitData = telegramApp?.initData || "";

document.querySelectorAll(".mode-btn").forEach((button) => {
  button.addEventListener("click", () => switchMode(button.dataset.mode));
});

elements.essayImage.addEventListener("change", handleImagePreview);
elements.essayForm.addEventListener("submit", handleSubmit);
elements.clearBtn.addEventListener("click", resetWorkspace);
elements.referralBtn.addEventListener("click", handleReferralClaim);
elements.ocrReviewBtn.addEventListener("click", handleOcrReviewSubmit);
elements.refreshHistoryBtn.addEventListener("click", () => {
  if (state.user?.telegram_id) {
    fetchHistory(state.user.telegram_id);
  }
});

initParticles();
initCardTilt();
initScene3d();
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
        <figure style="animation-delay:${index * 0.08}s">
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
    const essayText = elements.essayText.value.trim();
    if (!essayText) {
      updateStatus("Essay matnini kiriting.", "warning");
      return;
    }
    formData.append("text", essayText);
  } else {
    const files = Array.from(elements.essayImage.files || []);
    if (!files.length) {
      updateStatus("Kamida bitta rasm tanlang.", "warning");
      return;
    }
    files.forEach((file) => {
      formData.append("images", file);
    });
  }

  elements.submitBtn.disabled = true;
  updateStatus("Tekshiruv navbatga olindi", "neutral");
  updateProcessStrip("queued", state.mode === "image" ? "image" : "text");
  showLoading("Tekshiruv navbatga olindi...");
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
    hideLoading();
    updateStatus(error.message, "warning");
  } finally {
    elements.submitBtn.disabled = false;
  }
}

function resetWorkspace() {
  stopPolling();
  state.currentSubmissionId = null;
  elements.essayText.value = "";
  elements.essayImage.value = "";
  elements.imagePreview.innerHTML = "";
  elements.imagePreview.classList.add("hidden");
  elements.emptyState.classList.remove("hidden");
  elements.resultContent.classList.add("hidden");
  hideLoading();
  elements.scoreValue.textContent = "-";
  elements.cefrValue.textContent = "-";
  elements.providerValue.textContent = "demo";
  elements.rubricList.innerHTML = "";
  elements.grammarErrors.innerHTML = "";
  elements.spellingErrors.innerHTML = "";
  elements.suggestionList.innerHTML = "";
  elements.improvedVersion.textContent = "";
  elements.improvedCard.classList.add("hidden");
  elements.ocrText.textContent = "";
  elements.ocrCard.classList.add("hidden");
  elements.ocrReviewText.value = "";
  elements.ocrReviewCard.classList.add("hidden");
  updateProcessStrip(null);
  updateStatus("Kutilmoqda", "neutral");
}

function startPolling(submissionId) {
  stopPolling();
  state.pollingTimer = window.setInterval(async () => {
    try {
      const submission = await api(submissionPath(submissionId));
      renderSubmission(submission);
      if (["completed", "failed", "reviewing"].includes(submission.status)) {
        stopPolling();
        await refreshUserAndHistory();
      }
    } catch (error) {
      stopPolling();
      hideLoading();
      updateStatus(error.message || "Natijani olishda xatolik.", "warning");
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

async function handleOcrReviewSubmit() {
  if (!state.currentSubmissionId || !state.user?.telegram_id) {
    updateStatus("Avval rasm yuboring.", "warning");
    return;
  }
  const reviewedText = elements.ocrReviewText.value.trim();
  if (!reviewedText) {
    updateStatus("OCR matni bo'sh bo'lmasligi kerak.", "warning");
    return;
  }

  elements.ocrReviewBtn.disabled = true;
  updateStatus("AI tahlil boshlanmoqda", "warning");
  updateProcessStrip("processing", "image");
  showLoading("AI tahlil qilmoqda...");
  try {
    const submission = await api(
      `/api/submissions/${state.currentSubmissionId}/analyze?telegram_id=${encodeURIComponent(state.user.telegram_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: reviewedText }),
      },
    );
    renderSubmission(submission);
    startPolling(state.currentSubmissionId);
    await refreshUserAndHistory();
  } catch (error) {
    hideLoading();
    updateStatus(error.message, "warning");
  } finally {
    elements.ocrReviewBtn.disabled = false;
  }
}

function renderUser(user) {
  const limit = user.available_limit ?? 0;
  elements.limitCount.textContent = limit;
  animateLimitRing(limit);
  elements.referralBadge.textContent = `Kod: ${user.referral_code}`;
  elements.userName.textContent = user.full_name || `Telegram #${user.telegram_id}`;
  elements.referralCode.textContent = user.referral_code;
}

function animateLimitRing(limit) {
  if (!elements.limitRing) return;
  const max = 20;
  const pct = Math.min(limit / max, 1);
  const circumference = 264;
  elements.limitRing.style.strokeDashoffset = String(circumference * (1 - pct));
}

function renderSubmission(submission) {
  elements.emptyState.classList.add("hidden");
  elements.resultContent.classList.remove("hidden");
  updateStatus(mapStatus(submission.status), mapStatusTone(submission.status));
  updateProcessStrip(submission.status, submission.source_type);

  if (submission.status !== "completed") {
    if (["queued", "ocr_processing", "processing"].includes(submission.status)) {
      showLoading(mapStatus(submission.status) + "...");
    } else if (submission.status === "reviewing") {
      hideLoading();
    } else if (submission.status === "failed") {
      hideLoading();
    }

    elements.scoreValue.textContent = "-";
    elements.cefrValue.textContent = "-";
    elements.providerValue.textContent = "...";
    elements.rubricList.innerHTML = "";
    elements.grammarErrors.innerHTML = "";
    elements.spellingErrors.innerHTML = "";
    elements.suggestionList.innerHTML = "";
    elements.ocrCard.classList.toggle("hidden", !submission.ocr_text);
    elements.ocrText.textContent = submission.ocr_text || "";
    elements.improvedCard.classList.add("hidden");
    elements.ocrReviewCard.classList.toggle("hidden", submission.status !== "reviewing");
    if (submission.status === "reviewing") {
      const reviewText = submission.cleaned_text || submission.ocr_text || "";
      if (document.activeElement !== elements.ocrReviewText) {
        elements.ocrReviewText.value = reviewText;
      }
      elements.providerValue.textContent = "OCR";
      elements.improvedVersion.textContent = "";
    }
    if (submission.status === "failed") {
      elements.improvedVersion.textContent = submission.error_message || "Xatolik yuz berdi.";
    } else if (submission.status !== "reviewing") {
      elements.improvedVersion.textContent = "Essay tekshirilmoqda. Natija shu yerda chiqadi.";
    }
    return;
  }

  hideLoading();
  const analysis = submission.analysis || {};
  elements.ocrReviewCard.classList.add("hidden");
  animateScore(elements.scoreValue, formatScoreValue(submission, analysis));
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

function showLoading(text) {
  elements.loadingState.classList.remove("hidden");
  elements.loadingText.textContent = text;
}

function hideLoading() {
  elements.loadingState.classList.add("hidden");
}

function updateProcessStrip(status, sourceType = "text") {
  if (!elements.processStrip) return;
  const isImage = sourceType === "image";
  const allSteps = ["submit", "ocr", "review", "analyze", "done"];

  const flows = {
    text: {
      queued: ["submit"],
      processing: ["submit", "analyze"],
      completed: ["submit", "analyze", "done"],
      failed: [],
    },
    image: {
      queued: ["submit"],
      ocr_processing: ["submit", "ocr"],
      reviewing: ["submit", "ocr", "review"],
      processing: ["submit", "ocr", "review", "analyze"],
      completed: ["submit", "ocr", "review", "analyze", "done"],
      failed: [],
    },
  };

  const flow = isImage ? flows.image : flows.text;
  const activeSteps = status ? flow[status] || [] : [];
  const activeIndex = activeSteps.length - 1;

  elements.processStrip.querySelectorAll(".mini-step").forEach((el) => {
    const step = el.dataset.step;
    if (!isImage && (step === "ocr" || step === "review")) {
      el.style.opacity = "0.35";
    } else {
      el.style.opacity = "1";
    }
    const idx = allSteps.indexOf(step);
    el.classList.remove("active", "done");
    if (idx < activeIndex) {
      el.classList.add("done");
    } else if (idx === activeIndex) {
      el.classList.add("active");
    }
  });
}

function animateScore(element, finalText) {
  element.textContent = finalText;
  element.classList.remove("score-pop");
  void element.offsetWidth;
  element.classList.add("score-pop");
}

function renderRubric(rubric) {
  const items = Object.entries(rubric);
  elements.rubricList.innerHTML = items
    .map(
      ([key, value], index) => {
        const label = value.label || formatKey(key);
        const score = value.band ?? value.score ?? "-";
        const maxScore = value.band !== undefined ? "/9" : value.max_score ? `/${value.max_score}` : "";
        const comment = value.comment || "";
        return `
        <div class="stack-item" style="animation-delay:${index * 0.05}s">
          <strong>${escapeHtml(label)}: ${escapeHtml(score)}${escapeHtml(maxScore)}</strong>
          <small>${escapeHtml(comment)}</small>
        </div>
      `;
      },
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
      (item, index) => `
        <div class="stack-item" style="animation-delay:${index * 0.05}s">
          <strong>${escapeHtml(item.wrong)} -> ${escapeHtml(item.corrected)}</strong>
          <small>${escapeHtml(item.explanation || "")}</small>
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
      (item, index) => `
        <div class="stack-item" style="animation-delay:${index * 0.05}s">
          <strong>Imlo: ${escapeHtml(item.wrong)} -> ${escapeHtml(item.corrected)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderSuggestions(suggestions) {
  elements.suggestionList.innerHTML = suggestions
    .map(
      (item, index) =>
        `<div class="stack-item" style="animation-delay:${index * 0.05}s"><strong>${escapeHtml(item)}</strong></div>`,
    )
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
      (item, index) => `
        <button class="history-item" type="button" data-id="${item.id}" style="animation-delay:${index * 0.06}s">
          <strong>#${item.id} | ${item.source_type.toUpperCase()}</strong>
          <p>Status: ${escapeHtml(mapStatus(item.status))}</p>
          <p>Ball: ${escapeHtml(item.score ?? "-")} | Daraja: ${escapeHtml(item.cefr ?? "-")}</p>
        </button>
      `,
    )
    .join("");

  document.querySelectorAll(".history-item[data-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.currentSubmissionId = Number(button.dataset.id);
      const submission = await api(submissionPath(button.dataset.id));
      renderSubmission(submission);
    });
  });
}

function submissionPath(submissionId) {
  if (!state.user?.telegram_id) {
    return `/api/submissions/${submissionId}`;
  }
  return `/api/submissions/${submissionId}?telegram_id=${encodeURIComponent(state.user.telegram_id)}`;
}

function updateStatus(text, tone) {
  elements.resultStatus.textContent = text;
  elements.resultStatus.className = `pill ${tone}`;
}

function mapStatus(status) {
  const mapping = {
    queued: "Navbatda",
    ocr_processing: "OCR o'qilmoqda",
    reviewing: "Matnni ko'rib chiqing",
    processing: "Tekshirilmoqda",
    completed: "Tayyor",
    failed: "Xatolik",
  };
  return mapping[status] || status;
}

function mapStatusTone(status) {
  const mapping = {
    queued: "neutral",
    ocr_processing: "warning",
    reviewing: "warning",
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
    topic_coverage: "Mavzuni yoritish",
    thesis_position: "Tezis va pozitsiya",
    arguments_examples: "Dalil va misollar",
    logical_coherence: "Mantiqiy izchillik",
    structure: "Kompozitsiya",
    style_register: "Uslub va registr",
    spelling: "Imlo",
    punctuation: "Punktuatsiya",
    conclusion: "Xulosa",
    length_requirements: "Hajm va talabga moslik",
    coherence_cohesion: "Coherence and Cohesion",
    lexical_resource: "Lexical Resource",
    grammar_range_accuracy: "Grammatical Range and Accuracy",
  };
  if (labels[key]) {
    return labels[key];
  }
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatScoreValue(submission, analysis) {
  if (analysis.score_display) {
    return analysis.score_display;
  }
  if (analysis.scoring_system === "ielts" && typeof analysis.score === "number") {
    const band = (analysis.score / 10).toFixed(1).replace(/\.0$/, "");
    return `${band}/9 IELTS`;
  }
  if (analysis.scoring_system === "uzbek_75") {
    return `${submission.score ?? analysis.score ?? "-"}/75`;
  }
  return submission.score ?? analysis.score ?? "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (telegramInitData) {
    headers.set("X-Telegram-Init-Data", telegramInitData);
  }
  const response = await fetch(path, { ...options, headers });
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

/* ── Visual effects ── */

function initParticles() {
  const container = document.getElementById("particles");
  if (!container) return;
  const count = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 30;
  for (let i = 0; i < count; i++) {
    const p = document.createElement("div");
    p.className = "particle";
    p.style.left = `${Math.random() * 100}%`;
    p.style.animationDuration = `${8 + Math.random() * 12}s`;
    p.style.animationDelay = `${Math.random() * 10}s`;
    p.style.opacity = String(0.2 + Math.random() * 0.5);
    container.appendChild(p);
  }
}

function initCardTilt() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll("[data-tilt]").forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      card.style.transform = `perspective(800px) rotateY(${x * 6}deg) rotateX(${-y * 6}deg) translateZ(4px)`;
    });
    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
    });
  });
}

function initScene3d() {
  if (typeof THREE === "undefined") return;
  const canvas = document.getElementById("canvas3d");
  const container = document.getElementById("scene3d");
  if (!canvas || !container) return;

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.z = 5;

  const ambient = new THREE.AmbientLight(0xffffff, 0.5);
  scene.add(ambient);
  const point = new THREE.PointLight(0x4f8cff, 1.2, 20);
  point.position.set(2, 3, 4);
  scene.add(point);
  const point2 = new THREE.PointLight(0x22d3a8, 0.8, 20);
  point2.position.set(-3, -1, 3);
  scene.add(point2);

  const group = new THREE.Group();

  const paperGeo = new THREE.BoxGeometry(1.6, 2.2, 0.06);
  const paperMat = new THREE.MeshPhongMaterial({
    color: 0x1a2540,
    emissive: 0x0a1020,
    shininess: 60,
    transparent: true,
    opacity: 0.85,
  });
  const paper = new THREE.Mesh(paperGeo, paperMat);
  group.add(paper);

  const edgeGeo = new THREE.EdgesGeometry(paperGeo);
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x4f8cff, transparent: true, opacity: 0.6 });
  const edges = new THREE.LineSegments(edgeGeo, edgeMat);
  group.add(edges);

  for (let i = 0; i < 4; i++) {
    const lineGeo = new THREE.BoxGeometry(1.0, 0.04, 0.02);
    const lineMat = new THREE.MeshPhongMaterial({
      color: i % 2 === 0 ? 0x4f8cff : 0x22d3a8,
      emissive: i % 2 === 0 ? 0x1a3060 : 0x0a4030,
    });
    const line = new THREE.Mesh(lineGeo, lineMat);
    line.position.set(0, 0.7 - i * 0.35, 0.04);
    if (i === 2) line.scale.x = 0.7;
    if (i === 3) line.scale.x = 0.5;
    group.add(line);
  }

  const ringGeo = new THREE.TorusGeometry(1.1, 0.015, 8, 64);
  const ringMat = new THREE.MeshPhongMaterial({
    color: 0x22d3a8,
    emissive: 0x0a3020,
    transparent: true,
    opacity: 0.5,
  });
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.rotation.x = Math.PI / 2;
  group.add(ring);

  scene.add(group);
  state.scene3d = { renderer, scene, camera, group, container };

  function animate() {
    requestAnimationFrame(animate);
    group.rotation.y += 0.006;
    group.rotation.x = Math.sin(Date.now() * 0.001) * 0.08;
    ring.rotation.z += 0.01;
    renderer.render(scene, camera);
  }
  animate();

  const resizeObserver = new ResizeObserver(() => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
  resizeObserver.observe(container);
}
