// Conversation screen: load an episode, show the two-host transcript, and play the audio
// segments one after another with a synced transcript, custom controls and an animated waveform.
// All episode text is inserted with textContent (never innerHTML).
(function () {
  "use strict";

  const LOAD_ERROR = "Unable to load this episode right now. Please try again.";
  const EPISODE_ID_RE = /^[0-9a-f]{32}$/;
  const RESTART_THRESHOLD_SECONDS = 3; // "Previous" restarts the line if it has played longer than this
  const WAVE_BARS = 28;
  const VOICE_STORAGE_KEY = "podcast.voices";
  const VOICE_UPDATE_TIMEOUT_MS = 240000;

  const params = new URLSearchParams(window.location.search);
  const episodeId = (params.get("id") || "").trim();

  const titleEl = document.getElementById("episode-title");
  const metaEl = document.getElementById("episode-meta");
  const statusEl = document.getElementById("status");
  const transcriptEl = document.getElementById("transcript");
  const backToNewsEl = document.getElementById("back-to-news");

  const playerEl = document.getElementById("player");
  const waveformEl = document.getElementById("waveform");
  const prevBtn = document.getElementById("prev-btn");
  const playBtn = document.getElementById("play-btn");
  const nextBtn = document.getElementById("next-btn");
  const progressEl = document.getElementById("progress");
  const timeEl = document.getElementById("time-display");
  const volumeEl = document.getElementById("volume");
  const voiceSettingsEl = document.getElementById("voice-settings");
  const hostAVoiceEl = document.getElementById("host-a-voice");
  const hostBVoiceEl = document.getElementById("host-b-voice");
  const hostASampleBtn = document.getElementById("host-a-sample");
  const hostBSampleBtn = document.getElementById("host-b-sample");
  const voiceStatusEl = document.getElementById("voice-status");
  const applyVoicesBtn = document.getElementById("apply-voices-btn");

  let languageNames = {};
  try {
    languageNames = JSON.parse(document.getElementById("languages-data").textContent) || {};
  } catch (err) {
    languageNames = {};
  }

  let voiceOptionsByLanguage = {};
  try {
    voiceOptionsByLanguage = JSON.parse(document.getElementById("voice-options-data").textContent) || {};
  } catch (err) {
    voiceOptionsByLanguage = {};
  }

  // ---------- playback state ----------

  const audio = new Audio();
  audio.preload = "auto";
  const sampleAudio = new Audio();
  sampleAudio.preload = "none";

  let segments = [];   // episode.conversation
  let bubbles = [];    // one element per segment
  let durations = [];  // seconds per segment (NaN until metadata loads)
  let current = -1;    // index of the loaded segment, -1 = nothing loaded yet
  let finished = false;
  let seeking = false;
  let currentLanguage = "";
  let appliedVoices = {};
  let savedVoiceChoices = {};
  let sampleRequest = 0;
  let applyingVoices = false;

  try {
    const saved = JSON.parse(window.localStorage.getItem(VOICE_STORAGE_KEY) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) savedVoiceChoices = saved;
  } catch (err) {
    savedVoiceChoices = {};
  }

  // ---------- generic helpers ----------

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
        return (
          s &&
          (s.speaker === "host_a" || s.speaker === "host_b") &&
          typeof s.text === "string" &&
          typeof s.audio_url === "string" &&
          s.audio_url.indexOf("/audio/") === 0
        );
      })
    );
  }

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  // ---------- voice settings and previews ----------

  function voiceSelects() {
    return [
      { element: hostAVoiceEl, speaker: "host_a" },
      { element: hostBVoiceEl, speaker: "host_b" },
    ];
  }

  function selectedVoices() {
    return {
      host_a: hostAVoiceEl.value,
      host_b: hostBVoiceEl.value,
    };
  }

  function rememberSelectedVoices() {
    if (!currentLanguage || voiceSettingsEl.hidden) return;
    savedVoiceChoices[currentLanguage] = selectedVoices();
    try {
      window.localStorage.setItem(VOICE_STORAGE_KEY, JSON.stringify(savedVoiceChoices));
    } catch (err) {
      // The current selection still applies if browser storage is unavailable.
    }
  }

  function updateApplyVoicesButton() {
    if (!applyVoicesBtn || voiceSettingsEl.hidden) return;
    const selected = selectedVoices();
    const changed = selected.host_a !== appliedVoices.host_a || selected.host_b !== appliedVoices.host_b;
    applyVoicesBtn.disabled = applyingVoices || !changed;
    applyVoicesBtn.textContent = applyingVoices ? "Applying..." : "Apply to episode";
  }

  function setVoiceStatus(message) {
    if (voiceStatusEl) voiceStatusEl.textContent = message || "";
  }

  function renderVoiceSettings(episode) {
    if (!voiceSettingsEl || !hostAVoiceEl || !hostBVoiceEl) return;
    currentLanguage = episode.language || "en";
    const config = voiceOptionsByLanguage[currentLanguage];
    if (!config || !Array.isArray(config.options) || !config.options.length) {
      voiceSettingsEl.hidden = true;
      return;
    }

    appliedVoices = episode.voices || config.defaults;
    const saved = savedVoiceChoices[currentLanguage] || {};
    voiceSelects().forEach(function (item) {
      const select = item.element;
      select.textContent = "";
      config.options.forEach(function (voice) {
        const option = document.createElement("option");
        option.value = voice.id;
        option.textContent = voice.label;
        select.appendChild(option);
      });
      const ids = config.options.map(function (voice) { return voice.id; });
      const requested = saved[item.speaker] || appliedVoices[item.speaker] || config.defaults[item.speaker];
      select.value = ids.includes(requested) ? requested : config.defaults[item.speaker];
      select.disabled = applyingVoices;
    });
    voiceSettingsEl.hidden = false;
    setVoiceStatus("");
    updateApplyVoicesButton();
  }

  function previewVoice(speaker) {
    const voiceId = speaker === "host_a" ? hostAVoiceEl.value : hostBVoiceEl.value;
    if (!voiceId || applyingVoices) return;
    const requestId = ++sampleRequest;
    sampleAudio.pause();
    audio.pause();
    setVoiceStatus("Loading voice sample...");
    const query = new URLSearchParams({
      language: currentLanguage,
      speaker: speaker,
      voice_id: voiceId,
      request: String(requestId),
    });
    sampleAudio.src = "/api/tts/sample?" + query.toString();
    const promise = sampleAudio.play();
    if (promise && typeof promise.catch === "function") {
      promise.catch(function () {
        if (requestId === sampleRequest) setVoiceStatus("Unable to play this voice sample. Please try again.");
      });
    }
  }

  async function applyVoiceChanges() {
    if (applyingVoices || applyVoicesBtn.disabled) return;
    const voices = selectedVoices();
    rememberSelectedVoices();
    applyingVoices = true;
    sampleRequest++;
    sampleAudio.pause();
    audio.pause();
    voiceSelects().forEach(function (item) { item.element.disabled = true; });
    hostASampleBtn.disabled = true;
    hostBSampleBtn.disabled = true;
    applyVoicesBtn.disabled = true;
    applyVoicesBtn.textContent = "Applying...";
    setVoiceStatus("Updating episode audio...");

    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, VOICE_UPDATE_TIMEOUT_MS);
    try {
      const response = await fetch("/api/episode/" + encodeURIComponent(episodeId) + "/voices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voices: voices }),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data && typeof data.error === "string" ? data.error : "Unable to update episode voices.");
      stopPlayback();
      renderEpisode(data);
      setVoiceStatus("Episode voices updated.");
    } catch (err) {
      setVoiceStatus(err.name === "AbortError" ? "Voice update timed out. Please try again." : err.message);
    } finally {
      clearTimeout(timer);
      applyingVoices = false;
      voiceSelects().forEach(function (item) { item.element.disabled = false; });
      hostASampleBtn.disabled = false;
      hostBSampleBtn.disabled = false;
      updateApplyVoicesButton();
    }
  }

  sampleAudio.addEventListener("playing", function () {
    setVoiceStatus("Playing voice sample...");
  });
  sampleAudio.addEventListener("ended", function () {
    setVoiceStatus("Sample finished.");
  });
  sampleAudio.addEventListener("error", function () {
    if (sampleAudio.getAttribute("src")) setVoiceStatus("Unable to play this voice sample. Please try again.");
  });

  // ---------- waveform ----------

  function buildWaveform() {
    waveformEl.textContent = "";
    for (let i = 0; i < WAVE_BARS; i++) {
      const bar = document.createElement("span");
      bar.className = "wave-bar";
      // Pseudo-random but stable look: vary speed, delay and peak height per bar.
      bar.style.animationDuration = (0.7 + ((i * 37) % 11) / 10) + "s";
      bar.style.animationDelay = (-((i * 53) % 13) / 10) + "s";
      bar.style.setProperty("--peak", (35 + ((i * 29) % 65)) + "%");
      waveformEl.appendChild(bar);
    }
  }

  // state: "playing" (animating), "paused" (frozen), "idle" (flat and dim)
  function setWaveState(state) {
    waveformEl.classList.toggle("playing", state === "playing");
    waveformEl.classList.toggle("paused", state === "paused");
  }

  // ---------- duration / progress ----------

  function loadDurations() {
    durations = segments.map(function () { return NaN; });
    segments.forEach(function (segment, index) {
      const probe = new Audio();
      probe.preload = "metadata";
      probe.addEventListener("loadedmetadata", function () {
        if (isFinite(probe.duration)) {
          durations[index] = probe.duration;
          updateProgress();
        }
      });
      probe.src = segment.audio_url;
    });
  }

  function averageKnown() {
    const known = durations.filter(function (d) { return isFinite(d); });
    if (!known.length) return 0;
    return known.reduce(function (a, b) { return a + b; }, 0) / known.length;
  }

  function durationAt(index) {
    return isFinite(durations[index]) ? durations[index] : averageKnown();
  }

  function totalDuration() {
    let total = 0;
    for (let i = 0; i < segments.length; i++) total += durationAt(i);
    return total;
  }

  function elapsedTime() {
    if (current < 0) return 0;
    if (finished) return totalDuration();
    let elapsed = 0;
    for (let i = 0; i < current; i++) elapsed += durationAt(i);
    return elapsed + (audio.currentTime || 0);
  }

  function updateProgress() {
    const total = totalDuration();
    const elapsed = Math.min(elapsedTime(), total);
    timeEl.textContent = formatTime(elapsed) + " / " + formatTime(total);
    if (!seeking) {
      progressEl.value = total > 0 ? String(Math.round((elapsed / total) * 1000)) : "0";
    }
  }

  // ---------- transcript sync ----------

  function highlight(index) {
    bubbles.forEach(function (bubble, i) {
      bubble.classList.toggle("active", i === index);
    });
    if (index >= 0 && bubbles[index]) {
      bubbles[index].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  // ---------- playback control ----------

  function setPlayButton(isPlaying) {
    playBtn.textContent = isPlaying ? "\u275A\u275A" : "\u25B6";
    playBtn.setAttribute("aria-label", isPlaying ? "Pause" : "Play");
  }

  function updateNavButtons() {
    prevBtn.disabled = current <= 0 && (audio.currentTime || 0) < 0.1;
    nextBtn.disabled = current >= segments.length - 1;
  }

  function play() {
    const promise = audio.play();
    if (promise && typeof promise.catch === "function") {
      promise.catch(function () {
        // Autoplay blocked or the file failed to load: stay paused so the user can retry.
        setPlayButton(false);
        setWaveState(current >= 0 ? "paused" : "idle");
      });
    }
  }

  // Load segment `index`; start playing it when `autoplay` is true.
  function loadSegment(index, autoplay) {
    if (index < 0 || index >= segments.length) return;
    current = index;
    finished = false;
    audio.src = segments[index].audio_url;
    highlight(index);
    updateNavButtons();
    updateProgress();
    if (autoplay) {
      play();
    } else {
      setPlayButton(false);
      setWaveState("paused");
    }
  }

  function togglePlay() {
    if (finished || current < 0) {
      loadSegment(0, true);
      return;
    }
    if (audio.paused) play();
    else audio.pause();
  }

  function goNext() {
    if (current < segments.length - 1) loadSegment(current + 1, !audio.paused || finished);
  }

  function goPrevious() {
    if (current < 0) return;
    const keepPlaying = !audio.paused;
    if ((audio.currentTime || 0) > RESTART_THRESHOLD_SECONDS || current === 0) {
      audio.currentTime = 0;
      updateProgress();
      return;
    }
    loadSegment(current - 1, keepPlaying);
  }

  function seekToFraction(fraction) {
    const total = totalDuration();
    if (total <= 0) return;
    let target = fraction * total;
    let index = 0;
    while (index < segments.length - 1 && target >= durationAt(index)) {
      target -= durationAt(index);
      index++;
    }
    const keepPlaying = !audio.paused && !finished;
    if (index !== current) {
      loadSegment(index, keepPlaying);
      const setTime = function () {
        audio.currentTime = Math.min(target, Math.max(durationAt(index) - 0.05, 0));
        audio.removeEventListener("loadedmetadata", setTime);
      };
      audio.addEventListener("loadedmetadata", setTime);
    } else {
      audio.currentTime = target;
    }
    updateProgress();
  }

  function attachAudioEvents() {
    audio.addEventListener("play", function () {
      setPlayButton(true);
      setWaveState("playing");
    });
    audio.addEventListener("pause", function () {
      if (audio.ended) return; // handled by "ended"
      setPlayButton(false);
      setWaveState("paused");
    });
    audio.addEventListener("timeupdate", function () {
      updateProgress();
      updateNavButtons();
    });
    audio.addEventListener("loadedmetadata", function () {
      if (current >= 0 && isFinite(audio.duration)) {
        durations[current] = audio.duration;
        updateProgress();
      }
    });
    audio.addEventListener("ended", function () {
      if (current < segments.length - 1) {
        loadSegment(current + 1, true); // continue automatically
      } else {
        finished = true;
        setPlayButton(false);
        setWaveState("idle");
        highlight(-1);
        updateProgress();
        updateNavButtons();
      }
    });
    audio.addEventListener("error", function () {
      // A missing/corrupt segment: skip it so the episode keeps going.
      if (!audio.getAttribute("src")) return;
      if (current < segments.length - 1) {
        loadSegment(current + 1, true);
      } else {
        setPlayButton(false);
        setWaveState("idle");
      }
    });
  }

  function initControls() {
    prevBtn.addEventListener("click", goPrevious);
    nextBtn.addEventListener("click", goNext);
    playBtn.addEventListener("click", togglePlay);
    hostAVoiceEl.addEventListener("change", function () {
      rememberSelectedVoices();
      updateApplyVoicesButton();
      previewVoice("host_a");
    });
    hostBVoiceEl.addEventListener("change", function () {
      rememberSelectedVoices();
      updateApplyVoicesButton();
      previewVoice("host_b");
    });
    hostASampleBtn.addEventListener("click", function () { previewVoice("host_a"); });
    hostBSampleBtn.addEventListener("click", function () { previewVoice("host_b"); });
    applyVoicesBtn.addEventListener("click", applyVoiceChanges);

    progressEl.addEventListener("input", function () {
      seeking = true;
      const total = totalDuration();
      timeEl.textContent = formatTime((Number(progressEl.value) / 1000) * total) + " / " + formatTime(total);
    });
    progressEl.addEventListener("change", function () {
      seeking = false;
      seekToFraction(Number(progressEl.value) / 1000);
    });

    volumeEl.addEventListener("input", function () {
      audio.volume = Number(volumeEl.value) / 100;
    });
    audio.volume = Number(volumeEl.value) / 100;

    // Clicking a transcript bubble jumps to that line.
    transcriptEl.addEventListener("click", function (event) {
      const bubble = event.target.closest(".bubble");
      if (!bubble) return;
      const index = bubbles.indexOf(bubble);
      if (index >= 0) loadSegment(index, true);
    });

    // Space toggles play/pause (unless typing in a control that uses space).
    document.addEventListener("keydown", function (event) {
      if (event.code !== "Space") return;
      const tag = (event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "button" || tag === "textarea") return;
      event.preventDefault();
      togglePlay();
    });
  }

  function stopPlayback() {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    sampleRequest++;
    sampleAudio.pause();
    sampleAudio.removeAttribute("src");
    sampleAudio.load();
    current = -1;
    finished = false;
    playerEl.hidden = true;
    setWaveState("idle");
  }

  // ---------- rendering ----------

  function renderEpisode(episode) {
    document.title = episode.title + " - AI News Podcast";
    if (typeof episode.language === "string" && /^[a-z]{2,3}$/.test(episode.language)) {
      document.documentElement.lang = episode.language; // right fonts/screen-reader voice for Indic scripts
    }
    titleEl.textContent = episode.title;

    const languageName = languageNames[episode.language] || episode.language || "";
    const count = episode.conversation.length;
    metaEl.textContent = [languageName, count + " segments"].filter(Boolean).join(" \u2022 ");

    if (episode.topic) {
      backToNewsEl.href = "/news?q=" + encodeURIComponent(episode.topic);
      backToNewsEl.hidden = false;
    }

    renderVoiceSettings(episode);
    segments = episode.conversation;
    bubbles = [];
    transcriptEl.textContent = "";
    segments.forEach(function (segment) {
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
      bubbles.push(bubble);
    });

    buildWaveform();
    setWaveState("idle");
    setPlayButton(false);
    loadDurations();
    playerEl.hidden = false;
    loadSegment(0, false); // ready on line 1; the user presses play
    highlight(-1);         // don't scroll or highlight until playback starts
    updateNavButtons();
  }

  async function loadEpisode() {
    stopPlayback();
    transcriptEl.textContent = "";
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

  attachAudioEvents();
  initControls();
  loadEpisode();
})();
