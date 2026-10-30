/* Mpira shared front-end helpers. Plain JS, no framework, no build step. */
(function () {
  "use strict";

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^|; )" + name + "=([^;]+)"));
    return m ? decodeURIComponent(m[2]) : null;
  }

  function toast(message, kind) {
    let host = document.querySelector(".toast-host");
    if (!host) {
      host = document.createElement("div");
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  /** JSON API call with CSRF; rejects with the API's error message. */
  async function api(url, options) {
    const opts = Object.assign({ method: "GET" }, options || {});
    opts.headers = Object.assign(
      { "Accept": "application/json", "X-CSRFToken": getCookie("csrftoken") || "" },
      opts.headers || {}
    );
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    opts.credentials = "same-origin";
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      const msg = (data && data.error && data.error.message) || res.statusText || "Request failed";
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  window.Mpira = { api, toast, getCookie };

  // Theme toggle (stored per browser).
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-theme-toggle]");
    if (!t) return;
    const root = document.documentElement;
    const current = root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("mpira-theme", next); } catch (err) { /* private mode */ }
  });

  // Dropdown menus.
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-menu-trigger]");
    document.querySelectorAll(".menu.open").forEach((m) => {
      if (!trigger || !m.contains(trigger)) m.classList.remove("open");
    });
    if (trigger) {
      e.preventDefault();
      trigger.closest(".menu").classList.toggle("open");
    }
  });

  // Mobile sidebar: the toggle opens it; a link, a tap on the dimmed page, or Escape closes it.
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-nav-toggle]")) {
      document.body.classList.toggle("nav-open");
      return;
    }
    if (!document.body.classList.contains("nav-open")) return;
    if (!e.target.closest(".sidebar") || e.target.closest(".sidebar a")) document.body.classList.remove("nav-open");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.body.classList.remove("nav-open");
  });

  // Confirm dialogs for destructive forms: <form data-confirm="...">
  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // <dialog> openers: <button data-open-dialog="id">
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-dialog]");
    if (opener) {
      const dlg = document.getElementById(opener.getAttribute("data-open-dialog"));
      if (dlg && dlg.showModal) dlg.showModal();
    }
    const closer = e.target.closest("[data-close-dialog]");
    if (closer) closer.closest("dialog").close();
  });

  // Markdown write/preview toggle for every <textarea data-markdown>.
  function setupMarkdown(textarea) {
    const previewUrl = document.body.getAttribute("data-md-preview-url");
    if (!previewUrl) return;
    const bar = document.createElement("div");
    bar.className = "md-toolbar";
    const writeBtn = document.createElement("button");
    writeBtn.type = "button";
    writeBtn.className = "btn btn-sm btn-ghost";
    writeBtn.textContent = document.body.getAttribute("data-i18n-write") || "Write";
    const prevBtn = writeBtn.cloneNode();
    prevBtn.textContent = document.body.getAttribute("data-i18n-preview") || "Preview";
    bar.append(writeBtn, prevBtn);
    const preview = document.createElement("div");
    preview.className = "md-preview prose hidden";
    textarea.parentNode.insertBefore(bar, textarea);
    textarea.parentNode.insertBefore(preview, textarea.nextSibling);
    prevBtn.addEventListener("click", async () => {
      preview.innerHTML = "…";
      preview.classList.remove("hidden");
      textarea.classList.add("hidden");
      try {
        const data = await api(previewUrl, { method: "POST", body: { text: textarea.value } });
        preview.innerHTML = data.html || "<p class='muted'>—</p>";
      } catch (err) {
        preview.textContent = err.message;
      }
    });
    writeBtn.addEventListener("click", () => {
      preview.classList.add("hidden");
      textarea.classList.remove("hidden");
      textarea.focus();
    });
  }
  document.querySelectorAll("textarea[data-markdown]").forEach(setupMarkdown);

  // Issue form: only show custom fields that apply to the selected type,
  // and the parent field only for sub-tasks.
  const typeSelect = document.querySelector("select[name='issue_type']");
  if (typeSelect) {
    const sync = () => {
      const type = typeSelect.value;
      document.querySelectorAll("[data-issue-type]").forEach((input) => {
        const applies = !input.dataset.issueType || input.dataset.issueType === type;
        const field = input.closest(".form-field");
        if (field) field.classList.toggle("hidden", !applies);
      });
      const parent = document.querySelector("[data-field='parent']");
      if (parent) parent.classList.toggle("hidden", type !== "subtask");
      const epic = document.querySelector("[data-field='epic']");
      if (epic) epic.classList.toggle("hidden", type === "epic");
    };
    typeSelect.addEventListener("change", sync);
    sync();
  }

  // Keyboard: "/" focuses global search.
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      const s = document.querySelector(".header-search input");
      if (s) { e.preventDefault(); s.focus(); }
    }
  });
})();

(function () {
  "use strict";

  // Command palette: Ctrl/⌘+K or the header button lists every page in the sidebar and account menu.
  const dlg = document.getElementById("palette");
  if (dlg && dlg.showModal) {
    const input = dlg.querySelector("[data-palette-input]");
    const list = dlg.querySelector("[data-palette-list]");
    const empty = dlg.querySelector("[data-palette-empty]");
    let pages = [];
    let issueHits = [];
    let shown = [];
    let active = 0;
    let seq = 0;
    let timer = null;

    // Issues whose title contains the text, in the project of the current page.
    function searchIssues(text) {
      const mine = ++seq;
      const el = document.querySelector(".project-head .muted");
      const key = el ? el.textContent.trim() : "";
      clearTimeout(timer);
      if (!key || text.length < 2) return;
      timer = setTimeout(async () => {
        try {
          const data = await Mpira.api("/api/v1/issues/?project=" + encodeURIComponent(key) + "&q=" + encodeURIComponent(text));
          if (mine !== seq) return;
          const rows = Array.isArray(data) ? data : (data.results || []);
          issueHits = rows.slice(0, 8).map((i) => ({
            href: "/projects/" + key + "/issues/" + i.number + "/", label: i.key + " " + i.title, glyph: "◆",
          }));
          render();
        } catch (err) {
          // Offline or refused: pages and key jumps still work.
        }
      }, 180);
    }

    function collect() {
      const seen = new Set();
      return [...document.querySelectorAll(".sidebar a.side-link, .menu-panel a")]
        .filter((a) => {
          const href = a.getAttribute("href");
          if (!href || href === "#" || seen.has(href)) return false;
          seen.add(href);
          return true;
        })
        .map((a) => {
          const copy = a.cloneNode(true);
          const icon = copy.querySelector(".ico");
          const glyph = icon ? icon.textContent.trim() : "";
          if (icon) icon.remove();
          return { href: a.getAttribute("href"), label: copy.textContent.trim(), glyph: glyph || "•" };
        });
    }

    function highlight() {
      [...list.children].forEach((li, i) => li.setAttribute("aria-selected", i === active ? "true" : "false"));
      if (list.children[active]) list.children[active].scrollIntoView({ block: "nearest" });
    }

    // "SPT-12" jumps straight to that issue, if SPT is one of the projects in the sidebar.
    function issueJump(text) {
      const m = text.match(/^([a-z][a-z0-9]*)-(\d+)$/i);
      if (!m) return null;
      const key = m[1].toUpperCase();
      const known = [...document.querySelectorAll(".sidebar a[href^='/projects/']")]
        .some((a) => a.getAttribute("href").startsWith("/projects/" + key + "/"));
      return known ? { href: "/projects/" + key + "/issues/" + m[2] + "/", label: key + "-" + m[2], glyph: "⌕" } : null;
    }

    function render() {
      const typed = input.value.trim();
      const q = typed.toLowerCase();
      const jump = issueJump(typed);
      shown = (jump ? [jump] : []).concat(issueHits, pages.filter((p) => !q || p.label.toLowerCase().includes(q)));
      active = Math.min(active, Math.max(shown.length - 1, 0));
      list.innerHTML = "";
      shown.forEach((p, i) => {
        const li = document.createElement("li");
        li.className = "palette-item";
        li.setAttribute("role", "option");
        const glyph = document.createElement("span");
        glyph.className = "ico";
        glyph.textContent = p.glyph;
        const label = document.createElement("span");
        label.textContent = p.label;
        li.append(glyph, label);
        li.addEventListener("mousemove", () => { active = i; highlight(); });
        li.addEventListener("click", () => { window.location.href = p.href; });
        list.appendChild(li);
      });
      empty.hidden = shown.length > 0;
      highlight();
    }

    function open() {
      pages = collect();
      input.value = "";
      issueHits = [];
      active = 0;
      render();
      dlg.showModal();
      input.focus();
    }

    input.addEventListener("input", () => {
      active = 0;
      issueHits = [];
      render();
      searchIssues(input.value.trim());
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        active = (active + step + shown.length) % Math.max(shown.length, 1);
        highlight();
      } else if (e.key === "Enter" && shown[active]) {
        e.preventDefault();
        window.location.href = shown[active].href;
      }
    });

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (dlg.open) dlg.close(); else open();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-palette-open]")) open();
    });
  }

  // Spotlight: the ring around cards and stat tiles follows the pointer.
  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest && e.target.closest(".card, .stat-tile");
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty("--mx", (e.clientX - box.left) + "px");
    el.style.setProperty("--my", (e.clientY - box.top) + "px");
  });
})();
