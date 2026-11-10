const table = document.querySelector("table");
const groups = Array.from(table.tBodies);
const controls = document.querySelector(".sort");
const status = document.querySelector("#sort-status");
const labels = { total: "итогу", quality: "качеству", price: "цене" };
let sortKey = "total";
let ascending = false;

function compare(a, b) {
  if (a.dataset.complete !== b.dataset.complete) {
    return a.dataset.complete === "true" ? -1 : 1;
  }
  const x = a.dataset[sortKey];
  const y = b.dataset[sortKey];
  if ((x === "") !== (y === "")) return x === "" ? 1 : -1;
  const difference = Number(x) - Number(y);
  return (ascending ? difference : -difference) || Number(a.dataset.rank) - Number(b.dataset.rank);
}

controls.addEventListener("click", event => {
  const selected = event.target.closest("button[data-sort]");
  if (!selected) return;
  const key = selected.dataset.sort;
  ascending = key === sortKey ? !ascending : key === "price";
  sortKey = key;
  groups.sort(compare);
  table.append(...groups);
  for (const button of controls.querySelectorAll("button")) {
    const active = button === selected;
    button.setAttribute("aria-pressed", String(active));
    button.querySelector(".sort-dir").textContent = active ? (ascending ? "↑" : "↓") : "";
  }
  for (const th of table.tHead.querySelectorAll("[data-column]")) {
    if (th.dataset.column === key) th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
  }
  status.textContent = `Сортировка по ${labels[key]}, по ${ascending ? "возрастанию" : "убыванию"}.`;
});

table.addEventListener("click", event => {
  const button = event.target.closest("button.model");
  if (!button) return;
  const details = document.getElementById(button.getAttribute("aria-controls"));
  details.hidden = !details.hidden;
  button.setAttribute("aria-expanded", String(!details.hidden));
});
