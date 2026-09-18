if (!getToken("candidate")) {
  window.location.href = "/hr-quiz/candidate-login";
}

const introView = document.getElementById("introView");
const quizView = document.getElementById("quizView");
const resultView = document.getElementById("resultView");
const introError = document.getElementById("introError");
const startBtn = document.getElementById("startBtn");
const nextBtn = document.getElementById("nextBtn");
const progressText = document.getElementById("progressText");
const questionText = document.getElementById("questionText");
const optionsList = document.getElementById("optionsList");
const timerValue = document.getElementById("timerValue");
const timerCircle = document.getElementById("timerCircle");
const timerRing = document.getElementById("timerRing");

document.getElementById("logoutBtn").addEventListener("click", () => {
  clearToken("candidate");
  window.location.href = "/hr-quiz/";
});

const RADIUS = 26;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
timerCircle.style.strokeDasharray = `${CIRCUMFERENCE}`;

let sessionId = null;
let questions = [];
let secondsPerQuestion = 30;
let currentIndex = 0;
let selectedOption = null;
let timerInterval = null;
let questionStartedAt = null;
const collectedAnswers = [];

startBtn.addEventListener("click", async () => {
  hideError(introError);
  startBtn.disabled = true;
  startBtn.textContent = "Loading...";
  try {
    const data = await apiRequest("/api/candidate/quiz/start", { method: "POST", role: "candidate" });
    sessionId = data.session_id;
    questions = data.questions;
    secondsPerQuestion = data.seconds_per_question;
    introView.style.display = "none";
    quizView.style.display = "block";
    showQuestion(0);
  } catch (err) {
    showError(introError, err.message);
    startBtn.disabled = false;
    startBtn.textContent = "Start assessment";
  }
});

function showQuestion(index) {
  currentIndex = index;
  selectedOption = null;
  const q = questions[index];
  progressText.textContent = `Question ${index + 1} of ${questions.length}`;
  questionText.textContent = q.question;

  optionsList.innerHTML = "";
  q.options.forEach((opt, i) => {
    const row = document.createElement("div");
    row.className = "option-row";
    row.dataset.index = i;
    row.innerHTML = `<div class="option-letter">${String.fromCharCode(65 + i)}</div><div>${escapeHtml(opt)}</div>`;
    row.addEventListener("click", () => selectOption(i));
    optionsList.appendChild(row);
  });

  nextBtn.textContent = index === questions.length - 1 ? "Submit assessment" : "Next question";
  questionStartedAt = Date.now();
  startTimer();
}

function selectOption(i) {
  selectedOption = i;
  document.querySelectorAll(".option-row").forEach((el) => {
    el.classList.toggle("selected", Number(el.dataset.index) === i);
  });
}

function startTimer() {
  clearInterval(timerInterval);
  let remaining = secondsPerQuestion;
  updateTimerDisplay(remaining);

  timerInterval = setInterval(() => {
    remaining -= 1;
    updateTimerDisplay(remaining);
    if (remaining <= 0) {
      clearInterval(timerInterval);
      advance(true);
    }
  }, 1000);
}

function updateTimerDisplay(remaining) {
  timerValue.textContent = Math.max(remaining, 0);
  const fraction = Math.max(remaining, 0) / secondsPerQuestion;
  const offset = CIRCUMFERENCE * (1 - fraction);
  timerCircle.style.strokeDashoffset = offset;

  timerRing.classList.remove("warn", "danger");
  if (remaining <= 5) timerRing.classList.add("danger");
  else if (remaining <= 15) timerRing.classList.add("warn");
}

nextBtn.addEventListener("click", () => advance(false));

function advance(timedOut) {
  clearInterval(timerInterval);
  const timeTaken = Math.min((Date.now() - questionStartedAt) / 1000, secondsPerQuestion);
  const q = questions[currentIndex];
  collectedAnswers.push({
    question_id: q.question_id,
    selected_option: timedOut ? null : selectedOption,
    time_taken_seconds: Number(timeTaken.toFixed(1)),
  });

  if (currentIndex + 1 < questions.length) {
    showQuestion(currentIndex + 1);
  } else {
    finishQuiz();
  }
}

async function finishQuiz() {
  quizView.style.display = "none";
  nextBtn.disabled = true;
  try {
    const data = await apiRequest("/api/candidate/quiz/submit", {
      method: "POST",
      role: "candidate",
      body: { session_id: sessionId, answers: collectedAnswers },
    });
    document.getElementById("scoreValue").textContent = data.score;
    document.getElementById("totalValue").textContent = data.total_questions;
    resultView.style.display = "block";
    renderReview(data.answers_detail || []);
  } catch (err) {
    quizView.style.display = "block";
    alert(err.message);
  }
}

function renderReview(detail) {
  const reviewView = document.getElementById("reviewView");
  const reviewList = document.getElementById("reviewList");
  if (detail.length === 0) return;

  reviewList.innerHTML = "";
  detail.forEach((item, qi) => {
    const card = document.createElement("div");
    card.className = "card question-review";

    const optionsHtml = item.options.map((opt, i) => {
      let cls = "";
      if (i === item.correct_index) cls = "option-correct";
      else if (i === item.selected_option) cls = "option-wrong";
      const tag = i === item.correct_index ? '<span class="option-tag tag-correct">Correct answer</span>'
        : (i === item.selected_option ? '<span class="option-tag tag-wrong">Your answer</span>' : "");
      return `<div class="option-row-static ${cls}">
        <div class="option-letter">${String.fromCharCode(65 + i)}</div>
        <div>${escapeHtml(opt)}</div>
        ${tag}
      </div>`;
    }).join("");

    card.innerHTML = `
      <div class="question-review-header">
        <span class="question-review-num">Q${qi + 1}</span>
        <span class="badge ${item.is_correct ? "badge-completed" : "badge-pending"}">${item.is_correct ? "Correct" : (item.selected_option === null ? "Unattempted" : "Incorrect")}</span>
      </div>
      <div class="question-text" style="font-size:15px; margin-bottom:14px;">${escapeHtml(item.question)}</div>
      ${optionsHtml}
    `;
    reviewList.appendChild(card);
  });

  reviewView.style.display = "block";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
