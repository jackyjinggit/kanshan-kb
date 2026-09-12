#!/usr/bin/env python3
"""Validate the requested KB contract and resolvable local evidence chain."""
import json
import re
import sys
from urllib.parse import unquote, urlsplit, urlunsplit

import kb_common as kb


def source_errors(meta, body, zhihu):
    errors = []
    for key in ("title", "verification"):
        if not kb.nonempty(meta.get(key)):
            errors.append(f"{key} 必须为非空字符串")
    author = meta.get("author")
    if not (kb.nonempty(author) or isinstance(author, list) and author and all(kb.nonempty(a) for a in author)):
        errors.append("author 必须为非空字符串或非空字符串列表")
    if not kb.valid_date(meta.get("accessed_at"), not_future=True):
        errors.append("accessed_at 必须为有效 YYYY-MM-DD 且不得晚于今天")
    for key in ("published_at", "updated_at", "edited_at", "effective_at"):
        if key in meta and not kb.valid_date(meta[key], partial=True, nullable=True):
            errors.append(f"{key} 必须为有效年/月/日或 null")
    try:
        kb.validate_web_url(meta.get("source_url"), zhihu=zhihu)
    except kb.KBError as exc:
        errors.append(str(exc))
    if not kb.has_prose(body):
        errors.append("来源卡缺少非空原创摘要正文")
    return errors


def writing_errors(meta, body):
    errors = []
    for key in ("title", "standard_id", "evidence_level"):
        if not kb.nonempty(meta.get(key)):
            errors.append(f"{key} 必须为非空字符串")
    if meta.get("type") != "writing_standard":
        errors.append("写作真源 type 必须为 writing_standard")
    if not isinstance(meta.get("standard_id"), str) or not re.fullmatch(r"W[0-9]{2}", meta["standard_id"]):
        errors.append("standard_id 必须为 W 加两位 ASCII 数字")
    if not kb.valid_date(meta.get("updated"), not_future=True):
        errors.append("写作真源 updated 必须为有效日期且不得晚于今天")
    if not kb.has_prose(body):
        errors.append("写作真源正文不能为空")
    return errors


def canonical_key(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def validate():
    errors = []
    files, walk_errors = kb.repository_files()
    errors.extend(walk_errors)
    paths, layout_errors = kb.method_inventory()
    errors.extend(layout_errors)
    counts = {module: 0 for module in kb.MODULES}
    documents, text_cache = {}, {}
    source_directories = {kb.CASES, kb.ROOT / "知识库" / "全球研究资料"}
    source_paths, writing_paths = [], []

    def add(path, message):
        errors.append(f"{kb.relative_name(path)}: {message}")

    for path in files:
        if path.suffix != ".md":
            continue
        is_source = any(path.is_relative_to(directory) for directory in source_directories)
        is_writing = path.is_relative_to(kb.WRITING)
        if is_source and path.parent not in source_directories:
            add(path, "来源卡必须直接位于已登记的来源目录")
        elif is_source:
            source_paths.append(path)
        if is_writing:
            if path.parent != kb.WRITING:
                add(path, "写作真源必须直接位于写作目录")
            else:
                writing_paths.append(path)
        try:
            if path in paths or is_source or is_writing:
                meta, body, text = kb.read_doc(path)
                documents[path] = (meta, body)
                text_cache[path] = (body, text)
            else:
                text = kb.read_text(path)
                text_cache[path] = (text, text)
        except Exception as exc:
            add(path, kb.safe_error(exc))

    # Validate all actual links once. A bad URL becomes one safe error, not a traceback.
    targets_by_path = {}
    for path, (body, text) in text_cache.items():
        targets = []
        try:
            destinations = kb.link_targets(body)
        except Exception as exc:
            add(path, f"Markdown 无法解析：{kb.safe_error(exc)}")
            destinations = []
        for kind, link in destinations:
            try:
                target = kb.local_target(path, link)
                if target is not None:
                    if not target.exists():
                        raise kb.KBError("本地链接指向不存在的目标")
                    if kind == "hyperlink":
                        targets.append(target)
            except Exception as exc:
                add(path, f"链接无效：{kb.safe_error(exc)}")
        targets_by_path[path] = targets
        if re.search(r"/Users/|/var/folders/|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}", text):
            add(path, "命中本机路径或凭证模式，需检查")

    canonical, aliases, url_owners = {}, {}, {}
    for path in source_paths:
        if path not in documents:
            continue
        meta, body = documents[path]
        if meta.get("type") == "source_alias":
            if set(meta) != {"title", "type", "canonical"} or not kb.nonempty(meta.get("title")):
                add(path, "来源别名仅允许 title、type、canonical，title 必须为非空字符串")
                continue
            try:
                value = meta.get("canonical")
                if not kb.nonempty(value):
                    raise kb.KBError("来源别名 canonical 必须为同目录相对 Markdown 路径")
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or ".." in unquote(parsed.path).split("/"):
                    raise kb.KBError("来源别名 canonical 不得含协议、片段、查询或上级路径")
                target = kb.local_target(path, value)
                if target is None or target.parent != path.parent or target.suffix != ".md":
                    raise kb.KBError("来源别名必须指向同来源目录的 Markdown 文件")
                if target not in targets_by_path.get(path, []):
                    raise kb.KBError("来源别名正文必须有指向 canonical 的实际链接")
                if not kb.has_prose(body):
                    raise kb.KBError("来源别名正文不能为空")
                aliases[path] = target
            except Exception as exc:
                add(path, kb.safe_error(exc))
            continue
        if meta.get("type") != "source":
            add(path, "来源卡 type 必须为 source 或 source_alias")
            continue
        try:
            problems = source_errors(meta, body, path.parent == kb.CASES)
        except Exception as exc:
            problems = [kb.safe_error(exc)]
        for problem in problems:
            add(path, problem)
        if not problems:
            key = canonical_key(meta["source_url"])
            if key in url_owners:
                add(path, f"重复 canonical 来源 URL，应改用别名或合并（已有 {kb.relative_name(url_owners[key])}）")
            else:
                url_owners[key] = path
            canonical[path] = meta

    resolved_aliases = {}
    for path in aliases:
        visited, target = {path}, aliases[path]
        while target in aliases and target not in visited:
            visited.add(target)
            target = aliases[target]
        if target in visited:
            add(path, "来源别名形成循环")
        elif target not in canonical:
            add(path, "来源别名未解析到通过验证的 canonical source")
        else:
            resolved_aliases[path] = target

    valid_writing, writing_ids = set(), set()
    for path in writing_paths:
        if path not in documents:
            continue
        meta, body = documents[path]
        try:
            problems = writing_errors(meta, body)
        except Exception as exc:
            problems = [kb.safe_error(exc)]
        if not problems and meta["standard_id"] in writing_ids:
            problems.append("重复 standard_id")
        for problem in problems:
            add(path, problem)
        if not problems:
            writing_ids.add(meta["standard_id"])
            valid_writing.add(path)

    valid_cases = {path for path in canonical if path.parent == kb.CASES}
    valid_cases.update(path for path, target in resolved_aliases.items() if target.parent == kb.CASES)
    ids = set()
    for path in paths:
        expected = next((module for module, name in kb.MODULES.items() if path.parent == kb.METHODS / f"{module}_{name}"), None)
        if expected:
            counts[expected] += 1
        if path not in documents:
            continue
        meta, body = documents[path]
        try:
            problems = kb.method_errors(path, meta, body)
        except Exception as exc:
            problems = [kb.safe_error(exc)]
        for problem in problems:
            add(path, problem)
        identifier = meta.get("method_id")
        if isinstance(identifier, str):
            if identifier in ids:
                add(path, "重复 method_id")
            ids.add(identifier)
        targets = set(targets_by_path.get(path, []))
        if not targets.intersection(valid_cases):
            add(path, "缺少有效本地知乎案例引用")
        if expected == "M4" and not targets.intersection(valid_writing):
            add(path, "M4 必须引用通过验证的写作表述真源")
    for module, count in counts.items():
        minimum = 1 if module in ("M9", "M10") else 2
        if count < minimum:
            errors.append(f"{module}: {count} 篇，至少需要 {minimum} 篇")
    indexes = [path for path in files if path.is_relative_to(kb.METHODS) and path.name == "INDEX.md"]
    if indexes != [kb.METHODS / "INDEX.md"]:
        errors.append("方法论层应且仅应有根目录 INDEX.md")
    elif "更新记录" not in text_cache.get(indexes[0], ("", ""))[0]:
        errors.append("INDEX.md 缺少更新记录")
    errors = list(dict.fromkeys(errors))
    return {
        "ok": not errors, "method_count": sum(counts.values()), "module_counts": counts,
        "source_count": len(canonical), "source_alias_count": len(resolved_aliases),
        "zhihu_source_count": sum(path.parent == kb.CASES for path in canonical),
        "global_source_count": sum(path.parent != kb.CASES for path in canonical),
        "writing_standard_count": len(valid_writing), "distinct_primary_source_urls": len(url_owners),
        "errors": errors,
        "scope": "结构与本地文件引用检查；片段只检查文件；不替代来源事实、漏洞数据库、版权、线上接口或增长效果验收",
    }


def main():
    try:
        result = validate()
    except Exception as exc:
        result = {"ok": False, "errors": [kb.safe_error(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
