"""Обновить статический рейтинг из сохранённых прогонов Сямыч Бенча."""
import argparse
import importlib.util
import json
import re
from html import escape
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
LIFE = SITE.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bench", type=Path, default=LIFE / "youtube/Ресерч/model-duel")
parser.add_argument("--duels", type=Path, default=LIFE / "шоу/сямыч-бенч-дуэль")
options = parser.parse_args()

NAMES = {
    "gpt-6-astra": "GPT-6 Astra", "gpt-6.1-terra": "GPT-6.1 Terra",
    "gemini-4-carbon": "Gemini 4 Carbon", "kimi-k3.1-pro": "Kimi K3.1 Pro",
    "claude-opus-5.5": "Claude Opus 5.5", "claude-sonnet-5.5": "Claude Sonnet 5.5",
    "claude-fable-5.2": "Claude Fable 5.2",
}
VENDORS = {"openai": ("OpenAI", "openai"), "google": ("Google", "googlegemini"),
           "moonshotai": ("Moonshot AI", "moonshotai"), "anthropic": ("Anthropic", "anthropic")}
TASK_NAMES = {"пальцы": "Пальцы", "портрет": "Портрет", "заставка": "Заставка", "3d-сцена": "3D-город"}


def read_core(folder):
    spec = importlib.util.spec_from_file_location("bench_core", folder.resolve() / "core.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_name(model):
    slug = model.split("/")[-1]
    return NAMES.get(slug, slug)


def display(value, digits=1):
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def collect():
    core = read_core(options.bench)
    runs = {task: list(core.load(task)) for task in core.TASKS}
    scores = core.load_scores()
    known = {row["model"] for entries in runs.values() for row in entries}
    if core.BASE not in known:
        raise ValueError("В основной серии нет эталонной модели")
    originals = {}
    if options.duels.is_dir():
        duel = read_core(options.duels)
        for path in sorted((options.duels / "out").glob("*/оценки.json")):
            duel.PAIR_DIR = path.parent.name
            first, _ = duel.PAIR_DIR.split(" vs ", 1)
            measurements = {t: duel.load(t) for t in core.TASKS}
            models = {r["model"] for rows in measurements.values() for r in rows}
            duel.BASE = next(m for m in models if duel.short(m) == first)
            official, _ = duel.compute()
            additions = models - known
            for row in official:
                if row["model"] in additions:
                    originals[row["model"]] = {"reference": duel.BASE, "total": row["total"]}
            for task, rows in measurements.items():
                runs[task].extend(r for r in rows if r["model"] in additions)
            for task, grades in duel.load_scores().items():
                scores.setdefault(task, {}).update({m: v for m, v in grades.items() if m in additions})
            known.update(additions)

    # Та же compute(), что в TUI. Подставляем объединённый набор сохранённых измерений.
    core.load = lambda task, demo=False: runs[task]
    core.load_scores = lambda demo=False: scores
    unified, _ = core.compute()
    models = []
    for row in unified:
        m = row["model"]
        by_task = {t: [r for r in runs[t] if r["model"] == m] for t in core.TASKS}
        all_runs = [r for entries in by_task.values() for r in entries]
        tasks = {t: row["q"].get(t) if entries else None for t, entries in by_task.items()}
        complete = (all(v is not None for v in tasks.values()) and row["total"] is not None
                    and len(by_task["пальцы"]) >= core.FINGER_RUNS)
        models.append(dict(id=m, name=model_name(m), complete=complete, tasks=tasks,
                           quality=row["Q"], efficiency=row["Eall"], total=row["total"],
                           price=row["spent"] if all(r.get("cost") is not None for r in all_runs) else None,
                           calls=len(all_runs), seconds=sum(r["seconds"] for r in all_runs),
                           tokens_out=sum(r["tokens_out"] for r in all_runs), fingers=len(by_task["пальцы"]),
                           correct=sum(bool(r.get("correct")) for r in by_task["пальцы"]),
                           last=max(r["at"] for r in all_runs)[:10], duel=originals.get(m)))
    return sorted(models, key=lambda m: (not m["complete"], -(m["total"] or 0), m["id"]))


def render_model(model, rank):
    m = model
    name = escape(m["name"])
    vendor, icon = VENDORS.get(m["id"].split("/")[0], (m["id"].split("/")[0], None))
    logo = f'<img class="vendor-icon" src="assets/icons/{icon}.svg" alt="">' if icon else ""
    key = escape(m["id"].replace("/", "-"), quote=True)
    size = sum(v is not None for v in m["tasks"].values())
    total = display(m["total"]) if m["complete"] else "—"
    width = (m["total"] or 0) if m["complete"] else 0
    price = "—" if m["price"] is None else "$" + display(m["price"], 2)
    sub = escape(vendor) if m["complete"] else f'<span class="pending">{size}/4 тестов</span>'
    tasks = "".join(f'<div><dt>{TASK_NAMES[t]}</dt><dd>{display(v, 0) if v is None or v == int(v) else display(v)}</dd></div>'
                    for t, v in m["tasks"].items())
    notes = [f'Пальцы угаданы в {m["correct"]} из {m["fingers"]} ответов. Эффективность относительно Opus — {display(m["efficiency"])} из 10.']
    minutes, seconds = divmod(round(m["seconds"]), 60)
    tokens = f"{m['tokens_out']:,}".replace(",", " ")
    notes.append(f'За {m["calls"]} запросов суммарно — {minutes} мин {seconds} с и {tokens} выходных токенов.')
    if not m["complete"]:
        notes.append(f'Предварительный итог — {display(m["total"])}. Качество посчитано по выставленным оценкам, цена — по всем сохранённым ответам.')
    if m["duel"]:
        notes.append(f'В исходной дуэли с эталоном {escape(model_name(m["duel"]["reference"]))} итог составил {display(m["duel"]["total"])} из 100.')
    return f'''<tbody data-total="{m['total'] if m['total'] is not None else ''}" data-quality="{m['quality'] if m['quality'] is not None else ''}" data-price="{m['price'] if m['price'] is not None else ''}" data-complete="{str(m['complete']).lower()}" data-rank="{rank}">
<tr class="result-row">
<td class="rank">{f'{rank:02}' if m['complete'] else '—'}</td>
<th scope="row"><button class="model" type="button" aria-expanded="false" aria-controls="{key}" aria-label="Оценки по задачам · {name}"><span class="logo {icon or ''}">{logo}</span><span class="model-text"><strong>{name}</strong><small>{sub}</small></span><span class="disclosure" aria-hidden="true">›</span></button></th>
<td class="score"><strong>{total}</strong><span class="meter" aria-hidden="true"><i style="width:{width:.3f}%"></i></span></td>
<td class="quality">{display(m['quality'], 2).rstrip('0').rstrip(',')}</td><td class="price">{price}</td>
</tr>
<tr class="detail" id="{key}" hidden><td colspan="5"><dl class="grades">{tasks}</dl><p>{' '.join(notes)}</p></td></tr>
</tbody>'''


def main():
    models = collect()
    updated = max(m["last"] for m in models)
    table = "\n".join(render_model(m, rank) for rank, m in enumerate(models, 1))
    index = SITE / "index.html"
    page = index.read_text()
    start, end = "<!-- results:start -->", "<!-- results:end -->"
    a, tail = page.split(start)
    _, b = tail.split(end)
    page = a + start + "\n" + table + "\n" + end + b
    year, month, day = updated.split("-")
    page = re.sub(r'<time id="updated"[^<]*</time>', f'<time id="updated" datetime="{updated}">{day}.{month}.{year}</time>', page)
    count = str(len(models))
    page = re.sub(r'(<b id="model-count">)\d+', lambda match: match[1] + count, page)
    data = {"updated": updated, "reference": "anthropic/claude-opus-5.5", "models": models}
    (SITE / "data/results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    index.write_text(page)
    for m in models:
        print(m["name"], display(m["total"]), "в зачёте" if m["complete"] else "в процессе")


if __name__ == "__main__":
    main()
