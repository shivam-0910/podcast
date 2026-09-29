// Conversation screen: load an episode by id and show the two-host transcript.
// Audio playback, the active-line highlight, waveform and controls are added in Steps 10-12.
// All episode text is inserted with textContent (never innerHTML).
(function () {
  "use strict";

  const LOAD_ERROR = "Unable to load this episode right now. Please try again.";
  const EPISODE_ID_RE = /^[0-9a-f]{32}$/;

  const params = new URLSearchParams(window.location.search);
  const episodeId = (params.get("id") || "").trim();

  const titleEl = document.getElementById("episode-title");
  const metaEl = document.getElementById("episode-meta");
  const statusEl = document.getElementById("status");
  const transcriptEl = document.getElementById("transcript");
  const noteEl = document.getElementById("episode-note");
  const backToNewsEl = document.getElementById("back-to-news");

  let languageNames = {};
  try {
    languageNames = JSON.parse(document.getElementById("languages-data").textContent) || {};
  } catch (err) {
    languageNames = {};
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
      btn.addEventListener("click", loadEpisode);
      statusEl.appendChild(btn);
    }

    const home = document.createElement("a");
    home.className = "text-link";
    home.href = "/";
    home.textContent = "Start a new search";
    statusEl.appendChild(home);
  }

  function clearMessage() {
    statusEl.textContent = "";
  }

  function isValidEpisode(data) {
    return (
      data &&
      typeof data === "object" &&
      typeof data.title === "string" &&
      Array.isArray(data.conversation) &&
      data.conversation.length > 0 &&
      data.conversation.every(function (s) {
        return s && (s.speaker === "host_a" || s.speaker === "host_b") && typeof s.text === "string";
      })
    );
  }

  function renderEpisode(episode) {
    document.title = episode.title + " - AI News Podcast";
    titleEl.textContent = episode.title;

    const languageName = languageNames[episode.language] || episode.language || "";
    const count = episode.conversation.length;
    metaEl.textContent = [languageName, count + " segments"].filter(Boolean).join(" \u2022 ");

    if (episode.topic) {
      backToNewsEl.href = "/news?q=" + encodeURIComponent(episode.topic);
      backToNewsEl.hidden = false;
    }

    transcriptEl.textContent = "";
    episode.conversation.forEach(function (segment) {
      const isHostA = segment.speaker === "host_a";

      const bubble = document.createElement("div");
      bubble.className = "bubble " + (isHostA ? "host-a" : "host-b");
      bubble.dataset.segmentId = String(segment.id);

      const label = document.createElement("div");
      label.className = "bubble-speaker";
      label.textContent = isHostA ? "HOST A" : "HOST B";
      bubble.appendChild(label);

      const text = document.createElement("p");
      text.className = "bubble-text";
      text.textContent = segment.text;
      bubble.appendChild(text);

      transcriptEl.appendChild(bubble);
    });

    noteEl.hidden = false;
  }

  async function loadEpisode() {
    transcriptEl.textContent = "";
    noteEl.hidden = true;
    metaEl.textContent = "";

    if (!EPISODE_ID_RE.test(episodeId)) {
      titleEl.textContent = "Episode not found";
      showMessage("This episode link is not valid.", false);
      return;
    }

    titleEl.textContent = "Loading episode\u2026";
    clearMessage();

    let response;
    let data = null;
    try {
      response = await fetch("/api/episode/" + episodeId);
      data = await response.json();
    } catch (err) {
      titleEl.textContent = "Episode unavailable";
      showMessage(LOAD_ERROR, true);
      return;
    }

    if (!response.ok) {
      titleEl.textContent = response.status === 404 ? "Episode not found" : "Episode unavailable";
      const message = data && typeof data.error === "string" ? data.error : LOAD_ERROR;
      showMessage(message, response.status !== 404);
      return;
    }

    if (!isValidEpisode(data)) {
      titleEl.textContent = "Episode unavailable";
      showMessage(LOAD_ERROR, true);
      return;
    }

    clearMessage();
    renderEpisode(data);
  }

  loadEpisode();
})();
