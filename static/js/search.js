// Home page logic: server health check + send the topic to the news results page.
(function () {
  "use strict";

  const form = document.getElementById("search-form");
  const input = document.getElementById("topic-input");
  const statusEl = document.getElementById("status");
  const healthEl = document.getElementById("health");

  async function checkHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      if (data.status === "ok") {
        healthEl.textContent = "Server status: ok";
        healthEl.classList.add("ok");
        return;
      }
      throw new Error("bad status");
    } catch (err) {
      healthEl.textContent = "Server status: unreachable";
      healthEl.classList.add("error");
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const topic = input.value.trim();
    if (!topic) {
      statusEl.textContent = "Please enter a topic.";
      return;
    }
    window.location.href = "/news?q=" + encodeURIComponent(topic);
  });

  checkHealth();
})();