"""Обновить статический рейтинг из сохранённых прогонов Сямыч Бенча."""
import argparse
import hashlib
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
parser.add_argument("--exclude-model", action="append", default=[], help="Оставить указанный прогон вне этой публикации")
options = parser.parse_args()

NAMES = {
    "gpt-6-astra": "GPT-6 Astra", "gpt-6.1-terra": "GPT-6.1 Terra",
    "gemini-4-hydrogen": "Gemini 4 Hydrogen",
    "gemini-4-carbon": "Gemini 4 Carbon", "kimi-k3.1-pro": "Kimi K3.1 Pro",
    "claude-opus-5.5": "Claude Opus 5.5", "claude-sonnet-5.5": "Claude Sonnet 5.5",
    "claude-fable-5.2": "Claude Fable 5.2",
    "qwen4-max-preview": "Qwen4-Max-Preview",
}
VENDORS = {"openai": ("OpenAI", "openai"), "google": ("Google", "googlegemini"),
           "qwen": ("Alibaba", "qwen"),
           "moonshotai": ("Moonshot AI", "moonshotai"), "anthropic": ("Anthropic", "anthropic")}
TASK_NAMES = {"пальцы": "Пальцы", "портрет": "Портрет", "заставка": "Заставка", "3d-сцена": "3D-город"}
HTML_TASKS = {"заставка": "intro.html", "3d-сцена": "city.html"}
# Правки только для просмотра. Хеш привязывает их к конкретному ответу модели.
CITY_FIXES = {
    "1ebd4c7431229faed9985ec2ece3f72a836e1f7f8edbda0a709ecfdd366b2496": (
        "Qwen получил 0/10. Оригинал зависает на загрузке. После правки опечатки здания перекрывают тёмные прямоугольники.",
        [(b"transparent:addive}", b"transparent:additive}")],
    ),
    "f03e3bbc7b9813fca6b943351b068e73868cf5ddce43ae1c40071ecbbf642d70": (
        "В оригинале Kimi сцена не запускается. В копии для просмотра исправлены опечатка в числе и параметры тумана.",
        [(b"mulberry32(0xC17Y)", b"mulberry32(0xC17A)"),
         (b"fog: true,\n  uniforms: { uTime: { value: 0 } }",
          b"fog: true,\n  uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, { uTime: { value: 0 } }])")],
    ),
    "afda289815004647aa00e64e7ff1aff4ba85b26ea993c5179fecbe25c6756598": (
        "В оригинале Sonnet шейдер асфальта выдаёт ошибку. В копии для просмотра исправлены координаты дорожной разметки.",
        [(b"fract(p.z/9.)", b"fract(p.y/9.)"), (b"fract(p.z/1.5)", b"fract(p.y/1.5)")],
    ),
}


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


def recorded_sum(entries, field):
    values = [r.get(field) for r in entries]
    return sum(values) if values and None not in values else None


def task_usage(entries):
    tokens_in = recorded_sum(entries, "tokens_in")
    tokens_out = recorded_sum(entries, "tokens_out")
    return {
        "runs": len(entries),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out if None not in (tokens_in, tokens_out) else None,
        "cost": recorded_sum(entries, "cost"),
        "estimated": any(r.get("cost_kind") in ("api_estimate", "hypothetical_release_price") or r.get("via") in ("claude-code", "codex-cli")
                         for r in entries),
    }


def format_tokens(value):
    return "—" if value is None else f"{value:,}".replace(",", " ")


def render_task(task, score, usage):
    grade = display(score, 0) if score is None or score == int(score) else display(score)
    repeat = f' <small>· прогонов {usage["runs"]}</small>' if usage["runs"] > 1 else ""
    price = "—"
    if usage["cost"] is not None:
        amount = display(usage["cost"], 7).rstrip("0").rstrip(",")
        prefix = "≈ " if usage["estimated"] else ""
        price = f"{prefix}${amount}"
    return f'''<div><dt>{TASK_NAMES[task]}{repeat}</dt><dd>
<strong class="task-score">{grade} <small>/ 10</small></strong>
<dl class="usage"><div><dt>Токены</dt><dd>{format_tokens(usage["tokens_total"])}</dd></div>
<div><dt>Вход</dt><dd>{format_tokens(usage["tokens_in"])}</dd></div>
<div><dt>Выход</dt><dd>{format_tokens(usage["tokens_out"])}</dd></div>
<div><dt>Цена API</dt><dd>{price}</dd></div></dl>
</dd></div>'''


def export_works(model, by_task, source_root):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", model) or any(s in (".", "..") for s in model.split("/")):
        raise ValueError(f"Некорректный идентификатор модели: {model}")
    folder = Path("works") / model
    works = {}
    targets = dict(HTML_TASKS)
    if model in {"qwen/qwen4-max-preview", "google/gemini-4-hydrogen"}:
        targets["портрет"] = "portrait.svg"
    for task, target in targets.items():
        # Терминальный бенчмарк открывает файл из последней записи задачи.
        if not by_task[task]:
            continue
        filename = by_task[task][-1]["file"]
        if Path(filename).suffix.lower() != Path(target).suffix:
            continue
        source_dir = source_root / task
        source = (source_dir / filename).resolve()
        if source.parent != source_dir.resolve():
            raise ValueError(f"Файл работы вне папки задачи: {filename}")
        (SITE / folder).mkdir(parents=True, exist_ok=True)
        dest = folder / target
        original = source.read_bytes()
        (SITE / dest).write_bytes(original)
        work = {"url": dest.as_posix()}
        fix = CITY_FIXES.get(hashlib.sha256(original).hexdigest())
        if fix and task == "3d-сцена":
            work["note"], replacements = fix
            fixed = original
            for old, new in replacements:
                if fixed.count(old) != 1:
                    raise ValueError(f"Фрагмент для правки не найден однозначно: {model}")
                fixed = fixed.replace(old, new, 1)
            fixed_dest = folder / "city-fixed.html"
            (SITE / fixed_dest).write_bytes(fixed)
            work["fixed_url"] = fixed_dest.as_posix()
        works[task] = work
    return works


def collect():
    core = read_core(options.bench)
    runs = {task: list(core.load(task)) for task in core.TASKS}
    scores = core.load_scores()
    known = {row["model"] for entries in runs.values() for row in entries}
    source_roots = {m: core.HERE / "out" for m in known}
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
            source_roots.update({m: path.parent for m in additions})
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
        if m in options.exclude_model:
            continue
        by_task = {t: [r for r in runs[t] if r["model"] == m] for t in core.TASKS}
        all_runs = [r for entries in by_task.values() for r in entries]
        tasks = {t: row["q"].get(t) if entries else None for t, entries in by_task.items()}
        complete = (all(v is not None for v in tasks.values()) and row["total"] is not None
                    and len(by_task["пальцы"]) >= core.FINGER_RUNS)
        models.append(dict(id=m, name=model_name(m), complete=complete, tasks=tasks,
                           task_usage={t: task_usage(entries) for t, entries in by_task.items()},
                           works=export_works(m, by_task, source_roots[m]),
                           quality=row["Q"], efficiency=row["Eall"], total=row["total"],
                           price=row["spent"] if all(r.get("cost") is not None for r in all_runs) else None,
                           calls=len(all_runs), seconds=sum(r["seconds"] for r in all_runs),
                           tokens_out=recorded_sum(all_runs, "tokens_out"), fingers=len(by_task["пальцы"]),
                           correct=sum(bool(r.get("correct")) for r in by_task["пальцы"]),
                           last=max(r["at"] for r in all_runs)[:10], duel=originals.get(m)))
        if all_runs[0].get("cost_kind") == "hypothetical_release_price":
            models[-1]["assumed_usd_per_million"] = all_runs[0]["usd_per_million"]
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
    rates = m.get("assumed_usd_per_million")
    if rates:
        price = f'<abbr title="Расчёт по предполагаемому тарифу">≈ {price}</abbr>'
    sub = escape(vendor) if m["complete"] else f'<span class="pending">{size}/4 тестов</span>'
    tasks = "\n".join(render_task(t, score, m["task_usage"][t]) for t, score in m["tasks"].items())
    links = []
    for task, work in m["works"].items():
        title = {"заставка": "Открыть заставку", "портрет": "Открыть портрет", "3d-сцена": "Открыть 3D-город"}[task]
        if "fixed_url" in work:
            title = "3D-город · оригинал с ошибкой"
        links.append((title, work["url"]))
        if "fixed_url" in work:
            links.append(("3D-город · после правки", work["fixed_url"]))
    work_links = "".join(f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{label} <span aria-hidden="true">↗</span></a>'
                         for label, url in links)
    if work_links:
        work_links = f'<div class="work-links">{work_links}</div>'
    work_notes = "".join(f'<p>{escape(work["note"])} Оценка выставлена за оригинал.</p>'
                         for work in m["works"].values() if "note" in work)
    notes = [f'Пальцы угаданы в {m["correct"]} из {m["fingers"]} ответов. Эффективность относительно Opus — {display(m["efficiency"])} из 10.']
    if m["id"] == "google/gemini-4-hydrogen":
        notes.append("Цена и время указаны по зачётным ответам. Отдельная платная попытка нарисовать портрет оборвалась и в сумму не входит.")
    if rates:
        notes.append(f'Прогон в веб-чате. Токены и время взяты из экспорта ответов. Для цены и итогового балла принят условный тариф ${rates["input"]} за миллион входных и ${rates["output"]} за миллион выходных токенов.')
    minutes, seconds = divmod(round(m["seconds"]), 60)
    tokens = format_tokens(m["tokens_out"])
    notes.append(f'За {m["calls"]} запросов суммарно — {minutes} мин {seconds} с и {tokens} выходных токенов.')
    if not m["complete"]:
        notes.append(f'Предварительный итог — {display(m["total"])}. Качество посчитано по выставленным оценкам, цена — по всем сохранённым ответам.')
    if m["duel"]:
        notes.append(f'В исходной дуэли с эталоном {escape(model_name(m["duel"]["reference"]))} итог составил {display(m["duel"]["total"])} из 100.')
    return f'''<tbody data-total="{m['total'] if m['total'] is not None else ''}" data-quality="{m['quality'] if m['quality'] is not None else ''}" data-price="{m['price'] if m['price'] is not None else ''}" data-complete="{str(m['complete']).lower()}" data-rank="{rank}">
<tr class="result-row">
<td class="rank">{f'{rank:02}' if m['complete'] else '—'}</td>
<th scope="row"><button class="model" type="button" aria-expanded="false" aria-controls="{key}" aria-label="Оценки и работы · {name}"><span class="logo {icon or ''}">{logo}</span><span class="model-text"><strong>{name}</strong><small>{sub}</small></span><span class="disclosure" aria-hidden="true">›</span></button></th>
<td class="score"><strong>{total}</strong><span class="meter" aria-hidden="true"><i style="width:{width:.3f}%"></i></span></td>
<td class="quality">{display(m['quality'], 2).rstrip('0').rstrip(',')}</td><td class="price">{price}</td>
</tr>
<tr class="detail" id="{key}" hidden><td colspan="5"><dl class="grades">{tasks}</dl>{work_links}{work_notes}<p>{' '.join(notes)}</p></td></tr>
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
