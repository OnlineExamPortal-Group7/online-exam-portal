
document.addEventListener("DOMContentLoaded", function () {
  const examLayout = document.getElementById("exam-layout");

  if (!examLayout) {
    return;
  }

  let secondsRemaining = Number(examLayout.dataset.remainingSeconds) || 0;
  const questionCount = Number(examLayout.dataset.questionCount) || 0;

  let submissionStarted = false;

  const countdownElement = document.getElementById("countdown");
  const timerContainer = document.getElementById("timer-container");
  const timeoutMessage = document.getElementById("timeout-message");

  const answerForm = document.getElementById("answer-form");
  const submitForm = document.getElementById("submit-form");
  const submitButton = document.getElementById("submit-button");

  const autosaveStatus = document.getElementById("autosave-status");
  const AUTOSAVE_RETRY_DELAYS_MS = [1000, 2000, 4000];

  let autosaveSequence = answerForm
    ? Number(answerForm.dataset.autosaveSeq) || 0
    : 0;

  function syncSequenceFields() {
    document.querySelectorAll(".autosave-seq").forEach(function (field) {
      field.value = autosaveSequence;
    });
  }

  function showAutosaveStatus(text, state) {
    if (!autosaveStatus) {
      return;
    }

    autosaveStatus.textContent = text;
    autosaveStatus.classList.remove("saved", "error");

    if (state) {
      autosaveStatus.classList.add(state);
    }
  }

  function updateSelectedChoice(choiceId) {
    if (!answerForm) {
      return;
    }

    document.getElementById("choice-id").value = choiceId;

    const submitChoice = document.getElementById("submit-choice-id");

    if (submitChoice) {
      submitChoice.value = choiceId;
    }

    autosaveAnswer(choiceId);
  }

  function autosaveAnswer(choiceId) {
    if (submissionStarted || !answerForm) {
      return;
    }

    autosaveSequence += 1;
    syncSequenceFields();

    sendAutosave(choiceId, autosaveSequence, 0, false);
  }

  function sendAutosave(choiceId, sequence, attempt, resynced) {
    if (submissionStarted || sequence !== autosaveSequence) {
      return;
    }

    const body = new FormData();

    body.append(
      "question_id",
      answerForm.querySelector("[name=question_id]").value
    );

    body.append("choice_id", choiceId);
    body.append("seq", sequence);

    const csrfToken = answerForm.querySelector(
      "[name=csrfmiddlewaretoken]"
    ).value;

    showAutosaveStatus("Saving...", null);

    fetch(answerForm.dataset.autosaveUrl, {
      method: "POST",
      body: body,
      headers: { "X-CSRFToken": csrfToken },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (sequence !== autosaveSequence) {
          return;
        }

        if (response.ok) {
          return response.json().then(function (data) {
            handleAutosaveResult(data, choiceId, sequence, resynced);
          });
        } else if (response.status === 409) {
          submitAutomatically();
        } else if (response.status >= 500) {
          retryAutosave(choiceId, sequence, attempt, resynced);
        } else {
          showAutosaveStatus(
            "Answer not saved. Use Save & Next to try again.",
            "error"
          );
        }
      })
      .catch(function () {
        retryAutosave(choiceId, sequence, attempt, resynced);
      });
  }

  function handleAutosaveResult(data, choiceId, sequence, resynced) {
    if (sequence !== autosaveSequence) {
      return;
    }

    if (data.status !== "stale") {
      showAutosaveStatus("Answer saved.", "saved");
      markCurrentQuestionAnswered();
      return;
    }

    if (!resynced && typeof data.seq === "number") {
      autosaveSequence = Math.max(autosaveSequence, data.seq) + 1;
      syncSequenceFields();
      sendAutosave(choiceId, autosaveSequence, 0, true);
      return;
    }

    showAutosaveStatus(
      "Answer not saved. Use Save & Next to try again.",
      "error"
    );
  }

  function markCurrentQuestionAnswered() {
    const button = document.querySelector(
      '.question-nav button[aria-current="step"]'
    );

    if (!button || button.classList.contains("answered")) {
      return;
    }

    button.classList.add("answered");
    button.setAttribute(
      "aria-label",
      button.getAttribute("aria-label") + " (answered)"
    );

    const counter = document.getElementById("answered-count");

    if (counter) {
      counter.textContent = Number(counter.textContent) + 1;
    }
  }

  function retryAutosave(choiceId, sequence, attempt, resynced) {
    if (sequence !== autosaveSequence) {
      return;
    }

    if (attempt >= AUTOSAVE_RETRY_DELAYS_MS.length) {
      showAutosaveStatus(
        "Answer not saved. Check your connection and use Save & Next.",
        "error"
      );
      return;
    }

    showAutosaveStatus("Connection problem, retrying...", "error");

    setTimeout(function () {
      sendAutosave(choiceId, sequence, attempt + 1, resynced);
    }, AUTOSAVE_RETRY_DELAYS_MS[attempt]);
  }

  function disableExamControls() {
    submissionStarted = true;

    if (answerForm) {
      answerForm.querySelectorAll("button, input").forEach(function (element) {
        element.disabled = true;
      });
    }

    if (submitButton) {
      submitButton.disabled = true;
    }
  }

  function submitAutomatically() {
    if (submissionStarted) {
      return;
    }

    disableExamControls();

    countdownElement.textContent = "00:00";
    timerContainer.classList.add("expired");
    timeoutMessage.classList.add("visible");

    submitForm.submit();
  }

  function updateCountdown() {
    if (submissionStarted) {
      return;
    }

    if (secondsRemaining <= 0) {
      submitAutomatically();
      return;
    }

    const minutes = Math.floor(secondsRemaining / 60);
    const seconds = secondsRemaining % 60;

    countdownElement.textContent =
      String(minutes).padStart(2, "0") +
      ":" +
      String(seconds).padStart(2, "0");

    secondsRemaining -= 1;
  }

  function navigateToQuestion(index) {
    if (submissionStarted || !answerForm) {
      return;
    }

    const target = Math.max(0, Math.min(index, questionCount - 1));

    document.getElementById("next-question").value = target;
    answerForm.requestSubmit();
  }

  // Question navigation buttons.
  document.querySelectorAll("[data-navigate-question]").forEach(function (button) {
    button.addEventListener("click", function () {
      navigateToQuestion(Number(button.dataset.navigateQuestion));
    });
  });

  // Answer selection.
  document.querySelectorAll('input[name="visible_choice"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      updateSelectedChoice(this.value);
    });
  });

  // Manual submission confirmation.
  if (submitForm) {
    submitForm.addEventListener("submit", function (event) {
      if (submissionStarted) {
        return;
      }

      const confirmed = window.confirm(
        "Are you sure you want to submit the exam?"
      );

      if (!confirmed) {
        event.preventDefault();
        return;
      }

      disableExamControls();
    });
  }

  // Start countdown immediately.
  updateCountdown();

  const countdownInterval = setInterval(function () {
    if (submissionStarted) {
      clearInterval(countdownInterval);
      return;
    }

    updateCountdown();
  }, 1000);
});
