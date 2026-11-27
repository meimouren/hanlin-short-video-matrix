"""口播稿去机械化与自然度自动体检工具（可独立运行，严格只读，零网络调用）。"""

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True

ROOT = Path.cwd()

OFFICIAL_WORDS = [
    ("均暂定", "改用「都还没定 / 暂时还没定」"),
    ("仍待定", "改用「还没定 / 目前还写着待定」"),
    ("均需", "改用「都得 / 都要」"),
    ("均须", "改用「都得 / 都要」"),
    ("拟赴", "改用「准备去 / 能去」"),
    ("综上所述", "删掉套话，直接说结论或下一步动作"),
    ("值得注意的是", "改用「这里最容易漏 / 要注意一点」"),
    ("此外", "改用「另外 / 还有一点」"),
    ("另一方面", "改用「再看另一边 / 还有一种情况」"),
    ("相关事宜", "换成具体要办的那件事"),
    ("进行核对", "改用「核对一下 / 对一下」"),
    ("予以确认", "改用「确认好 / 问清楚」"),
    ("各位家长大家好", "删掉开场套话，第一句直接抛家长关心的问题"),
    ("首先", "删掉编号连接词，直接先说最关键的判断"),
    ("其次", "改用「接着再看 / 还有」"),
]

OFFICIAL_PATTERNS = [
    (re.compile(r"(?<![不未])须"), "书面词「须」建议改用「得 / 要 / 一定要」"),
    (re.compile(r"具备.{0,4}资格"), "「具备……资格」偏书面，改用「够不够条件 / 能不能报」"),
    (re.compile(r"按.{0,8}通知执行"), "「按……通知执行」偏公文，改用「看……发的通知」"),
    (re.compile(r"(?:^|[，。！？；：\n|])最后[，,]"), "口播避免「最后，」公文收尾感，直接讲最后一步或下一步"),
]

DATE_RI_PATTERN = re.compile(r"(?:\d+|[一二三四五六七八九十零〇两]+)\s*月\s*(?:\d+|[一二三四五六七八九十零〇两]+)\s*日")

ENUM_PATTERNS = [
    (re.compile(r"第一种.{0,80}第二种"), "出现「第一种……第二种……」机械分类排比，建议改成生活场景问答或自然转折"),
    (re.compile(r"第一[，,：:].{0,80}第二[，,：:]"), "出现「第一……第二……」编号排比，口播建议用「先看……再看……」"),
    (re.compile(r"首先.{0,80}其次"), "出现「首先……其次……」书面连接词"),
]

CLAUSE_SPLIT = re.compile(r"[，。！？；：、|,\n]+")
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*|[\u4e00-\u9fff]")


def normalize_text(text):
    return re.sub(r"[\W_]+", "", text).lower()


def count_spoken_units(clause):
    return len(TOKEN_RE.findall(clause))


def load_entries(target: Path):
    """自动识别批次目录、各类 JSON 稿件或纯文本文件，返回统一条目列表。"""
    if target.is_dir():
        gemini_file = target / "Gemini校订稿.json"
        if gemini_file.is_file():
            rows = json.loads(gemini_file.read_text("utf8"))
            return [
                {
                    "id": r.get("id", f"{i:02d}"),
                    "account": r.get("账号", ""),
                    "platform": r.get("平台", ""),
                    "speech": r.get("口播稿", ""),
                    "post": r.get("发布正文", ""),
                    "scenes": [p.strip() for p in r.get("口播稿", "").splitlines() if p.strip()],
                }
                for i, r in enumerate(rows, 1)
            ]

        tpl = target / "制作模板"
        sb_file = tpl / "新版分镜.json"
        ct_file = tpl / "本期内容.json"
        if sb_file.is_file():
            sb_rows = json.loads(sb_file.read_text("utf8"))
            ct_map = {}
            if ct_file.is_file():
                for row in json.loads(ct_file.read_text("utf8")):
                    ct_map[row[0]] = row
            entries = []
            for r in sb_rows:
                nid = r[0]
                scenes = [s for s in r[4:] if isinstance(s, str)]
                ct = ct_map.get(nid, [])
                entries.append({
                    "id": nid,
                    "platform": ct[1] if len(ct) > 1 else "",
                    "account": ct[2] if len(ct) > 2 else "",
                    "speech": "\n".join(scenes),
                    "post": ct[5] if len(ct) > 5 else "",
                    "scenes": scenes,
                })
            return entries
        raise ValueError(f"无法在目录中识别口播稿件: {target}")

    if not target.is_file():
        raise FileNotFoundError(f"路径不存在: {target}")

    if target.suffix.lower() == ".txt":
        text = target.read_text("utf-8-sig")
        scenes = [line.strip() for line in text.splitlines() if line.strip()]
        return [{"id": target.stem, "platform": "", "account": "", "speech": text, "post": "", "scenes": scenes}]

    data = json.loads(target.read_text("utf-8-sig"))
    if isinstance(data, dict) and "cues" in data:
        cues = [c["text"] for c in data["cues"] if c.get("text")]
        return [{
            "id": target.stem,
            "platform": "",
            "account": "",
            "speech": "\n".join(cues),
            "post": "",
            "scenes": cues,
        }]
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "口播稿" in data[0]:
            return [
                {
                    "id": r.get("id", f"{i:02d}"),
                    "platform": r.get("平台", ""),
                    "account": r.get("账号", ""),
                    "speech": r.get("口播稿", ""),
                    "post": r.get("发布正文", ""),
                    "scenes": [p.strip() for p in r.get("口播稿", "").splitlines() if p.strip()],
                }
                for i, r in enumerate(data, 1)
            ]
        if data and isinstance(data[0], list):
            if len(data[0]) in (2, 3) and all(isinstance(x, str) for x in data[0]):
                lines = [row[-1] for row in data if row[-1].strip()]
                return [{
                    "id": target.stem,
                    "platform": "",
                    "account": "",
                    "speech": "\n".join(lines),
                    "post": "",
                    "scenes": lines,
                }]
            if len(data[0]) >= 5:
                return [
                    {
                        "id": r[0],
                        "platform": "",
                        "account": "",
                        "speech": "\n".join(r[4:]),
                        "post": "",
                        "scenes": [s for s in r[4:] if isinstance(s, str)],
                    }
                    for r in data
                ]
    raise ValueError(f"不支持的稿件 JSON 结构: {target}")


def analyze(entries, max_clause=22):
    items_report = []
    tail_candidates = []

    for entry in entries:
        issues = []
        raw_speech = entry["speech"]
        plain_speech = raw_speech.replace("|", "")

        for word, advice in OFFICIAL_WORDS:
            if word in plain_speech:
                issues.append({"type": "书面公文词", "detail": f"命中「{word}」", "advice": advice})

        for pat, msg in OFFICIAL_PATTERNS:
            m = pat.search(plain_speech)
            if m:
                issues.append({"type": "书面公文词", "detail": f"命中「{m.group(0)}」", "advice": msg})

        ri_hits = DATE_RI_PATTERN.findall(plain_speech)
        if ri_hits:
            issues.append({
                "type": "口播日期偏书面",
                "detail": f"日期用「日」: {', '.join(ri_hits[:4])}",
                "advice": "口播建议将「×月×日」改读为「×月×号」",
            })

        flat_speech = re.sub(r"\s+", "", plain_speech)
        for pat, msg in ENUM_PATTERNS:
            if pat.search(flat_speech):
                issues.append({"type": "机械排比", "detail": pat.pattern, "advice": msg})

        long_clauses = []
        for clause in CLAUSE_SPLIT.split(raw_speech):
            c = clause.strip()
            if not c:
                continue
            units = count_spoken_units(c)
            if units > max_clause:
                long_clauses.append((units, c))
        if long_clauses:
            sample = "；".join(f"({u}字) {c[:28]}{'…' if len(c) > 28 else ''}" for u, c in long_clauses[:3])
            issues.append({
                "type": "超长无换气分句",
                "detail": f"{len(long_clauses)} 处超过 {max_clause} 字: {sample}",
                "advice": f"单口气分句拆短至 {max_clause} 字以内，删掉多层定语",
            })

        post = entry.get("post", "").strip()
        if post:
            ratio = SequenceMatcher(None, normalize_text(plain_speech), normalize_text(post), autojunk=False).ratio()
            if ratio >= 0.85:
                issues.append({
                    "type": "口播照搬发布正文",
                    "detail": f"与发布正文相似度 {ratio:.2%}",
                    "advice": "口播与发布正文需分开写，按「40 秒微信语音」口语重说",
                })

        scenes = [s.replace("|", "").strip() for s in entry.get("scenes", []) if s.strip()]
        if scenes:
            tail = scenes[-1]
            tail_candidates.append((entry["id"], entry.get("account", ""), tail))

        items_report.append({
            "id": entry["id"],
            "account": entry.get("account", ""),
            "platform": entry.get("platform", ""),
            "issue_count": len(issues),
            "issues": issues,
        })

    batch_warnings = []
    if len(tail_candidates) >= 3:
        template_hits = [
            (nid, acc, tail)
            for nid, acc, tail in tail_candidates
            if ("可以后台私信我们" in tail or "免费领取" in tail or "在评论区留" in tail)
        ]
        clustered = []
        for i, (id_a, acc_a, tail_a) in enumerate(tail_candidates):
            na = normalize_text(tail_a)
            peers = [id_a]
            for j, (id_b, _, tail_b) in enumerate(tail_candidates):
                if i == j:
                    continue
                if SequenceMatcher(None, na, normalize_text(tail_b), autojunk=False).ratio() >= 0.58:
                    peers.append(id_b)
            if len(peers) >= 3:
                key = tuple(sorted(peers))
                if key not in clustered:
                    clustered.append(key)
        if clustered:
            for group in clustered:
                batch_warnings.append({
                    "type": "批内片尾福利句式趋同",
                    "accounts": list(group),
                    "detail": f"{len(group)} 个账号片尾句式相似度 >= 58%: {', '.join(group)}",
                    "advice": "同批不同账号请换用动作接话/问题承接/提醒收尾等不同过渡方式",
                })
        elif len(template_hits) >= 4:
            batch_warnings.append({
                "type": "批内片尾套话偏多",
                "accounts": [x[0] for x in template_hits],
                "detail": f"{len(template_hits)} 个账号共用「可以后台私信我们/免费领取/在评论区留」模板词",
                "advice": "适当替换更口语化的收尾接话（如「发我两字」「评论区打个…」）",
            })

    total_issues = sum(item["issue_count"] for item in items_report) + len(batch_warnings)
    return {
        "ok": total_issues == 0,
        "checked_count": len(entries),
        "total_issues": total_issues,
        "batch_warnings": batch_warnings,
        "items": items_report,
    }


def resolve_target(raw: str) -> Path:
    p = Path(raw)
    if p.exists():
        return p.resolve()
    rel = ROOT / raw
    if rel.exists():
        return rel.resolve()
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="批次目录名/路径，或具体口播稿文件（.json/.txt）")
    parser.add_argument("--max-clause", type=int, default=22, help="单口气分句上限字数（默认 22）")
    parser.add_argument("--strict", action="store_true", help="发现机械化问题时返回退出码 1")
    parser.add_argument("--json", type=Path, help="可选：保存结构化检查结果 JSON")
    args = parser.parse_args()

    target = resolve_target(args.target)
    entries = load_entries(target)
    report = analyze(entries, max_clause=args.max_clause)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    print(f"=== 口播去机械化体检 | 目标: {target.name} | 共 {report['checked_count']} 条 ===")
    for item in report["items"]:
        label = " ".join(x for x in (item["id"], item["platform"], item["account"]) if x)
        if not item["issues"]:
            print(f"[通过] {label}")
            continue
        print(f"[待润色 {item['issue_count']} 项] {label}")
        for iss in item["issues"]:
            print(f"  - {iss['type']}: {iss['detail']} | 建议: {iss['advice']}")
    for bw in report["batch_warnings"]:
        print(f"[批次提示] {bw['type']}: {bw['detail']} | 建议: {bw['advice']}")
    print(f"总计发现 {report['total_issues']} 项可优化点。")
    if args.strict and not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
