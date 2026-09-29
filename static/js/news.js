// News results page: fetch /api/search, render article cards, manage selection,
// create the podcast conversation via /api/episode/create, then open the conversation screen.
// Everything stays inside this site: no article links to other websites are rendered.
// All external text is inserted with textContent (never innerHTML) so news content cannot inject HTML.
(function () {
  "use strict";

  const GENERIC_ERROR = "Unable to search for news right now. Please try again.";
  const CREATE_ERROR = "Unable to create the podcast right now. Please try again.";
  const MAX_SELECTED = 5;
  const FALLBACK_LANGUAGE = "en"; // only used if the selector is missing from the page
  const LANGUAGE_STORAGE_KEY = "podcast.language";
  const CREATE_TIMEOUT_MS = 90000;
  const CREATE_LABEL = "CREATE AI PODCAST";
  const EPISODE_ID_RE = /^[0-9a-f]{32}$/;

  const params = new URLSearchParams(window.location.search);
  const topic = (params.get("q") || "").trim();

  const titleEl = document.getElementById("results-title");
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const inputEl = document.getElementById("topic-input");
  const countEl = document.getElementById("selected-count");
  const clearBtn = document.getElementById("clear-btn");
  const noteEl = document.getElementById("selection-note");
  const createBtn = document.getElementById("create-btn");
  const languageEl = document.getElementById("language-select");

  const selected = new Map(); // article id -> article (insertion-ordered)
  let creating = false;

  // ---------- helpers ----------

  function isHttpUrl(value) {
    if (typeof value !== "string") return false;
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch (err) {
      return false;
    }
  }

  function showMessage(text, withRetry) {
    statusEl.textContent = "";
    const p = document.createElement("p");
    p.textContent = text;
    statusEl.appendChild(p);

    if (withRetry) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary-btn";
      btn.textContent = "Try again";
      btn.addEventListener("click", loadNews);
      statusEl.appendChild(btn);
    }
  }

  function clearMessage() {
    statusEl.textContent = "";
  }

  function setNote(text) {
    noteEl.textContent = text || "";
  }

  // ---------- language ----------

  // The chosen language code, or the fallback if the selector is missing or has no usable value.
  function selectedLanguage() {
    if (!languageEl) return FALLBACK_LANGUAGE;
    const option = languageEl.selectedOptions && languageEl.selectedOptions[0];
    if (!option || option.disabled || !languageEl.value) {
      return languageEl.dataset.default || FALLBACK_LANGUAGE;
    }
    return languageEl.value;
  }

  function restoreLanguage() {
    if (!languageEl) return;
    let saved = null;
    try {
      saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    } catch (err) {
      saved = null; // storage blocked: keep the server's default
    }
    if (!saved) return;
    const option = Array.from(languageEl.options).find(function (o) {
      return o.value === saved && !o.disabled;
    });
    if (option) languageEl.value = saved;
  }

  function rememberLanguage() {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, selectedLanguage());
    } catch (err) {
      /* storage blocked: the choice simply won't persist */
    }
  }

  // ---------- selection ----------

  function updateSelectionUI() {
    const count = selected.size;
    countEl.textContent = count + " selected";
    clearBtn.hidden = count === 0 || creating;
    createBtn.disabled = count === 0 || creating;
    if (languageEl) languageEl.disabled = creating; // language is locked while an episode is being made
  }

  function setCardSelected(card, isSelected) {
    card.classList.toggle("selected", isSelected);
  }

  function handleToggle(article, card, checkbox) {
    if (creating) {
      checkbox.checked = !checkbox.checked; // selection is locked while an episode is being created
      return;
    }
    if (checkbox.checked) {
      if (selected.size >= MAX_SELECTED) {
        checkbox.checked = false;
        setNote("You can select up to " + MAX_SELECTED + " articles.");
        return;
      }
      selected.set(article.id, article);
      setCardSelected(card, true);
    } else {
      selected.delete(article.id);
      setCardSelected(card, false);
    }
    setNote("");
    updateSelectionUI();
  }

  function clearSelection() {
    if (creating) return;
    selected.clear();
    resultsEl.querySelectorAll(".card").forEach(function (card) {
      setCardSelected(card, false);
      const checkbox = card.querySelector(".card-check");
      if (checkbox) checkbox.checked = false;
    });
    setNote("");
    updateSelectionUI();
  }

  // ---------- episode creation ----------

  function resetCreatingState() {
    creating = false;
    createBtn.textContent = CREATE_LABEL;
    updateSelectionUI();
  }

  async function handleCreate() {
    if (creating || selected.size === 0) return;

    const language = selectedLanguage(); // read before the selector is locked
    creating = true;
    createBtn.textContent = "CREATING\u2026";
    updateSelectionUI();
    setNote("Writing your episode. This can take up to a minute.");

    const articles = Array.from(selected.values()).map(function (a) {
      return {
        id: a.id,
        title: a.title,
        source: a.source,
        url: a.url,
        snippet: a.snippet,
        published_at: a.published_at,
        image_url: a.image_url,
      };
    });

    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, CREATE_TIMEOUT_MS);

    let response = null;
    let data = null;
    let failed = false;
    try {
      response = await fetch("/api/episode/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topic, language: language, articles: articles }),
        signal: controller.signal,
      });
      data = await response.json();
    } catch (err) {
      failed = true;
    } finally {
      clearTimeout(timer);
    }

    if (failed) {
      resetCreatingState();
      setNote(CREATE_ERROR);
      return;
    }
    if (!response.ok) {
      resetCreatingState();
      setNote(data && typeof data.error === "string" ? data.error : CREATE_ERROR);
      return;
    }
    if (!data || typeof data.episode_id !== "string" || !EPISODE_ID_RE.test(data.episode_id)) {
      resetCreatingState();
      setNote(CREATE_ERROR);
      return;
    }

    // Success: open the conversation screen. The button stays locked until the page unloads.
    setNote("Opening your episode\u2026");
    window.location.href = "/conversation?id=" + encodeURIComponent(data.episode_id);
  }

  // ---------- rendering ----------

  function createCard(article) {
    const card = document.createElement("article");
    card.className = "card";
    card.dataset.articleId = article.id;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "card-check";
    checkbox.value = article.id;
    checkbox.setAttribute("aria-label", "Select article: " + article.title);
    checkbox.addEventListener("change", function () {
      handleToggle(article, card, checkbox);
    });
    card.appendChild(checkbox);

    const body = document.createElement("div");
    body.className = "card-body";

    const heading = document.createElement("h3");
    heading.className = "card-title";
    heading.textContent = article.title;
    body.appendChild(heading);

    const meta = document.createElement("p");
    meta.className = "card-meta";
    meta.textContent = [article.source, article.published_at].filter(Boolean).join(" \u2022 ");
    body.appendChild(meta);

    if (article.snippet) {
      const snippet = document.createElement("p");
      snippet.className = "card-snippet";
      snippet.textContent = article.snippet;
      body.appendChild(snippet);
    }

    card.appendChild(body);

    if (isHttpUrl(article.image_url)) {
      const img = document.createElement("img");
      img.className = "card-image";
      img.src = article.image_url;
      img.alt = "";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", function () {
        img.remove();
      });
      card.appendChild(img);
    }

    // Clicking anywhere on the card (except the checkbox itself) toggles selection.
    card.addEventListener("click", function (event) {
      if (event.target.closest("input")) return;
      checkbox.click();
    });

    return card;
  }

  function renderArticles(articles) {
    resultsEl.textContent = "";
    articles.forEach(function (article) {
      resultsEl.appendChild(createCard(article));
    });
  }

  // ---------- loading ----------

  async function loadNews() {
    resultsEl.textContent = "";
    selected.clear();
    setNote("");
    updateSelectionUI();

    if (!topic) {
      titleEl.textContent = "News";
      showMessage("Please enter a topic to search for.", false);
      return;
    }

    titleEl.textContent = "News about \u201C" + topic + "\u201D";
    showMessage("Searching for news\u2026", false);

    let response;
    let data = null;
    try {
      response = await fetch("/api/search?q=" + encodeURIComponent(topic));
      data = await response.json();
    } catch (err) {
      showMessage(GENERIC_ERROR, true);
      return;
    }

    if (!response.ok) {
      const message = data && typeof data.error === "string" ? data.error : GENERIC_ERROR;
      showMessage(message, true);
      return;
    }

    const articles = data && Array.isArray(data.results) ? data.results : null;
    if (!articles) {
      showMessage(GENERIC_ERROR, true);
      return;
    }

    if (articles.length === 0) {
      showMessage("No news found for this topic. Try a different search.", false);
      return;
    }

    clearMessage();
    renderArticles(articles);
  }

  // ---------- init ----------

  clearBtn.addEventListener("click", clearSelection);
  createBtn.addEventListener("click", handleCreate);
  if (languageEl) languageEl.addEventListener("change", rememberLanguage);

  // Coming back with the browser Back button can restore this page from cache in its "creating" state.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      resetCreatingState();
      setNote("");
    }
  });

  if (inputEl) {
    inputEl.value = topic;
  }
  restoreLanguage();
  updateSelectionUI();
  loadNews();
})();
