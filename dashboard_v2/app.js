// Starter for a new UI. Same rules as the built-in dashboard: no CDN, no inline script (CSP script-src 'self'),
// and render every data field with textContent (PI8), never innerHTML.
"use strict";

document.addEventListener("DOMContentLoaded", async () => {
  const ul = document.getElementById("scenarios");
  const r = await fetch("/scenarios");
  const body = await r.json();
  for (const s of body.scenarios) {
    const li = document.createElement("li");
    li.textContent = s.name;
    ul.appendChild(li);
  }
});
