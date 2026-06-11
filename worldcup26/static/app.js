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
