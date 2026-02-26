const healthPill = document.getElementById("health-pill");
const statusLine = document.getElementById("status-line");
const outputBox = document.getElementById("output");
const resultView = document.getElementById("result-view");
const copyBtn = document.getElementById("copy-btn");
const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
const generateForm = document.getElementById("generate-form");
const evaluateForm = document.getElementById("evaluate-form");
const questionJsonField = document.getElementById("question-json");

let busy = false;
let lastPayload = {};

function setBusy(value) {
  busy = value;
  const buttons = Array.from(document.querySelectorAll(".action-btn"));
  buttons.forEach((button) => {
    button.disabled = value;
    button.textContent = value ? "Working..." : button.dataset.label;
  });
}

function setStatus(text, mode = "") {
  statusLine.textContent = text;
  statusLine.classList.remove("error", "ok");
  if (mode) {
    statusLine.classList.add(mode);
  }
}

function setOutput(payload) {
  lastPayload = payload || {};
  outputBox.textContent = JSON.stringify(lastPayload, null, 2);
  renderFriendly(lastPayload);
}

function parseOptionalJson(raw, label) {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch (error) {
    throw new Error(`${label} must be valid JSON.`);
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/healthz");
    if (!response.ok) {
      throw new Error("Health endpoint returned non-200.");
    }
    healthPill.textContent = "API Online";
    healthPill.style.borderColor = "rgba(47, 211, 137, 0.55)";
    healthPill.style.color = "#2fd389";
  } catch (error) {
    healthPill.textContent = "API Unreachable";
    healthPill.style.borderColor = "rgba(255, 106, 122, 0.65)";
    healthPill.style.color = "#ff6a7a";
  }
}

function activateTab(tabName) {
  tabButtons.forEach((button) => {
    const active = button.dataset.tab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  tabPanels.forEach((panel) => {
    const active = panel.id.startsWith(tabName);
    panel.classList.toggle("active", active);
  });
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({ detail: "Invalid server response." }));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    throw new Error(detail || "Request failed.");
  }
  return data;
}

function wireTabs() {
  tabButtons.forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
}

function wireCopy() {
  copyBtn.addEventListener("click", async () => {
    const text = JSON.stringify(lastPayload || {}, null, 2);
    if (!text.trim()) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Copied JSON to clipboard.", "ok");
    } catch (error) {
      setStatus("Clipboard copy failed.", "error");
    }
  });
}

function makeBlock(title, contentNode) {
  const block = document.createElement("section");
  block.className = "result-block";
  const heading = document.createElement("h3");
  heading.textContent = title;
  block.appendChild(heading);
  block.appendChild(contentNode);
  return block;
}

function makeList(items) {
  const list = document.createElement("ul");
  list.className = "result-list";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = String(item);
    list.appendChild(li);
  });
  return list;
}

function makeParagraph(text) {
  const p = document.createElement("p");
  p.textContent = String(text || "");
  return p;
}

function renderQuestion(payload) {
  const title = document.createElement("h3");
  title.className = "result-title";
  title.textContent = payload.question || "Generated Question";
  resultView.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "meta-row";
  const track = document.createElement("span");
  track.className = "meta-pill";
  track.textContent = `Track: ${payload.track || "-"}`;
  const type = document.createElement("span");
  type.className = "meta-pill";
  type.textContent = `Type: ${payload.question_type || "-"}`;
  const difficulty = document.createElement("span");
  difficulty.className = "meta-pill";
  difficulty.textContent = `Difficulty: ${payload.difficulty ?? "-"}`;
  meta.appendChild(track);
  meta.appendChild(type);
  meta.appendChild(difficulty);
  resultView.appendChild(meta);

  resultView.appendChild(makeBlock("Expected Points", makeList(payload.expected_points)));
  resultView.appendChild(makeBlock("Follow-ups", makeList(payload.followups)));
  resultView.appendChild(makeBlock("Red Flags", makeList(payload.red_flags)));

  if (payload.coding) {
    resultView.appendChild(makeBlock("Coding Requirements", makeList(payload.coding.requirements)));
    resultView.appendChild(makeBlock("Starter Code", makeCodeBlock(payload.coding.starter_code)));
    resultView.appendChild(makeBlock("Tests", makeCodeBlock(payload.coding.tests)));
  }
}

function makeCodeBlock(text) {
  const pre = document.createElement("pre");
  pre.className = "code-block";
  pre.textContent = String(text || "");
  return pre;
}

function scoreClass(score) {
  if (score >= 85) {
    return "good";
  }
  if (score >= 60) {
    return "mid";
  }
  return "low";
}

function renderEvaluation(payload) {
  const score = Number(payload.score ?? 0);
  const badge = document.createElement("div");
  badge.className = `score-pill ${scoreClass(score)}`;
  badge.textContent = `Score: ${score}/100`;
  resultView.appendChild(badge);

  resultView.appendChild(makeBlock("Ideal Answer", makeParagraph(payload.ideal_answer)));
  resultView.appendChild(makeBlock("Strengths", makeList(payload.strengths)));
  resultView.appendChild(makeBlock("Missing Points", makeList(payload.missing_points)));
  resultView.appendChild(makeBlock("Incorrect Points", makeList(payload.incorrect_points)));
  resultView.appendChild(makeBlock("Improvement Tips", makeList(payload.improvement_tips)));

  if ((payload.clarifying_questions || []).length) {
    resultView.appendChild(makeBlock("Clarifying Questions", makeList(payload.clarifying_questions)));
  }
  if (payload.followup_question) {
    resultView.appendChild(makeBlock("Follow-up Question", makeParagraph(payload.followup_question)));
  }
}

function renderFriendly(payload) {
  resultView.innerHTML = "";

  if (!payload || Object.keys(payload).length === 0) {
    resultView.appendChild(makeParagraph("No result yet. Submit a request to view formatted output."));
    return;
  }

  if ("question" in payload && "expected_points" in payload) {
    renderQuestion(payload);
    return;
  }
  if ("score" in payload && "ideal_answer" in payload) {
    renderEvaluation(payload);
    return;
  }

  resultView.appendChild(makeParagraph("Structured view unavailable for this payload. Check raw JSON."));
}

function wireGenerate() {
  generateForm.querySelectorAll(".action-btn").forEach((button) => {
    button.dataset.label = button.textContent;
  });

  generateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) {
      return;
    }

    const form = new FormData(generateForm);
    const payload = {
      track: form.get("track"),
      question_type: form.get("question_type"),
      difficulty: Number(form.get("difficulty")),
    };
    const style = String(form.get("style") || "").trim();
    if (style) {
      payload.style = style;
    }

    setBusy(true);
    setStatus("Generating question...");
    try {
      const data = await postJson("/generate-question", payload);
      setOutput(data);
      questionJsonField.value = JSON.stringify(data, null, 2);
      setStatus("Question generated and copied into evaluator form.", "ok");
    } catch (error) {
      setStatus(error.message || "Question generation failed.", "error");
    } finally {
      setBusy(false);
    }
  });
}

function wireEvaluate() {
  evaluateForm.querySelectorAll(".action-btn").forEach((button) => {
    button.dataset.label = button.textContent;
  });

  evaluateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) {
      return;
    }

    try {
      const questionJson = parseOptionalJson(questionJsonField.value, "Question JSON");
      if (!questionJson) {
        throw new Error("Question JSON is required.");
      }

      const validatorSummary = parseOptionalJson(
        document.getElementById("validator-summary").value,
        "Validator Summary"
      );

      const payload = {
        question_json: questionJson,
        candidate_answer: String(document.getElementById("candidate-answer").value || "").trim(),
      };
      if (!payload.candidate_answer) {
        throw new Error("Candidate answer is required.");
      }
      if (validatorSummary !== null) {
        payload.validator_summary = validatorSummary;
      }

      setBusy(true);
      setStatus("Evaluating answer...");
      const data = await postJson("/evaluate-answer", payload);
      setOutput(data);
      setStatus("Evaluation complete.", "ok");
    } catch (error) {
      setStatus(error.message || "Evaluation failed.", "error");
    } finally {
      setBusy(false);
    }
  });
}

function init() {
  wireTabs();
  wireCopy();
  wireGenerate();
  wireEvaluate();
  checkHealth();
  setOutput({});
  setStatus("Idle");
}

init();
