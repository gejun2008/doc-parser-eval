"""
导出 ocr-benchmark-dataset 仓库的结构清单（只导结构，不导内容）

在公司电脑上、数据集仓库根目录运行：
  python dataset_inventory.py                 # 输出 inventory-for-photo.md
  python dataset_inventory.py --no-hash       # 跳过 sha256 重算（最慢的一步）
  python dataset_inventory.py --no-network    # 跳过联网探测

只读：不改任何文件，只新建输出文件。只依赖标准库；装了 PyYAML 才会解析 YAML 类 GT。

输出只含：目录名、文件名规律、计数、字段名、类型、短枚举标签、哈希比对结果。
不输出：正文、GT 值、绝对路径、用户名、主机名。枚举值的过滤规则见 enum_ok()。
这是启发式脚本：它不知道数据集的确切格式，看不懂的结构会照实写「未识别」，不猜。
"""
import argparse
import csv
import hashlib
import json
import platform
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT_DIRS = ["data", "gt", "metadata"]
ENUM_MAX = 15
ENUM_VAL_MAXLEN = 40
# 这些列名的值可能是正文、GT 值或路径，即使取值少也不列出
NO_ENUM = re.compile(r"path|url|sha|hash|md5|title|text|content|target|value|note|comment|"
                     r"label|anchor|answer|expected|name|desc|source|file|^id$|_id$", re.I)
# 可能与难度 / 选页相关的列名，单独点名
SELECT_HINT = re.compile(r"diffic|hard|easy|level|tier|opus|llm|claude|gpt|model|select|pick|"
                         r"score|rank|reason|strat|bucket", re.I)
# GT 里只有这些键名的取值允许列出（白名单）。上游 GT 的其他键（text、cell、before…）是正文
GT_ENUM_ALLOW = re.compile(r"^(type|status|tier|category|categories|dimension|kind|severity|eval_on|"
                           r"rule|rule_type|subset|variant|family|window|split|difficulty|level|"
                           r"tag|tags|mode|checked|test_type|source_type)$", re.I)
REF_KEYS = {"doc_id", "pdf", "file", "local_path", "source_pdf", "image", "page_id", "path"}
TABLE_EXT = {".csv", ".tsv"}
STRUCT_EXT = {".json", ".jsonl", ".yaml", ".yml"}

out_lines = []


def w(s=""):
    out_lines.append(s)


def table(header, rows, checksum=True):
    """rows 里的 int 计入校验和。"""
    w("| " + " | ".join(header) + " |")
    w("|" + "---|" * len(header))
    total = 0
    for r in rows:
        w("| " + " | ".join(str(c) for c in r) + " |")
        total += sum(c for c in r if isinstance(c, int) and not isinstance(c, bool))
    if checksum:
        w(f"| 校验和 = {total} |" + " |" * (len(header) - 1))
    w()


def name_pattern(name):
    s = re.sub(r"[0-9a-f]{16,}", "<hex>", name, flags=re.I)
    return re.sub(r"\d+", "9", s)


def enum_ok(key, values, allow=None):
    vals = [v for v in values if v not in ("", None)]
    distinct = set(map(str, vals))
    if any(vtype(v) not in ("str", "bool") for v in vals):
        return False  # 数字、日期、哈希不当枚举
    if allow is not None and not allow.search(key):
        return False
    return (not NO_ENUM.search(key) and 0 < len(distinct) <= ENUM_MAX
            and all(len(v) <= ENUM_VAL_MAXLEN for v in distinct))


def vtype(v):
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    s = str(v)
    if re.fullmatch(r"-?\d+", s):
        return "int"
    if re.fullmatch(r"-?\d+\.\d+", s):
        return "float"
    if s.lower() in ("true", "false"):
        return "bool"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        return "date"
    if re.fullmatch(r"[0-9a-f]{64}", s, re.I):
        return "sha256"
    return "str"


def rel(p, root):
    return p.relative_to(root).as_posix()


def is_lfs_pointer(p):
    try:
        with open(p, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- 读取 ----------

def read_table(p):
    delim = "\t" if p.suffix == ".tsv" else ","
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=delim))


def read_struct(p):
    """返回 (records, 说明)。records 是 dict 列表。"""
    if p.suffix == ".jsonl":
        recs = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
        return recs, "jsonl 每行一条"
    if p.suffix == ".json":
        doc = json.loads(p.read_text(encoding="utf-8"))
    else:
        if yaml is None:
            return None, "未装 PyYAML，跳过"
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return [d for d in doc if isinstance(d, dict)], "顶层列表"
    if isinstance(doc, dict):
        return [doc], "单个文档"
    return [], "未识别"


def walk(obj, prefix, paths, leaves):
    """收集键路径 -> 类型计数；叶子值收集到 leaves（只用于枚举判断，不输出原值）。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            paths[key][vtype(v)] += 1
            walk(v, key, paths, leaves)
    elif isinstance(obj, list):
        key = prefix + "[]"
        for item in obj:
            if isinstance(item, (dict, list)):
                walk(item, key, paths, leaves)
    else:
        leaves[prefix].append(obj)


def skeleton(obj, depth=0):
    if isinstance(obj, dict):
        return {k: skeleton(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (dict, list)):
            return [skeleton(obj[0], depth + 1), f"<list[{len(obj)}]>"]
        return f"<list[{len(obj)}]>"
    t = vtype(obj)
    return {"str": "<str>", "int": "<num>", "float": "<num>", "bool": "<bool>",
            "null": "<null>", "date": "<date>", "sha256": "<sha256>"}.get(t, "<str>")


def collect_refs(obj, out):
    """GT 里对文档/文件的引用：只取 REF_KEYS 里的键。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in REF_KEYS and isinstance(v, (str, int)):
                out[k].add(str(v))
            else:
                collect_refs(v, out)
    elif isinstance(obj, list):
        for x in obj:
            collect_refs(x, out)


def stem_variants(v):
    s = str(v).replace("\\", "/")
    base = s.rsplit("/", 1)[-1]
    return {s, base, base.rsplit(".", 1)[0]}


# ---------- 各节 ----------

def section_a(root):
    w("## A. 目录结构")
    w()
    w("### A1 目录树（三层以内，含子目录的文件总数）")
    w()
    rows = []
    patterns = []
    for top in ROOT_DIRS:
        base = root / top
        if not base.is_dir():
            rows.append((top, "不存在", 0, ""))
            continue
        dirs = [base] + [d for d in base.rglob("*") if d.is_dir() and len(d.relative_to(base).parts) <= 2]
        for d in sorted(dirs):
            files = [f for f in d.rglob("*") if f.is_file()]
            direct = [f for f in d.iterdir() if f.is_file()]
            ext = Counter(f.suffix.lower() or "(无)" for f in files)
            ext_s = ", ".join(f"{e}×{n}" for e, n in ext.most_common(6))
            rows.append((rel(d, root), len(direct), len(files), ext_s))
            if direct:
                pc = Counter(name_pattern(f.name) for f in direct)
                for pat, n in pc.most_common(3):
                    patterns.append((rel(d, root), pat, n))
    table(["目录", "直属文件数", "含子目录文件数", "扩展名分布"],
          [(a, b, c, d) for a, b, c, d in rows])
    w("### A1b 文件名规律（数字串替换为 9，长十六进制替换为 <hex>；每目录前 3 种）")
    w()
    table(["目录", "规律", "文件数"], patterns)

    w("### A2 .gitattributes")
    w()
    ga = root / ".gitattributes"
    if ga.exists():
        w("```")
        for line in ga.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                w(line)
        w("```")
    else:
        w("不存在")
    w()
    lfs = [f for top in ROOT_DIRS if (root / top).is_dir()
           for f in (root / top).rglob("*") if f.is_file() and is_lfs_pointer(f)]
    w(f"**未拉取的 LFS 指针文件数：{len(lfs)}**（非 0 说明没跑 `git lfs pull`，D3 哈希会对不上）")
    w()

    w("### A3 README 章节标题")
    w()
    rd = root / "README.md"
    if rd.exists():
        for line in rd.read_text(encoding="utf-8").splitlines():
            if re.match(r"#{1,4} ", line):
                w("- " + line)
    else:
        w("不存在")
    w()


def section_b(root):
    w("## B. metadata 字段")
    w()
    meta = {}
    base = root / "metadata"
    if not base.is_dir():
        w("metadata/ 不存在")
        w()
        return meta
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        r = rel(p, root)
        if p.suffix in TABLE_EXT:
            rows = read_table(p)
        elif p.suffix in STRUCT_EXT:
            recs, note = read_struct(p)
            if recs is None:
                w(f"### {r}\n\n{note}\n")
                continue
            rows = [{k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                     for k, v in x.items()} for x in recs]
        else:
            w(f"### {r}\n\n格式 {p.suffix or '(无扩展名)'}，未解析\n")
            continue
        meta[r] = rows
        cols = list(rows[0].keys()) if rows else []
        w(f"### {r}")
        w()
        w(f"行数 {len(rows)}，列数 {len(cols)}")
        w()
        trows, enums, hints = [], [], []
        for c in cols:
            vals = [x.get(c) for x in rows]
            nonempty = [v for v in vals if v not in ("", None)]
            types = Counter(vtype(v) for v in nonempty)
            t = "/".join(k for k, _ in types.most_common(2)) or "null"
            distinct = len(set(map(str, nonempty)))
            trows.append((c, t, len(nonempty), distinct))
            if enum_ok(c, vals):
                cnt = Counter(map(str, nonempty))
                enums.append((c, "; ".join(f"{k}={n}" for k, n in sorted(cnt.items()))))
            if SELECT_HINT.search(c):
                hints.append(c)
        table(["列名", "类型", "非空行", "不同值个数"], trows)
        if enums:
            w("枚举列取值：")
            w()
            for c, s in enums:
                w(f"- `{c}`：{s}")
            w()
        if hints:
            w(f"**可能与难度/选页相关的列：** {', '.join('`'+h+'`' for h in hints)}")
            w()
    return meta


def section_c(root):
    w("## C. GT 结构")
    w()
    base = root / "gt"
    groups = defaultdict(list)
    if not base.is_dir():
        w("gt/ 不存在")
        w()
        return {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in STRUCT_EXT | TABLE_EXT:
            parts = p.relative_to(base).parts
            groups[parts[0] if len(parts) > 1 else p.stem].append(p)
    refs_by_group = {}
    summary = []
    for g, files in groups.items():
        paths = defaultdict(Counter)
        leaves = defaultdict(list)
        nrec, first, notes = 0, None, Counter()
        refs = defaultdict(set)
        for p in files:
            if p.suffix in TABLE_EXT:
                recs, note = read_table(p), "表格每行一条"
            else:
                recs, note = read_struct(p)
            notes[note] += 1
            if recs is None:
                continue
            for rec in recs:
                # 单文档且含记录列表（如金融 YAML 的 assertions）：按列表元素计数
                inner = [v for v in rec.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
                nrec += max((len(v) for v in inner), default=1) if note == "单个文档" else 1
                walk(rec, "", paths, leaves)
                collect_refs(rec, refs)
                if first is None:
                    first = rec
        refs_by_group[g] = refs
        summary.append((g, len(files), nrec, "; ".join(f"{k}×{n}" for k, n in notes.items())))

        w(f"### {g}")
        w()
        w(f"文件 {len(files)}，记录 {nrec}（单文档按其中最长的对象列表计）")
        w()
        w("C2 键路径：")
        w()
        table(["键路径", "类型", "出现次数"],
              [(k, "/".join(t for t, _ in c.most_common(2)), sum(c.values()))
               for k, c in sorted(paths.items())])
        enums = [(k, Counter(map(str, v))) for k, v in sorted(leaves.items())
                 if enum_ok(k.split(".")[-1].rstrip("[]"), v, GT_ENUM_ALLOW)]
        if enums:
            w("C3 枚举键取值：")
            w()
            for k, cnt in enums:
                w(f"- `{k}`：" + "; ".join(f"{a}={n}" for a, n in sorted(cnt.items())))
            w()
        if first is not None:
            w("C4 结构骨架（第一条记录，值已替换为类型）：")
            w()
            w("```json")
            w(json.dumps(skeleton(first), ensure_ascii=False, indent=1)[:3000])
            w("```")
            w()
    w("### C 汇总")
    w()
    table(["集合", "文件数", "记录数", "解析方式"], summary)
    return refs_by_group


def section_d(root, meta, refs_by_group, do_hash):
    w("## D. 一致性检查（只有计数）")
    w()
    # D1：metadata 里像路径的值，在仓库里能不能找到
    d1 = []
    meta_values = set()
    for r, rows in meta.items():
        for row in rows:
            for v in row.values():
                if isinstance(v, str) and v:
                    meta_values |= stem_variants(v)
        for c in (rows[0].keys() if rows else []):
            vals = [x.get(c) for x in rows if x.get(c)]
            pathlike = [v for v in vals if isinstance(v, str)
                        and re.search(r"\.(pdf|png|jpe?g|tiff?|json|jsonl|ya?ml)$", v, re.I)]
            if len(pathlike) < max(1, len(vals) // 2):
                continue
            found = 0
            for v in pathlike:
                v2 = v.replace("\\", "/")
                if any((root / pre / v2).is_file() for pre in ("", "data", "gt")):
                    found += 1
            d1.append((r, c, len(pathlike), found, len(pathlike) - found))
    w("### D1 metadata 登记的文件路径能否在仓库找到")
    w()
    table(["metadata 文件", "列", "登记数", "找到", "找不到"], d1) if d1 else w("未识别到路径列\n")

    # D2：GT 引用能否在 metadata 找到
    d2 = []
    for g, refs in refs_by_group.items():
        for k, vals in sorted(refs.items()):
            hit = sum(1 for v in vals if stem_variants(v) & meta_values)
            d2.append((g, k, len(vals), hit, len(vals) - hit))
    w("### D2 GT 引用的文档/文件 id 能否在 metadata 找到")
    w()
    table(["集合", "键", "不同值个数", "找到", "找不到"], d2) if d2 else w("GT 里未识别到引用键\n")

    # D3：sha256 重算
    w("### D3 sha256 重算")
    w()
    if not do_hash:
        w("已跳过（--no-hash）")
        w()
    else:
        d3 = []
        for r, rows in meta.items():
            if not rows:
                continue
            cols = list(rows[0].keys())
            hcol = next((c for c in cols if re.search(r"sha256|sha|hash|checksum", c, re.I)), None)
            if not hcol:
                continue
            pcols = [c for c in cols if c != hcol and any(
                isinstance(x.get(c), str) and re.search(r"\.\w{2,5}$", x.get(c) or "") for x in rows[:20])]
            if not pcols:
                continue
            pcol = pcols[0]
            ok = bad = missing = lfs = 0
            for x in rows:
                v = (x.get(pcol) or "").replace("\\", "/")
                cand = [root / pre / v for pre in ("", "data", "gt")]
                f = next((c for c in cand if c.is_file()), None)
                if f is None:
                    missing += 1
                elif is_lfs_pointer(f):
                    lfs += 1
                elif sha256(f) == (x.get(hcol) or "").lower():
                    ok += 1
                else:
                    bad += 1
            d3.append((r, f"{pcol}/{hcol}", ok, bad, missing, lfs))
        table(["metadata 文件", "路径列/哈希列", "一致", "不一致", "文件缺失", "LFS 指针"], d3) \
            if d3 else w("未识别到含哈希列的 metadata\n")

    # D4：扰动集能否映射回原始页
    w("### D4 扰动集映射")
    w()
    gt_docs = set()
    for refs in refs_by_group.values():
        gt_docs |= refs.get("doc_id", set())
    d4 = []
    for r, rows in meta.items():
        if not rows or "variant" not in rows[0]:
            continue
        idcol = "doc_id" if "doc_id" in rows[0] else None
        if not idcol:
            d4.append((r, len(rows), 0, len(rows)))
            continue
        hit = sum(1 for x in rows if x.get(idcol) in gt_docs)
        d4.append((r, len(rows), hit, len(rows) - hit))
    table(["metadata 文件", "扰动行数", "doc_id 在 GT 中", "不在"], d4) if d4 \
        else w("未找到含 variant 列的 metadata\n")


def section_f(do_net):
    w("## F. 运行环境")
    w()
    w(f"- Python {platform.python_version()}，{platform.system()} {platform.release()}")
    w(f"- PyYAML：{'有' if yaml else '无'}")
    try:
        import playwright  # noqa: F401
        w("- playwright：已装（chromium 是否装好需另查）")
    except ImportError:
        w("- playwright：未装")
    if do_net:
        for host in ("github.com", "huggingface.co", "pypi.org"):
            try:
                urllib.request.urlopen(f"https://{host}", timeout=5)
                w(f"- {host}：能")
            except urllib.error.HTTPError as e:
                w(f"- {host}：能（返回 HTTP {e.code}）")
            except Exception as e:
                w(f"- {host}：不能（{type(e).__name__}）")
    w()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="inventory-for-photo.md")
    ap.add_argument("--no-hash", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve()

    w("# ocr-benchmark-dataset 结构清单")
    w()
    w("由 dataset_inventory.py 生成。只含结构与计数，不含正文、GT 值、路径以外的内容。")
    w()
    print("[A] ...", file=sys.stderr)
    section_a(root)
    print("[B] ...", file=sys.stderr)
    meta = section_b(root)
    print("[C] ...", file=sys.stderr)
    refs = section_c(root)
    print("[D] ...", file=sys.stderr)
    section_d(root, meta, refs, not a.no_hash)
    print("[F] ...", file=sys.stderr)
    section_f(not a.no_network)

    Path(a.out).write_text("\n".join(out_lines), encoding="utf-8")
    print(f"写入 {a.out}（{len(out_lines)} 行）", file=sys.stderr)


if __name__ == "__main__":
    main()
