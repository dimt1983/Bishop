"""File-tools для Claude tool-use. Дают Бишепу прямой доступ к исходникам
проекта (генераторы прайсов, шаблоны КП, каталоги) — чтобы Дмитрий мог
править их через переписку.

Только владелец. Жёстко ограничено корнем /root/projects/ai-agents-rb/.
.env, database и любые скрытые файлы (.git, .venv, __pycache__) запрещены.

Дополнительно:
  • Яндекс.Диск (yadisk_list / yadisk_fetch) — через rclone-remote `yadisk:`
    (настроен в /etc/rclone.conf, тот же что у dashboard sync).
  • PDF (pdf_extract_pages) — рендерит страницы как JPG через PyMuPDF.
"""
import json
import subprocess
from pathlib import Path

# Корни, в которые разрешён доступ. Всё остальное — запрет.
ALLOWED_ROOTS = [
    Path("/root/projects/ai-agents-rb").resolve(),
]

# Запрещённые имена/префиксы — даже если путь под allowed root.
DENY_NAMES = {".env", ".env.local", "bishop.db", "credentials.json"}
DENY_PREFIXES = (".env",)
DENY_DIR_PARTS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache"}

MAX_READ_BYTES = 200_000   # ~200KB достаточно для любого текстового скрипта
MAX_WRITE_BYTES = 500_000  # safety — не давать заливать гигантские файлы


# ─── Tool-определения ──────────────────────────────────────────────────────

_TOOL_LIST = {
    "name": "file_list",
    "description": (
        "Показать содержимое директории внутри проекта Roastberry "
        "(/root/projects/ai-agents-rb). Используй чтобы найти файл прежде чем читать "
        "или править. Возвращает список с пометкой 'd' для папок и размером для файлов."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Абсолютный путь под /root/projects/ai-agents-rb. По умолчанию — корень проекта.",
            },
        },
    },
}

_TOOL_READ = {
    "name": "file_read",
    "description": (
        "Прочитать содержимое текстового файла (Python, JSON, MD, TXT, CSV). "
        "Возвращает текст или ошибку если файл бинарный/слишком большой/запрещённый. "
        "Лимит 200КБ. Параметры offset/limit — для чтения по строкам, как в read."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Абсолютный путь к файлу"},
            "offset": {"type": "integer", "description": "С какой строки читать (1-indexed). По умолчанию 1."},
            "limit": {"type": "integer", "description": "Сколько строк читать. По умолчанию весь файл."},
        },
        "required": ["path"],
    },
}

_TOOL_EDIT = {
    "name": "file_edit",
    "description": (
        "Заменить точную строку (old_string) на новую (new_string) в файле. "
        "old_string должна встречаться РОВНО ОДИН РАЗ — иначе ошибка. "
        "Если нужно заменить ВСЕ вхождения — передай replace_all=true. "
        "Перед правкой ОБЯЗАТЕЛЬНО прочитай файл через file_read и согласуй изменения с пользователем. "
        "После сохранения файла предложи прогнать генератор (file_run для price_manager.py export или rental_offer.py)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Абсолютный путь к файлу"},
            "old_string": {"type": "string", "description": "Точная подстрока для замены (с учётом отступов)"},
            "new_string": {"type": "string", "description": "Новый текст"},
            "replace_all": {"type": "boolean", "description": "Заменить все вхождения. По умолчанию false (только если уникально)."},
        },
        "required": ["path", "old_string", "new_string"],
    },
}

_TOOL_WRITE = {
    "name": "file_write",
    "description": (
        "Создать новый файл или полностью перезаписать существующий. "
        "Используй ТОЛЬКО для новых файлов. Для правки существующего — file_edit. "
        "Запрещено для .env, бинарников, скрытых служебных файлов."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Абсолютный путь куда писать"},
            "content": {"type": "string", "description": "Новое содержимое файла"},
        },
        "required": ["path", "content"],
    },
}

_TOOL_RUN = {
    "name": "file_run",
    "description": (
        "Запустить разрешённый генератор/скрипт проекта. Доступно: "
        "'price_export' (price_manager.py export — пересобирает прайс/каталог/СТМ/дашборд), "
        "'rental_pdf' (rental_offer.py — пересобирает КП по аренде), "
        "'tea_catalog' (tea_catalog.py — каталог чая), "
        "'assortment_export' (assortment_manager.py export — прайсы чай/сиропы/прочее). "
        "Используй после file_edit чтобы изменения попали в чистовики."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "enum": ["price_export", "rental_pdf", "tea_catalog", "assortment_export"],
            },
        },
        "required": ["task"],
    },
}

_TOOL_YADISK_LIST = {
    "name": "yadisk_list",
    "description": (
        "Показать содержимое папки на Яндекс.Диске Roastberry. Используй "
        "чтобы найти нужный файл, прежде чем скачивать его через yadisk_fetch. "
        "Корень — папка 'Roastberry'. Поддерживает рекурсивный обход."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Путь относительно корня Я.Диска. Примеры: '' (корень), "
                    "'Roastberry', 'Roastberry/dashboard', 'Roastberry/photos/Borsch'. "
                    "По умолчанию — 'Roastberry'."
                ),
            },
            "recursive": {
                "type": "boolean",
                "description": "Показывать вложенные папки. По умолчанию false.",
            },
        },
    },
}

_TOOL_YADISK_FETCH = {
    "name": "yadisk_fetch",
    "description": (
        "Скачать файл с Яндекс.Диска в локальную рабочую папку "
        "/root/projects/ai-agents-rb/bishoprb-agent/workdir/. "
        "Возвращает абсолютный локальный путь — его можно передать в "
        "pdf_extract_pages, file_read и др. Лимит 50 МБ за раз."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "remote_path": {
                "type": "string",
                "description": (
                    "Путь на Я.Диске, например 'Roastberry/photos/Borsch/file.pdf'. "
                    "Должен быть файлом, не папкой."
                ),
            },
            "local_name": {
                "type": "string",
                "description": "Желаемое имя файла локально. По умолчанию — то же что в remote_path.",
            },
        },
        "required": ["remote_path"],
    },
}

_TOOL_PDF_EXTRACT = {
    "name": "pdf_extract_pages",
    "description": (
        "Отрендерить страницы PDF как JPG-картинки. Каждая страница → отдельный "
        "JPG. Используй когда пользователь просит вытащить картинки из PDF "
        "(карточки товаров, макеты упаковок и т.п.). Возвращает список путей "
        "к JPG-файлам в указанной папке."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "Локальный путь к PDF (после yadisk_fetch или из проекта).",
            },
            "output_dir": {
                "type": "string",
                "description": "Куда сложить JPG. Папка создаётся автоматически.",
            },
            "dpi": {
                "type": "integer",
                "description": "Разрешение рендера, DPI. По умолчанию 200.",
            },
        },
        "required": ["pdf_path", "output_dir"],
    },
}

TOOLS_OWNER = [
    _TOOL_LIST, _TOOL_READ, _TOOL_EDIT, _TOOL_WRITE, _TOOL_RUN,
    _TOOL_YADISK_LIST, _TOOL_YADISK_FETCH, _TOOL_PDF_EXTRACT,
]
TOOLS_READONLY: list[dict] = []  # Не даём не-владельцам никакого file-доступа.


# ─── Безопасность путей ─────────────────────────────────────────────────────

def _check_path(path_str: str, *, allow_create: bool = False) -> Path:
    """Резолвит путь и проверяет что он внутри ALLOWED_ROOTS, не в чёрном списке."""
    if not path_str:
        raise ValueError("Путь не задан")
    p = Path(path_str)
    if not p.is_absolute():
        raise ValueError(f"Путь должен быть абсолютным: {path_str}")
    # Резолвим символические ссылки и .. — для родителя если файла ещё нет
    target = p.resolve() if p.exists() else (p.parent.resolve() / p.name)

    if not any(_is_under(target, root) for root in ALLOWED_ROOTS):
        raise PermissionError(
            f"Доступ запрещён: путь {target} вне разрешённых корней"
        )

    if target.name in DENY_NAMES:
        raise PermissionError(f"Файл {target.name} в чёрном списке")
    for prefix in DENY_PREFIXES:
        if target.name.startswith(prefix):
            raise PermissionError(f"Префикс {prefix}* запрещён")
    for part in target.parts:
        if part in DENY_DIR_PARTS:
            raise PermissionError(f"Каталог {part}/ запрещён")

    if not allow_create and not target.exists():
        raise FileNotFoundError(f"Не найден: {target}")

    return target


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# ─── Executors ──────────────────────────────────────────────────────────────

def _t_list(inp: dict) -> str:
    raw = inp.get("path") or str(ALLOWED_ROOTS[0])
    target = _check_path(raw)
    if not target.is_dir():
        return json.dumps({"status": "error", "error": "это файл, не папка"}, ensure_ascii=False)

    items = []
    for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if entry.name.startswith(".") and entry.name not in {".gitignore"}:
            continue
        if entry.name in DENY_DIR_PARTS or entry.name in DENY_NAMES:
            continue
        if entry.is_dir():
            items.append(f"d  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
                items.append(f"   {entry.name}  ({_fmt_size(size)})")
            except OSError:
                items.append(f"   {entry.name}")
    body = "\n".join(items) if items else "(пусто)"
    return json.dumps({"status": "ok", "path": str(target), "items": body},
                      ensure_ascii=False)


def _fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b/1024:.1f} KB"
    return f"{b/1024/1024:.1f} MB"


def _t_read(inp: dict) -> str:
    target = _check_path(inp["path"])
    if not target.is_file():
        return json.dumps({"status": "error", "error": "не файл"}, ensure_ascii=False)

    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        return json.dumps(
            {"status": "error",
             "error": f"файл слишком большой ({_fmt_size(size)} > {_fmt_size(MAX_READ_BYTES)}), "
                      f"используй offset/limit"},
            ensure_ascii=False,
        )

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return json.dumps({"status": "error",
                           "error": "файл не текстовый (utf-8 декодирование упало)"},
                          ensure_ascii=False)

    lines = text.splitlines()
    offset = max(int(inp.get("offset") or 1), 1)
    limit = inp.get("limit")
    if limit is not None:
        end = offset - 1 + int(limit)
        sliced = lines[offset - 1:end]
    else:
        sliced = lines[offset - 1:]

    numbered = "\n".join(f"{i+offset:5d}\t{ln}" for i, ln in enumerate(sliced))
    return json.dumps({
        "status": "ok",
        "path": str(target),
        "total_lines": len(lines),
        "shown_lines": f"{offset}–{offset + len(sliced) - 1}" if sliced else "—",
        "content": numbered,
    }, ensure_ascii=False)


def _t_edit(inp: dict) -> str:
    target = _check_path(inp["path"])
    if not target.is_file():
        return json.dumps({"status": "error", "error": "не файл"}, ensure_ascii=False)

    old = inp["old_string"]
    new = inp["new_string"]
    replace_all = bool(inp.get("replace_all"))
    if old == new:
        return json.dumps({"status": "error", "error": "old_string == new_string"},
                          ensure_ascii=False)

    text = target.read_text(encoding="utf-8")
    occurrences = text.count(old)
    if occurrences == 0:
        return json.dumps({"status": "error", "error": "old_string не найден в файле"},
                          ensure_ascii=False)
    if occurrences > 1 and not replace_all:
        return json.dumps({
            "status": "error",
            "error": f"old_string встречается {occurrences} раз. "
                     f"Передай больше контекста или replace_all=true.",
        }, ensure_ascii=False)

    new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)

    if len(new_text.encode("utf-8")) > MAX_WRITE_BYTES:
        return json.dumps({"status": "error",
                           "error": f"итоговый файл > {_fmt_size(MAX_WRITE_BYTES)}"},
                          ensure_ascii=False)

    target.write_text(new_text, encoding="utf-8")
    return json.dumps({
        "status": "ok",
        "path": str(target),
        "replacements": occurrences if replace_all else 1,
        "size": _fmt_size(len(new_text.encode('utf-8'))),
    }, ensure_ascii=False)


def _t_write(inp: dict) -> str:
    target = _check_path(inp["path"], allow_create=True)
    content = inp.get("content") or ""
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return json.dumps({"status": "error",
                           "error": f"файл > {_fmt_size(MAX_WRITE_BYTES)}"},
                          ensure_ascii=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    return json.dumps({
        "status": "ok",
        "path": str(target),
        "action": "overwritten" if existed else "created",
        "size": _fmt_size(len(content.encode('utf-8'))),
    }, ensure_ascii=False)


# Разрешённые задачи запуска. Жёсткий enum — никакого произвольного shell.
_RUN_TASKS = {
    "price_export": {
        "cwd": "/root/projects/ai-agents-rb/Прайсы",
        "args": ["python3", "price_manager.py", "export"],
        "label": "Пересборка прайса/каталога/СТМ/дашборда",
    },
    "rental_pdf": {
        "cwd": "/root/projects/ai-agents-rb/Аренда",
        "args": ["python3", "rental_offer.py"],
        "label": "Пересборка КП по аренде",
    },
    "tea_catalog": {
        "cwd": "/root/projects/ai-agents-rb/Чай",
        "args": ["python3", "tea_catalog.py"],
        "label": "Пересборка каталога чая",
    },
    "assortment_export": {
        "cwd": "/root/projects/ai-agents-rb/Прайсы",
        "args": ["python3", "assortment_manager.py", "export"],
        "label": "Пересборка прайсов ассортимента",
    },
}

_VENV_PY = "/root/projects/ai-agents-rb/bishoprb-agent/.venv/bin/python"


def _t_run(inp: dict) -> str:
    task = inp.get("task")
    spec = _RUN_TASKS.get(task)
    if not spec:
        return json.dumps({"status": "error", "error": f"unknown task: {task}"},
                          ensure_ascii=False)

    args = list(spec["args"])
    if args and args[0] == "python3":
        args[0] = _VENV_PY  # запуск в нашем venv где есть reportlab/openpyxl

    try:
        result = subprocess.run(
            args, cwd=spec["cwd"], capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "error": "таймаут (120 сек)"},
                          ensure_ascii=False)

    out = (result.stdout or "")[-4000:]
    err = (result.stderr or "")[-2000:]
    return json.dumps({
        "status": "ok" if result.returncode == 0 else "error",
        "task": task,
        "label": spec["label"],
        "returncode": result.returncode,
        "stdout": out,
        "stderr": err if result.returncode != 0 else err[-500:],
    }, ensure_ascii=False)


# ─── Yandex.Disk через rclone ───────────────────────────────────────────────

YADISK_REMOTE = "yadisk"  # имя rclone-remote (см. /etc/rclone.conf)
YADISK_WORKDIR = Path("/root/projects/ai-agents-rb/bishoprb-agent/workdir")
YADISK_MAX_FETCH_BYTES = 50 * 1024 * 1024  # 50 MB


def _t_yadisk_list(inp: dict) -> str:
    raw = (inp.get("path") or "Roastberry").strip().lstrip("/")
    recursive = bool(inp.get("recursive"))
    # Формат "ps": path|size. Папки в rclone отмечены '/' в конце пути.
    cmd = ["rclone", "lsf", f"{YADISK_REMOTE}:{raw}",
           "--format", "ps", "--separator", "|"]
    if recursive:
        cmd.append("-R")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "error": "rclone таймаут (30 сек)"},
                          ensure_ascii=False)
    if r.returncode != 0:
        err = (r.stderr or "rclone error").strip()[:500]
        # Преобразуем «directory not found» в осмысленную ошибку с подсказкой,
        # чтобы Claude не перепутал её с «unknown tool».
        if "directory not found" in err.lower() or "object not found" in err.lower():
            return json.dumps({
                "status": "not_found",
                "error": f"Папки '{raw}' нет на Яндекс.Диске. Тул работает; путь — неверный.",
                "hint": "Вызови yadisk_list({'path':'Roastberry'}) чтобы посмотреть существующие папки.",
            }, ensure_ascii=False)
        return json.dumps({"status": "error", "error": err}, ensure_ascii=False)

    items = []
    for ln in r.stdout.splitlines():
        parts = ln.split("|", 1)
        if len(parts) < 2:
            continue
        name, size = parts
        if name.endswith("/"):
            items.append(f"d  {name}")
        else:
            try:
                items.append(f"   {name}  ({_fmt_size(int(size or 0))})")
            except ValueError:
                items.append(f"   {name}")
    body = "\n".join(items[:200]) if items else "(пусто)"
    truncated = len(items) > 200
    return json.dumps({
        "status": "ok",
        "path": raw or "(root)",
        "items": body,
        "count": len(items),
        "truncated": truncated,
    }, ensure_ascii=False)


def _yadisk_path_variants(path: str) -> list[str]:
    """Я.Диск может хранить кириллические имена в decomposed форме (NFD),
    а Claude отдаёт обычно NFC. Пробуем несколько нормализаций."""
    import unicodedata
    seen, out = set(), []
    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        v = unicodedata.normalize(form, path)
        if v not in seen:
            seen.add(v); out.append(v)
    return out


def _t_yadisk_fetch(inp: dict) -> str:
    remote_path = (inp.get("remote_path") or "").strip().lstrip("/")
    if not remote_path:
        return json.dumps({"status": "error", "error": "remote_path не задан"},
                          ensure_ascii=False)
    if remote_path.endswith("/"):
        return json.dumps({"status": "error",
                           "error": "это папка, а не файл — используй yadisk_list"},
                          ensure_ascii=False)

    YADISK_WORKDIR.mkdir(parents=True, exist_ok=True)
    local_name = (inp.get("local_name") or Path(remote_path).name).strip()
    local_name = Path(local_name).name  # анти-traversal
    if not local_name:
        return json.dumps({"status": "error", "error": "пустое local_name"},
                          ensure_ascii=False)
    dest = (YADISK_WORKDIR / local_name).resolve()
    if not _is_under(dest, YADISK_WORKDIR):
        return json.dumps({"status": "error", "error": "недопустимое имя файла"},
                          ensure_ascii=False)

    # Перебираем NFC/NFD варианты: Я.Диск иногда хранит кириллицу в decomposed-форме
    last_err = ""
    for variant in _yadisk_path_variants(remote_path):
        # Размер
        try:
            r = subprocess.run(
                ["rclone", "size", f"{YADISK_REMOTE}:{variant}", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                sz = json.loads(r.stdout).get("bytes", 0)
                if sz > YADISK_MAX_FETCH_BYTES:
                    return json.dumps({
                        "status": "error",
                        "error": f"файл {_fmt_size(sz)} > лимит {_fmt_size(YADISK_MAX_FETCH_BYTES)}",
                    }, ensure_ascii=False)
        except Exception:
            pass

        try:
            r = subprocess.run(
                ["rclone", "copyto", f"{YADISK_REMOTE}:{variant}", str(dest), "-q"],
                capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "rclone copy таймаут (180 сек)"},
                              ensure_ascii=False)
        if r.returncode == 0 and dest.exists():
            return json.dumps({
                "status": "ok",
                "remote_path": remote_path,
                "local_path": str(dest),
                "size": _fmt_size(dest.stat().st_size),
            }, ensure_ascii=False)
        last_err = (r.stderr or "rclone copy fail").strip()[:300]

    return json.dumps({
        "status": "error",
        "error": f"не удалось скачать ни в одной нормализации (NFC/NFD): {last_err}",
    }, ensure_ascii=False)


def _t_pdf_extract(inp: dict) -> str:
    pdf_path = inp.get("pdf_path") or ""
    if not pdf_path:
        return json.dumps({"status": "error", "error": "pdf_path не задан"},
                          ensure_ascii=False)
    pdf = Path(pdf_path).resolve()
    # PDF должен лежать в проекте или в workdir
    valid = (
        any(_is_under(pdf, root) for root in ALLOWED_ROOTS)
        or _is_under(pdf, YADISK_WORKDIR.resolve())
    )
    if not valid:
        return json.dumps({"status": "error",
                           "error": f"PDF вне разрешённых корней: {pdf}"},
                          ensure_ascii=False)
    if not pdf.is_file():
        return json.dumps({"status": "error", "error": f"не найден: {pdf}"},
                          ensure_ascii=False)

    out_raw = inp.get("output_dir") or ""
    if not out_raw:
        return json.dumps({"status": "error", "error": "output_dir не задан"},
                          ensure_ascii=False)
    out = Path(out_raw)
    if not out.is_absolute():
        return json.dumps({"status": "error", "error": "output_dir должен быть абсолютным"},
                          ensure_ascii=False)
    out_resolved = out.resolve() if out.exists() else (out.parent.resolve() / out.name)
    if not any(_is_under(out_resolved, root) for root in ALLOWED_ROOTS):
        return json.dumps({"status": "error",
                           "error": "output_dir должен быть под /root/projects/ai-agents-rb/"},
                          ensure_ascii=False)
    out.mkdir(parents=True, exist_ok=True)
    dpi = int(inp.get("dpi") or 200)
    if dpi < 72: dpi = 72
    if dpi > 600: dpi = 600

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return json.dumps({"status": "error",
                           "error": "PyMuPDF не установлен — pip install PyMuPDF"},
                          ensure_ascii=False)

    try:
        doc = fitz.open(str(pdf))
    except Exception as e:
        return json.dumps({"status": "error", "error": f"не удалось открыть PDF: {e}"},
                          ensure_ascii=False)

    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        stem = pdf.stem
        files = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            name = f"{stem}_p{i+1}.jpg" if len(doc) > 1 else f"{stem}.jpg"
            dest = out / name
            pix.save(str(dest), jpg_quality=90)
            files.append({"path": str(dest), "size": _fmt_size(dest.stat().st_size),
                          "page": i + 1, "dimensions": f"{pix.width}x{pix.height}"})
    finally:
        doc.close()

    return json.dumps({
        "status": "ok",
        "pdf": str(pdf),
        "output_dir": str(out),
        "dpi": dpi,
        "pages": len(files),
        "files": files,
    }, ensure_ascii=False)


# ─── Dispatcher ─────────────────────────────────────────────────────────────

_DISPATCH = {
    "file_list": _t_list,
    "file_read": _t_read,
    "file_edit": _t_edit,
    "file_write": _t_write,
    "file_run": _t_run,
    "yadisk_list": _t_yadisk_list,
    "yadisk_fetch": _t_yadisk_fetch,
    "pdf_extract_pages": _t_pdf_extract,
}

# Публичный set имён, чтобы внешний диспетчер (claude_service) знал,
# какие тулы маршрутизировать в этот модуль.
TOOL_NAMES = frozenset(_DISPATCH.keys())


def execute_tool(name: str, inp: dict) -> str:
    handler = _DISPATCH.get(name)
    if handler is None:
        return json.dumps({"status": "error", "error": f"unknown tool: {name}"},
                          ensure_ascii=False)
    try:
        return handler(inp)
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)
