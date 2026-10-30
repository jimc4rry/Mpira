/*
 * Kanban board drag & drop (HTML5 DnD). Only workflow-legal target columns
 * accept a drop; the server re-validates via POST /api/v1/.../move/.
 * A page can hold several boards (one per swimlane); each one works on its own,
 * and the quick filters apply to all of them.
 */
(function () {
  "use strict";
  const boards = [...document.querySelectorAll("[data-board]")];
  if (!boards.length) return;
  const transitions = JSON.parse(document.getElementById("board-transitions").textContent);
  const q = document.getElementById("board-filter-q");
  const who = document.getElementById("board-filter-assignee");
  const type = document.getElementById("board-filter-type");
  const touch = window.matchMedia("(pointer: coarse)").matches;

  function cardAfter(container, y) {
    const cards = [...container.querySelectorAll(".card-issue:not(.dragging)")];
    let closest = { offset: -Infinity, el: null };
    for (const c of cards) {
      const box = c.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) closest = { offset, el: c };
    }
    return closest.el;
  }

  function updateCounts(board) {
    board.querySelectorAll(".board-col").forEach((col) => {
      const cards = col.querySelectorAll(".card-issue:not(.filtered-out)");
      const pts = [...cards].reduce((s, c) => s + (parseInt(c.dataset.points, 10) || 0), 0);
      col.querySelector("[data-count]").textContent = cards.length;
      col.querySelector("[data-points]").textContent = pts;
    });
  }

  function setupDragAndDrop(board) {
    const moveUrlTpl = board.dataset.moveUrl; // contains /0/ placeholder for the issue number
    let dragged = null;
    let fromStatus = null;
    const moveUrl = (number) => moveUrlTpl.replace("/0/", "/" + number + "/");

    board.querySelectorAll(".card-issue").forEach((card) => {
      card.setAttribute("draggable", "true");
      card.addEventListener("dragstart", (e) => {
        dragged = card;
        // The card's real workflow status - its column may hold several statuses.
        fromStatus = card.dataset.status;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.dataset.number);
        const allowed = transitions[fromStatus] || [];
        board.querySelectorAll(".board-col-body").forEach((b) => {
          const st = b.dataset.status;
          // Empty columns have no target status, so they never accept a drop.
          if (!st || (st !== fromStatus && !allowed.includes(st))) b.classList.add("drop-no");
        });
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("dragging");
        board.querySelectorAll(".board-col-body").forEach((b) => b.classList.remove("drop-ok", "drop-no"));
        dragged = null;
      });
    });

    board.querySelectorAll(".board-col-body").forEach((body) => {
      body.addEventListener("dragover", (e) => {
        if (!dragged || body.classList.contains("drop-no")) return;
        e.preventDefault();
        body.classList.add("drop-ok");
        const after = cardAfter(body, e.clientY);
        if (after) body.insertBefore(dragged, after);
        else body.appendChild(dragged);
      });
      body.addEventListener("dragleave", (e) => {
        if (!body.contains(e.relatedTarget)) body.classList.remove("drop-ok");
      });
      body.addEventListener("drop", async (e) => {
        e.preventDefault();
        if (!dragged || body.classList.contains("drop-no")) return;
        const card = dragged;
        const toStatus = body.dataset.status;
        const prev = card.previousElementSibling && card.previousElementSibling.classList.contains("card-issue") ? card.previousElementSibling : null;
        const next = card.nextElementSibling && card.nextElementSibling.classList.contains("card-issue") ? card.nextElementSibling : null;
        const payload = {
          before: prev ? parseInt(prev.dataset.number, 10) : null,
          after: next ? parseInt(next.dataset.number, 10) : null,
        };
        if (toStatus !== fromStatus) payload.status = toStatus;
        updateCounts(board);
        try {
          await Mpira.api(moveUrl(card.dataset.number), { method: "POST", body: payload });
        } catch (err) {
          Mpira.toast(err.message, "error");
          setTimeout(() => window.location.reload(), 900);
        }
      });
    });
  }

  // Phones have no HTML5 drag and drop: each card gets a status picker with the allowed moves instead.
  function setupTouchMove(board) {
    const moveUrlTpl = board.dataset.moveUrl;
    const moveUrl = (number) => moveUrlTpl.replace("/0/", "/" + number + "/");
    const labels = {};
    board.querySelectorAll(".board-col").forEach((col) => {
      const body = col.querySelector(".board-col-body");
      const head = col.querySelector(".board-col-head > span");
      if (body && head && head.firstChild) labels[body.dataset.status] = head.firstChild.textContent.trim();
    });
    board.querySelectorAll(".card-issue").forEach((card) => {
      const status = card.dataset.status;
      const picker = document.createElement("select");
      picker.className = "card-move";
      [status, ...(transitions[status] || [])].forEach((s) => picker.add(new Option(labels[s] || s, s, false, s === status)));
      picker.addEventListener("change", async () => {
        if (picker.value === status) return;
        try {
          await Mpira.api(moveUrl(card.dataset.number), { method: "POST", body: { status: picker.value } });
          window.location.reload();
        } catch (err) {
          Mpira.toast(err.message, "error");
          picker.value = status;
        }
      });
      card.appendChild(picker);
    });
  }

  // Assignee picker on each card: saved at once, through the same endpoint as the list's inline edit.
  document.addEventListener("change", async (e) => {
    const picker = e.target.closest && e.target.closest("select.card-assignee");
    if (!picker) return;
    const card = picker.closest(".card-issue");
    const body = new URLSearchParams({ field: picker.dataset.field, value: picker.value });
    try {
      const res = await fetch(picker.dataset.url, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-CSRFToken": Mpira.getCookie("csrftoken") || "" },
      });
      if (!res.ok) throw new Error("refused");
      card.dataset.assignee = picker.value === "none" ? "" : picker.value;
      applyFilters();
    } catch (err) {
      window.location.reload();
    }
  });

  if (boards.some((b) => b.dataset.canEdit === "1")) {
    boards.forEach((board) => {
      if (board.dataset.canEdit !== "1") return;
      if (touch) setupTouchMove(board);
      else setupDragAndDrop(board);
    });
  }

  // Quick filters (client-side): text, assignee, type. They apply to every swimlane.
  function applyFilters() {
    const text = (q && q.value || "").toLowerCase();
    const a = who && who.value;
    const t = type && type.value;
    boards.forEach((board) => {
      board.querySelectorAll(".card-issue").forEach((c) => {
        const match =
          (!text || c.dataset.search.includes(text)) &&
          (!a || (a === "none" ? !c.dataset.assignee : c.dataset.assignee === a)) &&
          (!t || c.dataset.type === t);
        c.classList.toggle("hidden", !match);
        c.classList.toggle("filtered-out", !match);
      });
      updateCounts(board);
    });
  }
  [q, who, type].forEach((el) => el && el.addEventListener("input", applyFilters));
})();
