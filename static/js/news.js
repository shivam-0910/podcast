// News results page: fetch /api/search, render article cards, manage selection,
// create the podcast conversation via /api/episode/create, then open the conversation screen.
// Everything stays inside this site: no article links to other websites are rendered.
// All external text is inserted with textContent (never innerHTML) so news content cannot inject HTML.
(function () {
  "use strict";

  const GENERIC_ERROR = "Unable to search for news right now. Please try again.";
  const CREATE_ERROR = "Unable to create the podcast right now. Please try again.";
  const MAX_SELECTED = 5;
  const SINGLE_PAGE_VIEW = true; // one article per screen; set false to restore the two-page desktop spread
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
  const detailsCache = new Map(); // article id -> {image_url, paragraphs} or null when unavailable
  const detailsPending = new Set();
  let creating = false;
  let articleResults = [];
  let currentIndex = 0;
  let mobileLayout = null;

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

  function showMessage(text, withRetry, isLoading) {
    statusEl.textContent = "";
    statusEl.classList.toggle("is-loading", Boolean(isLoading));
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
    statusEl.classList.remove("is-loading");
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
    countEl.textContent = count + (count === 1 ? " story selected" : " stories selected");
    clearBtn.hidden = count === 0 || creating;
    createBtn.disabled = count === 0 || creating;
    if (languageEl) languageEl.disabled = creating; // language is locked while an episode is being made
  }

  function setPageSelected(page, isSelected) {
    page.classList.toggle("selected", isSelected);
  }

  function handleToggle(article, page, checkbox) {
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
      setPageSelected(page, true);
    } else {
      selected.delete(article.id);
      setPageSelected(page, false);
    }
    setNote("");
    updateSelectionUI();
  }

  function clearSelection() {
    if (creating) return;
    selected.clear();
    resultsEl.querySelectorAll(".newspaper-page").forEach(function (page) {
      setPageSelected(page, false);
      const checkbox = page.querySelector(".paper-check");
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
    const payload = { topic: topic, language: language, articles: articles };

    let response = null;
    let data = null;
    let failed = false;
    try {
      response = await fetch("/api/episode/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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

  // ---------- article details (full-size image + longer text) ----------

  function validDetails(data) {
    return data && typeof data === "object" && Array.isArray(data.paragraphs) &&
      data.paragraphs.every(function (p) { return typeof p === "string"; });
  }

  async function loadDetails(articleId) {
    if (detailsCache.has(articleId)) {
      applyDetails(articleId);
      return;
    }
    if (detailsPending.has(articleId)) return;
    detailsPending.add(articleId);
    let details = null;
    try {
      const response = await fetch("/api/article/" + encodeURIComponent(articleId));
      if (response.ok) details = await response.json();
    } catch (err) {
      details = null; // keep the snippet and thumbnail
    }
    detailsPending.delete(articleId);
    detailsCache.set(articleId, validDetails(details) ? details : null);
    applyDetails(articleId);
  }

  function findPage(articleId) {
    const pages = resultsEl.querySelectorAll(".newspaper-page[data-article-id]");
    return Array.from(pages).find(function (p) { return p.dataset.articleId === articleId; }) || null;
  }

  function applyDetails(articleId) {
    const details = detailsCache.get(articleId);
    const page = findPage(articleId);
    if (!details || !page || page.dataset.detailed) return;
    const body = page.querySelector(".paper-body");
    const text = page.querySelector(".paper-text");
    if (!body || !text) return;
    page.dataset.detailed = "1";

    if (details.paragraphs.length > 0) {
      const story = document.createElement("div");
      story.className = "paper-story";
      details.paragraphs.forEach(function (paragraph) {
        const p = document.createElement("p");
        p.textContent = paragraph;
        story.appendChild(p);
      });
      const oldStory = text.querySelector(".paper-story");
      if (oldStory) oldStory.replaceWith(story);
      else text.insertBefore(story, text.firstChild);
    }

    // Swap in the sharp image only once it has loaded; otherwise keep the thumbnail.
    if (isHttpUrl(details.image_url)) {
      const loader = new Image();
      loader.referrerPolicy = "no-referrer";
      loader.addEventListener("load", function () {
        if (!page.isConnected) return;
        let image = body.querySelector(".paper-figure img");
        if (!image) {
          const figure = document.createElement("figure");
          figure.className = "paper-figure";
          image = document.createElement("img");
          image.alt = "";
          image.decoding = "async";
          image.referrerPolicy = "no-referrer";
          figure.appendChild(image);
          body.insertBefore(figure, body.firstChild);
          body.classList.remove("no-image");
        }
        image.src = details.image_url;
      });
      loader.src = details.image_url;
    }
  }

  // Load details for the visible page(s) and prefetch the next one.
  function loadVisibleDetails() {
    const visible = isMobileSpread() ? 2 : 3;
    articleResults.slice(currentIndex, currentIndex + visible).forEach(function (article) {
      loadDetails(article.id);
    });
  }

  // ---------- rendering ----------

  function textElement(tagName, className, text) {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = text;
    return element;
  }

  function createArticlePage(article, index) {
    const page = document.createElement("article");
    page.className = "newspaper-page";
    page.dataset.articleId = article.id;
    page.setAttribute("aria-label", "Page " + (index + 1) + ": " + article.title);

    const section = textElement("p", "paper-section", topic || "News");
    page.appendChild(section);
    page.appendChild(textElement("h3", "paper-headline", article.title || "Untitled story"));

    const body = document.createElement("div");
    body.className = "paper-body";
    if (isHttpUrl(article.image_url)) {
      const figure = document.createElement("figure");
      figure.className = "paper-figure";
      const image = document.createElement("img");
      image.src = article.image_url;
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", function () {
        figure.remove();
        body.classList.add("no-image");
      });
      figure.appendChild(image);
      body.appendChild(figure);
    } else {
      body.classList.add("no-image");
    }

    const text = document.createElement("div");
    text.className = "paper-text";
    if (article.snippet) {
      text.appendChild(textElement("p", "paper-story", article.snippet));
    }
    const metadata = [article.source, article.published_at].filter(Boolean).join(" \u2022 ");
    if (metadata) text.appendChild(textElement("p", "paper-meta", metadata));
    body.appendChild(text);
    page.appendChild(body);

    const footer = document.createElement("div");
    footer.className = "paper-page-footer";
    if (isHttpUrl(article.url)) {
      const link = textElement("a", "paper-read-link", "READ FULL ARTICLE \u2192");
      link.href = article.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      footer.appendChild(link);
    }

    const selectLabel = document.createElement("label");
    selectLabel.className = "paper-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "paper-check";
    checkbox.value = article.id;
    checkbox.checked = selected.has(article.id);
    checkbox.setAttribute("aria-label", "Select article: " + article.title);
    checkbox.addEventListener("change", function () {
      handleToggle(article, page, checkbox);
    });
    selectLabel.append(checkbox, document.createTextNode(" Select this story"));
    footer.appendChild(selectLabel);
    footer.appendChild(textElement("span", "paper-page-number", "PAGE " + (index + 1)));
    page.appendChild(footer);

    setPageSelected(page, checkbox.checked);
    page.addEventListener("click", function (event) {
      if (event.target.closest("a, input, label, button")) return;
      checkbox.click();
    });
    return page;
  }

  function isMobileSpread() {
    if (SINGLE_PAGE_VIEW) return true;
    return window.matchMedia("(max-width: 1100px)").matches;
  }

  function renderSpread(direction) {
    resultsEl.textContent = "";
    const mobile = isMobileSpread();
    mobileLayout = mobile;
    const start = mobile ? currentIndex : Math.floor(currentIndex / 2) * 2;
    currentIndex = start;

    const edition = document.createElement("section");
    edition.className = "newspaper-edition";
    const masthead = document.createElement("header");
    masthead.className = "newspaper-masthead";
    masthead.appendChild(textElement("p", "masthead-kicker", "Independent news, clearly told"));
    masthead.appendChild(textElement("h1", "masthead-title", "THE AI NEWSCAST"));
    masthead.appendChild(textElement("p", "masthead-date", new Intl.DateTimeFormat(undefined, {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    }).format(new Date()).toUpperCase()));
    edition.appendChild(masthead);

    const editionLine = textElement("p", "edition-topic", "NEWS ON: " + topic);
    edition.appendChild(editionLine);

    const spread = document.createElement("div");
    spread.className = "newspaper-spread" + (direction ? " turn-" + direction : "");
    const end = Math.min(start + (mobile ? 1 : 2), articleResults.length);
    for (let index = start; index < end; index += 1) {
      spread.appendChild(createArticlePage(articleResults[index], index));
    }
    if (!mobile && end === articleResults.length && articleResults.length % 2 === 1) {
      const blankPage = document.createElement("div");
      blankPage.className = "newspaper-page newspaper-page-empty";
      blankPage.setAttribute("aria-label", "Blank page");
      blankPage.setAttribute("aria-hidden", "true");
      spread.appendChild(blankPage);
    }
    edition.appendChild(spread);

    const navigation = document.createElement("nav");
    navigation.className = "newspaper-navigation";
    navigation.setAttribute("aria-label", "Newspaper pages");
    const previous = textElement("button", "page-nav-button", "\u25c0 PREVIOUS");
    previous.type = "button";
    previous.disabled = start === 0;
    previous.addEventListener("click", function () { navigateSpread(-1); });
    const current = mobile
      ? "PAGE " + (start + 1) + " OF " + articleResults.length
      : "PAGES " + (start + 1) + "\u2013" + end + " OF " + articleResults.length;
    navigation.append(previous, textElement("span", "spread-count", current));
    const next = textElement("button", "page-nav-button", "NEXT \u25b6");
    next.type = "button";
    next.disabled = end >= articleResults.length;
    next.addEventListener("click", function () { navigateSpread(1); });
    navigation.appendChild(next);
    edition.appendChild(navigation);
    resultsEl.appendChild(edition);
    loadVisibleDetails();
  }

  function navigateSpread(direction) {
    const step = isMobileSpread() ? 1 : 2;
    const lastStart = isMobileSpread()
      ? articleResults.length - 1
      : Math.floor((articleResults.length - 1) / 2) * 2;
    currentIndex = Math.max(0, Math.min(currentIndex + direction * step, lastStart));
    renderSpread(direction > 0 ? "next" : "previous");
  }

  function renderArticles(articles) {
    articleResults = articles;
    currentIndex = 0;
    renderSpread("");
  }

  // ---------- loading ----------

  async function loadNews() {
    resultsEl.textContent = "";
    articleResults = [];
    currentIndex = 0;
    mobileLayout = isMobileSpread();
    selected.clear();
    setNote("");
    updateSelectionUI();

    if (!topic) {
      titleEl.textContent = "News";
      showMessage("Please enter a topic to search for.", false);
      return;
    }

    titleEl.textContent = "News about \u201C" + topic + "\u201D";
    showMessage("Searching the wires\u2026", false, true);

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
  window.addEventListener("resize", function () {
    if (articleResults.length > 0 && isMobileSpread() !== mobileLayout) renderSpread("");
  });

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
