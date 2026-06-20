/* English Class — browser speech synthesis and quizzes */
(function () {
  "use strict";

  var DEBUG = true;
  function log() {
    if (DEBUG && window.console && console.log) {
      console.log.apply(console, ["[EnglishClass]"].concat(Array.prototype.slice.call(arguments)));
    }
  }
  function logError() {
    if (window.console && console.error) {
      console.error.apply(console, ["[EnglishClass]"].concat(Array.prototype.slice.call(arguments)));
    }
  }

  var indexData = window.EC_INDEX || {};
  var levels = indexData.levels || [];
  var levelCache = {};

  var state = {
    view: "home",
    levelId: "",
    categoryId: "",
    lessonId: "",
    mode: "read",
    currentLesson: null,
    quizAnswers: {},
    quizSubmitted: false,
  };

  var els = {};

  function $(id) { return document.getElementById(id); }

  function showStatus(msg, isError) {
    var banner = $("ecStatusBanner");
    if (!banner) return;
    if (!msg) {
      banner.style.display = "none";
      banner.textContent = "";
      return;
    }
    banner.textContent = msg;
    banner.style.display = "";
    banner.style.borderColor = isError ? "var(--red)" : "#ccc";
    banner.style.background = isError ? "#fff5f5" : "#f8f8f8";
    banner.style.color = isError ? "#8a0000" : "var(--muted)";
    log(isError ? "status-error" : "status", msg);
  }

  function init() {
    log("init start", {
      readyState: document.readyState,
      levelsCount: levels.length,
      hasIndex: !!window.EC_INDEX,
      stats: indexData.stats || null,
    });

    try {
      els.home = $("ecHome");
      els.level = $("ecLevel");
      els.lesson = $("ecLesson");
      els.levelTitle = $("ecLevelTitle");
      els.levelDesc = $("ecLevelDesc");
      els.categoryList = $("ecCategoryList");
      els.lessonTitle = $("ecLessonTitle");
      els.dialogue = $("ecDialogue");
      els.quiz = $("ecQuiz");
      els.quizScore = $("ecQuizScore");
      els.progressBar = $("ecProgressBar");
      els.progressText = $("ecProgressText");
      els.backHome = $("ecBackHome");
      els.backLevel = $("ecBackLevel");
      els.statsLessons = $("ecStatsLessons");
      els.statsLines = $("ecStatsLines");
      els.errorBox = $("ecErrorBox");

      var required = {
        ecHome: els.home,
        ecLevel: els.level,
        ecLesson: els.lesson,
        ecLevelGrid: $("ecLevelGrid"),
        ecCategoryList: els.categoryList,
      };
      Object.keys(required).forEach(function (key) {
        if (!required[key]) {
          logError("missing DOM element:", key);
        }
      });

      if (!levels.length) {
        showStatus("Course index did not load. Please refresh the page.", true);
        logError("EC_INDEX.levels is empty", window.EC_INDEX);
      }

      if (indexData.stats) {
        if (els.statsLessons) els.statsLessons.textContent = String(indexData.stats.lessons || 0);
        if (els.statsLines) els.statsLines.textContent = String(indexData.stats.lines || 0);
      }

      renderHome();
      bindEvents();
      updateProgressDisplay();
      log("init complete");
    } catch (err) {
      logError("init failed", err);
      showStatus("English Class failed to start: " + (err.message || err), true);
    }
  }

  function bindEvents() {
    document.querySelectorAll(".ec-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setMode(btn.getAttribute("data-mode"));
      });
    });
    if (els.backHome) els.backHome.addEventListener("click", showHome);
    if (els.backLevel) els.backLevel.addEventListener("click", function () {
      if (state.levelId) showLevel(state.levelId);
    });
    log("bindEvents complete");
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".ec-tab").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });
    document.querySelectorAll(".ec-mode-panel").forEach(function (p) {
      p.style.display = p.getAttribute("data-mode") === mode ? "block" : "none";
    });
    if (els.dialogue) els.dialogue.style.display = (mode === "quiz") ? "none" : "block";
    if (mode === "quiz" && state.currentLesson) renderQuiz(state.currentLesson);
  }

  function showView(name) {
    state.view = name;
    log("showView", name);

    var views = [
      { el: els.home, key: "home" },
      { el: els.level, key: "level" },
      { el: els.lesson, key: "lesson" },
    ];

    views.forEach(function (v) {
      if (!v.el) return;
      if (name === v.key) {
        v.el.classList.remove("ec-view-hidden");
        v.el.style.display = "block";
      } else {
        v.el.classList.add("ec-view-hidden");
        v.el.style.display = "none";
      }
    });
  }

  function renderHome() {
    log("renderHome");
    showView("home");
    showStatus("");
    var grid = $("ecLevelGrid");
    if (!grid) {
      logError("renderHome: ecLevelGrid missing");
      showStatus("Level grid not found in page.", true);
      return;
    }
    grid.innerHTML = "";
    if (!levels.length) {
      grid.innerHTML = "<p class=\"subtle\">No levels available.</p>";
      return;
    }
    levels.forEach(function (lv) {
      var card = document.createElement("button");
      card.type = "button";
      card.className = "ec-level-card card" + (state.levelId === lv.id ? " current" : "");
      card.setAttribute("data-level-id", lv.id);
      card.innerHTML =
        "<div class=\"ec-level-badge\">" + escapeHtml(lv.id.toUpperCase()) + "</div>" +
        "<h3>" + escapeHtml(lv.name) + "</h3>" +
        "<p class=\"subtle\">" + escapeHtml(lv.description || "") + "</p>" +
        "<p class=\"muted\">" + (lv.categories ? lv.categories.length : 0) + " categories</p>";
      card.addEventListener("click", function () {
        log("level card click", lv.id);
        showLevel(lv.id);
      });
      grid.appendChild(card);
    });
    log("renderHome done, cards=", levels.length);
  }

  function showLevel(levelId) {
    log("showLevel", levelId);
    state.levelId = levelId;
    state.categoryId = "";
    state.lessonId = "";
    showView("level");
    showStatus("Loading " + levelId.toUpperCase() + " lessons…");

    var meta = levels.find(function (l) { return l.id === levelId; });
    if (els.levelTitle) els.levelTitle.textContent = meta ? meta.name : levelId.toUpperCase();
    if (els.levelDesc) els.levelDesc.textContent = meta ? (meta.description || "") : "";

    if (!els.categoryList) {
      logError("showLevel: ecCategoryList missing");
      showStatus("Category list container not found.", true);
      return;
    }

    if (levelCache[levelId]) {
      log("showLevel cache hit", levelId);
      renderLevelCategories(levelCache[levelId]);
      return;
    }

    els.categoryList.innerHTML = "<p class=\"subtle\">Loading lessons…</p>";
    var url = "/api/english-class/" + encodeURIComponent(levelId);
    log("fetch start", url);

    fetch(url)
      .then(function (r) {
        log("fetch response", url, r.status, r.ok);
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            throw new Error((body && body.error) || ("HTTP " + r.status));
          });
        }
        return r.json();
      })
      .then(function (data) {
        log("fetch json", url, {
          ok: data.ok,
          levelId: data.level && data.level.level,
          categories: data.level && data.level.categories && data.level.categories.length,
        });
        if (!data.ok || !data.level) {
          throw new Error((data && data.error) || "Invalid API response");
        }
        levelCache[levelId] = data.level;
        renderLevelCategories(data.level);
      })
      .catch(function (err) {
        logError("showLevel failed", levelId, err);
        els.categoryList.innerHTML =
          "<p class=\"ec-error-banner\">Could not load this level. " + escapeHtml(err.message || String(err)) + "</p>";
        showStatus("Failed to load " + levelId.toUpperCase() + ": " + (err.message || err), true);
      });
  }

  function renderLevelCategories(levelData) {
    log("renderLevelCategories", {
      level: levelData && levelData.level,
      categories: levelData && levelData.categories && levelData.categories.length,
    });

    if (!els.categoryList) {
      logError("renderLevelCategories: ecCategoryList missing");
      return;
    }

    var categories = (levelData && levelData.categories) || [];
    if (!categories.length) {
      els.categoryList.innerHTML = "<p class=\"subtle\">No categories found for this level.</p>";
      showStatus("This level has no categories.", true);
      return;
    }

    els.categoryList.innerHTML = "";
    var lessonCount = 0;

    categories.forEach(function (cat) {
      var section = document.createElement("div");
      section.className = "ec-category card";
      var h = document.createElement("h3");
      h.textContent = cat.name || cat.id || "Category";
      section.appendChild(h);

      var lessons = cat.lessons || [];
      lessonCount += lessons.length;

      if (!lessons.length) {
        var empty = document.createElement("p");
        empty.className = "subtle";
        empty.textContent = "No lessons in this category.";
        section.appendChild(empty);
      } else {
        var list = document.createElement("div");
        list.className = "ec-lesson-links";
        lessons.forEach(function (lesson) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "ec-lesson-link";
          var done = isLessonComplete(lesson.id);
          btn.innerHTML = escapeHtml(lesson.title) + (done ? " ✓" : "");
          btn.addEventListener("click", function () {
            log("lesson click", lesson.id, lesson.title);
            openLesson(levelData, cat.id, lesson);
          });
          list.appendChild(btn);
        });
        section.appendChild(list);
      }

      els.categoryList.appendChild(section);
    });

    showStatus(levelData.name + " — " + lessonCount + " lessons ready.");
    log("renderLevelCategories done", lessonCount, "lessons");
  }

  function openLesson(levelData, categoryId, lesson) {
    log("openLesson", lesson && lesson.id, lesson && lesson.title);
    if (!lesson || !lesson.dialogue) {
      logError("openLesson: invalid lesson", lesson);
      showStatus("Lesson data is missing or invalid.", true);
      return;
    }

    state.categoryId = categoryId;
    state.lessonId = lesson.id;
    state.currentLesson = lesson;
    state.quizAnswers = {};
    state.quizSubmitted = false;
    showView("lesson");
    showStatus("");

    if (els.lessonTitle) els.lessonTitle.textContent = lesson.title || "Lesson";
    renderDialogue(lesson);
    renderQuiz(lesson);
    setMode("read");
    stopSpeech();
    log("openLesson done", lesson.dialogue.length, "lines");
  }

  function renderDialogue(lesson) {
    if (!els.dialogue) {
      logError("renderDialogue: ecDialogue missing");
      return;
    }
    els.dialogue.innerHTML = "";

    var fullRow = document.createElement("div");
    fullRow.className = "ec-full-speak-row";
    var fullBtn = document.createElement("button");
    fullBtn.type = "button";
    fullBtn.className = "btn primary ec-full-speak";
    fullBtn.textContent = "🔊 Play Full Conversation";
    fullBtn.addEventListener("click", function () {
      speakSequence((lesson.dialogue || []).map(function (l) { return l.text; }));
    });
    fullRow.appendChild(fullBtn);
    els.dialogue.appendChild(fullRow);

    (lesson.dialogue || []).forEach(function (line, idx) {
      var row = document.createElement("div");
      row.className = "ec-line";
      row.setAttribute("data-line-idx", String(idx));

      var inner = document.createElement("div");
      inner.className = "ec-line-inner";

      var body = document.createElement("div");
      body.className = "ec-line-body";
      var speaker = document.createElement("span");
      speaker.className = "ec-speaker ec-speaker-" + String(line.speaker || "a").toLowerCase();
      speaker.textContent = (line.speaker || "A") + ":";
      var text = document.createElement("span");
      text.className = "ec-text";
      text.textContent = " " + (line.text || "");
      body.appendChild(speaker);
      body.appendChild(text);

      inner.appendChild(body);

      if (line.speaker === "A" || line.speaker === "B") {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ec-speak-btn";
        btn.setAttribute("aria-label", "Listen to speaker " + line.speaker);
        btn.textContent = "🔊";
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          speakText(line.text);
        });
        inner.appendChild(btn);
      }

      row.appendChild(inner);
      els.dialogue.appendChild(row);
    });

    log("renderDialogue", (lesson.dialogue || []).length, "lines");
  }

  var QUIZ_TYPE_LABELS = {
    reading: "Reading Comprehension",
    vocabulary: "Vocabulary",
    grammar: "Grammar",
  };

  function renderQuiz(lesson) {
    if (!els.quiz) return;
    els.quiz.innerHTML = "";
    if (els.quizScore) els.quizScore.textContent = "";
    var questions = lesson.quiz || [];
    if (!questions.length) {
      els.quiz.innerHTML = "<p class=\"subtle\">No quiz questions for this lesson yet.</p>";
      return;
    }
    questions.forEach(function (q, qi) {
      var block = document.createElement("div");
      block.className = "ec-quiz-q card";
      if (q.type && QUIZ_TYPE_LABELS[q.type]) {
        var typeEl = document.createElement("div");
        typeEl.className = "ec-quiz-type";
        typeEl.textContent = QUIZ_TYPE_LABELS[q.type];
        block.appendChild(typeEl);
      }
      var title = document.createElement("p");
      title.className = "ec-quiz-question";
      title.textContent = (qi + 1) + ". " + q.question;
      block.appendChild(title);
      var opts = document.createElement("div");
      opts.className = "ec-quiz-options";
      (q.options || []).forEach(function (opt, oi) {
        var label = document.createElement("label");
        label.className = "ec-quiz-opt";
        var input = document.createElement("input");
        input.type = "radio";
        input.name = "ecq-" + lesson.id + "-" + qi;
        input.value = String(oi);
        input.addEventListener("change", function () {
          state.quizAnswers[qi] = oi;
        });
        label.appendChild(input);
        label.appendChild(document.createTextNode(" " + opt));
        opts.appendChild(label);
      });
      block.appendChild(opts);
      els.quiz.appendChild(block);
    });
    var submit = document.createElement("button");
    submit.type = "button";
    submit.className = "btn primary";
    submit.textContent = "Submit Quiz";
    submit.addEventListener("click", function () { submitQuiz(lesson); });
    els.quiz.appendChild(submit);
  }

  function submitQuiz(lesson) {
    var questions = lesson.quiz || [];
    var correct = 0;
    questions.forEach(function (q, qi) {
      if (state.quizAnswers[qi] === q.correct) correct++;
    });
    state.quizSubmitted = true;
    var pct = questions.length ? Math.round((correct / questions.length) * 100) : 0;
    if (els.quizScore) {
      els.quizScore.textContent = "Score: " + correct + " / " + questions.length + " (" + pct + "%)";
    }
    if (pct >= 66) markLessonComplete(lesson.id);
    updateProgressDisplay();
    highlightQuizResults(lesson);
  }

  function highlightQuizResults(lesson) {
    var blocks = els.quiz ? els.quiz.querySelectorAll(".ec-quiz-q") : [];
    (lesson.quiz || []).forEach(function (q, qi) {
      var block = blocks[qi];
      if (!block) return;
      var chosen = state.quizAnswers[qi];
      if (chosen === q.correct) block.classList.add("ec-correct");
      else block.classList.add("ec-wrong");
    });
  }

  function getProgress() {
    try {
      return JSON.parse(localStorage.getItem("ec_progress") || "{}");
    } catch (e) {
      logError("getProgress parse error", e);
      return {};
    }
  }

  function saveProgress(data) {
    try {
      localStorage.setItem("ec_progress", JSON.stringify(data));
    } catch (e) {
      logError("saveProgress error", e);
    }
  }

  function isLessonComplete(lessonId) {
    var p = getProgress();
    return !!(p.completed && p.completed[lessonId]);
  }

  function markLessonComplete(lessonId) {
    var p = getProgress();
    if (!p.completed) p.completed = {};
    p.completed[lessonId] = true;
    saveProgress(p);
  }

  function updateProgressDisplay() {
    var p = getProgress();
    var completed = p.completed ? Object.keys(p.completed).length : 0;
    var total = (indexData.stats && indexData.stats.lessons) || 0;
    var pct = total ? Math.round((completed / total) * 100) : 0;
    if (els.progressBar) els.progressBar.style.width = pct + "%";
    if (els.progressText) {
      els.progressText.textContent = completed + " / " + total + " lessons completed (" + pct + "%)";
    }
  }

  function showHome() {
    log("showHome");
    stopSpeech();
    renderHome();
  }

  var speakQueue = [];
  var speaking = false;

  function getVoices() {
    return window.speechSynthesis ? speechSynthesis.getVoices() : [];
  }

  function pickEnglishVoice() {
    var voices = getVoices();
    var en = voices.filter(function (v) { return /^en(-|_)/i.test(v.lang); });
    return en.find(function (v) { return /US|GB|AU/i.test(v.lang); }) || en[0] || voices[0] || null;
  }

  function speakText(text, onEnd) {
    if (!window.speechSynthesis) {
      showStatus("Speech synthesis is not supported in this browser.", true);
      return;
    }
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US";
    u.rate = 0.95;
    var voice = pickEnglishVoice();
    if (voice) u.voice = voice;
    u.onend = function () { if (onEnd) onEnd(); };
    speechSynthesis.speak(u);
  }

  function speakSequence(texts, onEnd) {
    if (!texts || !texts.length) return;
    speakQueue = texts.slice();
    speaking = true;
    function next() {
      if (!speaking || !speakQueue.length) {
        speaking = false;
        if (onEnd) onEnd();
        return;
      }
      var line = speakQueue.shift();
      speakText(line, next);
    }
    next();
  }

  function stopSpeech() {
    speaking = false;
    speakQueue = [];
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  if (window.speechSynthesis) {
    speechSynthesis.onvoiceschanged = function () { getVoices(); };
    getVoices();
  }

  log("script loaded, readyState=", document.readyState);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      log("DOMContentLoaded fired");
      init();
    });
  } else {
    log("DOM already ready, init now");
    init();
  }
})();
