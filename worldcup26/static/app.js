function renumberList(list) {
  list.querySelectorAll(".sortable-item").forEach((item, index) => {
    const badge = item.querySelector(".position-badge");
    if (badge) {
      badge.textContent = index + 1;
    }
  });
}

function getPredictionCard(form) {
  return form.matches("[data-card-state]") ? form : form.closest("[data-card-state]");
}

function getSectionContainer(node) {
  return node.closest("[data-section-state]");
}

function readFormState(form) {
  if (form.dataset.saveForm === "group") {
    return form.querySelector('input[name="team_order"]')?.value ?? "";
  }

  if (form.dataset.saveForm === "top-five") {
    return JSON.stringify(
      Array.from(form.querySelectorAll('select[name="team_ids"]')).map((select) => select.value),
    );
  }

  const home = form.querySelector('input[name="home"]')?.value.trim() ?? "";
  const away = form.querySelector('input[name="away"]')?.value.trim() ?? "";
  if (!home && !away) {
    return "";
  }
  return `${home}:${away}`;
}

function updatePredictionCardState(form) {
  const card = getPredictionCard(form);
  if (!card) {
    return;
  }

  const saved = form.dataset.savedState ?? "";
  const initial = form.dataset.initialState ?? "";
  const current = readFormState(form);
  const locked = card.dataset.locked === "true" || form.dataset.locked === "true";
  card.classList.remove("is-saved", "is-dirty", "is-missed");

  if (saved && current === saved) {
    card.classList.add("is-saved");
    return;
  }

  if (current !== initial) {
    card.classList.add("is-dirty");
    return;
  }

  if (locked) {
    card.classList.add("is-missed");
  }
}

function updateSectionState(node) {
  const section = getSectionContainer(node);
  if (!section) {
    return;
  }

  const cards = Array.from(section.querySelectorAll("[data-card-state]"));
  section.classList.remove("is-section-saved", "is-section-dirty", "is-section-missed");
  if (!cards.length) {
    return;
  }

  const allSaved = cards.every((card) => card.classList.contains("is-saved"));
  if (allSaved) {
    section.classList.add("is-section-saved");
    return;
  }

  if (cards.some((card) => card.classList.contains("is-dirty"))) {
    section.classList.add("is-section-dirty");
    return;
  }

  if (cards.some((card) => card.classList.contains("is-missed"))) {
    section.classList.add("is-section-missed");
  }
}

function bindSortableList(list) {
  if (list.dataset.locked === "true") {
    return;
  }

  let dragged = null;
  list.querySelectorAll(".sortable-item").forEach((item) => {
    item.addEventListener("dragstart", () => {
      dragged = item;
      item.classList.add("dragging");
    });

    item.addEventListener("dragend", () => {
      item.classList.remove("dragging");
      dragged = null;
      renumberList(list);
      const form = list.closest("form");
      const orderInput = form?.querySelector('input[name="team_order"]');
      const teamIds = Array.from(list.querySelectorAll(".sortable-item")).map((node) => node.dataset.teamId);
      if (orderInput) {
        orderInput.value = JSON.stringify(teamIds);
      }
      if (form) {
        updatePredictionCardState(form);
        updateSectionState(form);
      }
    });
  });

  list.addEventListener("dragover", (event) => {
    event.preventDefault();
    const target = event.target.closest(".sortable-item");
    if (!target || target === dragged) {
      return;
    }

    const items = Array.from(list.querySelectorAll(".sortable-item"));
    const targetIndex = items.indexOf(target);
    const draggedIndex = items.indexOf(dragged);
    if (draggedIndex < targetIndex) {
      target.after(dragged);
    } else {
      target.before(dragged);
    }
  });
}

function showToast(message, tone = "success") {
  const stack = document.getElementById("toast-stack");
  if (!stack || !message) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${tone}`;
  toast.textContent = message;
  stack.append(toast);

  requestAnimationFrame(() => {
    toast.classList.add("is-visible");
  });

  window.setTimeout(() => {
    toast.classList.remove("is-visible");
    window.setTimeout(() => {
      toast.remove();
    }, 220);
  }, 2400);
}

function roomStateKey() {
  return `room-ui:${window.location.pathname}`;
}

function scrollSectionIntoView(item) {
  const menuToggle = document.querySelector(".site-menu .menu-toggle");
  const topOffset = (menuToggle?.getBoundingClientRect().height || 0) + 32;
  const targetTop = window.scrollY + item.getBoundingClientRect().top - topOffset;
  window.scrollTo({
    top: Math.max(targetTop, 0),
    behavior: "smooth",
  });
}

function persistRoomState() {
  const items = Array.from(document.querySelectorAll("details[data-persist-id]"));
  if (!items.length) {
    return;
  }

  const payload = {
    openIds: items.filter((item) => item.open).map((item) => item.dataset.persistId),
    scrollY: window.scrollY,
  };
  window.sessionStorage.setItem(roomStateKey(), JSON.stringify(payload));
}

function restoreRoomState() {
  const navEntry = window.performance.getEntriesByType("navigation")[0];
  if (navEntry?.type !== "reload") {
    return;
  }

  const raw = window.sessionStorage.getItem(roomStateKey());
  if (!raw) {
    return;
  }

  try {
    const payload = JSON.parse(raw);
    const openIds = new Set(payload.openIds || []);
    document.querySelectorAll("details[data-persist-id]").forEach((item) => {
      item.open = openIds.has(item.dataset.persistId);
    });

    window.requestAnimationFrame(() => {
      window.scrollTo(0, payload.scrollY || 0);
    });
  } catch {
    window.sessionStorage.removeItem(roomStateKey());
  }
}

async function submitPredictionForm(form, submitButton) {
  const button = submitButton || form.querySelector('button[type="submit"]');
  const card = getPredictionCard(form);
  const originalLabel = button?.textContent;

  form.dataset.submitting = "true";
  if (card) {
    card.classList.add("is-saving");
  }
  if (button) {
    button.disabled = true;
    button.textContent = "Saving...";
  }

  try {
    const response = await fetch(form.action, {
      method: form.method || "POST",
      body: new FormData(form),
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    });

    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      showToast(payload?.message || "Could not save right now.", "error");
      return;
    }

    const savedState = readFormState(form);
    form.dataset.savedState = savedState;
    form.dataset.initialState = savedState;
    updatePredictionCardState(form);
    updateSectionState(form);
    persistRoomState();
    showToast(payload.message || "Saved.", "success");
  } catch {
    showToast("Could not save right now.", "error");
  } finally {
    delete form.dataset.submitting;
    if (card) {
      card.classList.remove("is-saving");
    }
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

function bindPredictionForm(form) {
  updatePredictionCardState(form);
  updateSectionState(form);

  if (form.dataset.saveForm === "match") {
    form.querySelectorAll('input[name="home"], input[name="away"]').forEach((input) => {
      input.addEventListener("input", () => {
        updatePredictionCardState(form);
        updateSectionState(form);
      });
    });
  }

  if (form.dataset.saveForm === "top-five") {
    form.querySelectorAll('select[name="team_ids"]').forEach((select) => {
      select.addEventListener("change", () => {
        updatePredictionCardState(form);
        updateSectionState(form);
      });
    });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (form.dataset.submitting === "true") {
      return;
    }
    submitPredictionForm(form, event.submitter);
  });
}

document.querySelectorAll("[data-sortable]").forEach(bindSortableList);

document.querySelectorAll("[data-open-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = document.getElementById(button.dataset.openDialog);
    if (dialog?.showModal) {
      dialog.showModal();
    }
  });
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest("dialog");
    dialog?.close();
  });
});

document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    const rect = dialog.getBoundingClientRect();
    const inside =
      rect.top <= event.clientY &&
      event.clientY <= rect.top + rect.height &&
      rect.left <= event.clientX &&
      event.clientX <= rect.left + rect.width;
    if (!inside) {
      dialog.close();
    }
  });
});

document.querySelectorAll("dialog[data-auto-open='true']").forEach((dialog) => {
  if (dialog.showModal) {
    dialog.showModal();
  }
});

document.querySelectorAll("[data-accordion]").forEach((container) => {
  const items = Array.from(container.children).filter((item) => item.tagName === "DETAILS");
  items.forEach((item) => {
    item.addEventListener("toggle", () => {
      if (!item.open) {
        persistRoomState();
        return;
      }
      items.forEach((other) => {
        if (other !== item) {
          other.open = false;
        }
      });
      window.requestAnimationFrame(() => {
        scrollSectionIntoView(item);
      });
      persistRoomState();
    });
  });
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) {
      return;
    }
    const text = "value" in target ? target.value : target.textContent;
    try {
      await navigator.clipboard.writeText(text);
      const original = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1400);
    } catch {
      if (target.select) {
        target.select();
      }
    }
  });
});

document.querySelectorAll("[data-menu-link]").forEach((link) => {
  link.addEventListener("click", () => {
    const menu = link.closest("[data-menu]");
    if (menu) {
      menu.open = false;
    }
  });
});

document.querySelectorAll("details[data-persist-id]").forEach((item) => {
  item.addEventListener("toggle", persistRoomState);
});

document.querySelectorAll("form[data-save-form]").forEach(bindPredictionForm);

document.querySelectorAll("[data-section-state]").forEach((section) => {
  updateSectionState(section);
});

window.addEventListener("beforeunload", persistRoomState);

restoreRoomState();
