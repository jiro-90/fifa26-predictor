function renumberList(list) {
  list.querySelectorAll(".sortable-item").forEach((item, index) => {
    const badge = item.querySelector(".position-badge");
    if (badge) {
      badge.textContent = index + 1;
    }
  });
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
      const orderInput = list.closest("form").querySelector('input[name="team_order"]');
      const teamIds = Array.from(list.querySelectorAll(".sortable-item")).map((node) => node.dataset.teamId);
      orderInput.value = JSON.stringify(teamIds);
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
  const items = Array.from(container.querySelectorAll("details"));
  items.forEach((item) => {
    item.addEventListener("toggle", () => {
      if (!item.open) {
        return;
      }
      items.forEach((other) => {
        if (other !== item) {
          other.open = false;
        }
      });
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
