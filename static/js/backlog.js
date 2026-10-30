/*
 * Backlog / sprint planning drag & drop: move issues between the backlog and
 * sprints, and reorder by rank. Server: POST /api/v1/.../move/ {sprint, before, after}.
 */
(function () {
  "use strict";
  const root = document.querySelector("[data-backlog]");
  if (!root || root.dataset.canEdit !== "1") return;
  const moveUrlTpl = root.dataset.moveUrl;
  let dragged = null;

  function rowAfter(container, y) {
    const rows = [...container.querySelectorAll(".issue-row:not(.dragging)")];
    let closest = { offset: -Infinity, el: null };
    for (const r of rows) {
      const box = r.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) closest = { offset, el: r };
    }
    return closest.el;
  }

  function refreshTotals() {
    root.querySelectorAll(".issue-rows").forEach((list) => {
      const rows = list.querySelectorAll(".issue-row");
      const pts = [...rows].reduce((s, r) => s + (parseInt(r.dataset.points, 10) || 0), 0);
      const box = list.closest("[data-list]");
      const c = box.querySelector("[data-count]");
      const p = box.querySelector("[data-points]");
      if (c) c.textContent = rows.length;
      if (p) p.textContent = pts;
      const hint = list.querySelector(".empty-hint");
      if (hint) hint.classList.toggle("hidden", rows.length > 0);
    });
  }

  root.querySelectorAll(".issue-row").forEach((row) => {
    row.setAttribute("draggable", "true");
    row.addEventListener("dragstart", (e) => {
      dragged = row;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", row.dataset.number);
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      root.querySelectorAll(".issue-rows").forEach((l) => l.classList.remove("drop-ok"));
      dragged = null;
    });
  });

  root.querySelectorAll(".issue-rows").forEach((list) => {
    list.addEventListener("dragover", (e) => {
      if (!dragged) return;
      e.preventDefault();
      list.classList.add("drop-ok");
      const after = rowAfter(list, e.clientY);
      if (after) list.insertBefore(dragged, after);
      else list.appendChild(dragged);
    });
    list.addEventListener("dragleave", (e) => {
      if (!list.contains(e.relatedTarget)) list.classList.remove("drop-ok");
    });
    list.addEventListener("drop", async (e) => {
      e.preventDefault();
      if (!dragged) return;
      const row = dragged;
      const prev = row.previousElementSibling && row.previousElementSibling.classList.contains("issue-row") ? row.previousElementSibling : null;
      const next = row.nextElementSibling && row.nextElementSibling.classList.contains("issue-row") ? row.nextElementSibling : null;
      const sprint = list.dataset.sprint ? parseInt(list.dataset.sprint, 10) : null;
      refreshTotals();
      try {
        await Mpira.api(moveUrlTpl.replace("/0/", "/" + row.dataset.number + "/"), {
          method: "POST",
          body: {
            sprint: sprint,
            before: prev ? parseInt(prev.dataset.number, 10) : null,
            after: next ? parseInt(next.dataset.number, 10) : null,
          },
        });
      } catch (err) {
        Mpira.toast(err.message, "error");
        setTimeout(() => window.location.reload(), 900);
      }
    });
  });
})();
