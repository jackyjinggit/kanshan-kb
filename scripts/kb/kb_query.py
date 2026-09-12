#!/usr/bin/env python3
"""Filter validated methods in place, returning JSON for a consuming engine."""
import argparse
import json

import kb_common as kb
from kb_validate import validate


def query(module=None, keyword="", limit=3, full_text=False):
    checked = validate()
    if not checked["ok"]:
        return {"status": "invalid_kb", "methods": [], "errors": checked["errors"]}
    results = []
    for path in kb.method_paths():
        meta, body, _ = kb.read_doc(path)
        if module and meta["module"] != module:
            continue
        if keyword and keyword.casefold() not in (str(meta) + body).casefold():
            continue
        record = {"method_id": meta["method_id"], "title": meta["title"], "module": meta["module"],
                  "platform": meta["适用平台"], "stage": meta["适用阶段"], "signal": meta["数据信号"],
                  "evidence_level": meta.get("evidence_level"), "path": path.relative_to(kb.ROOT).as_posix(),
                  "reference_base": "method_directory", "references": kb.links(body)}
        if full_text:
            record["full_text"] = body
        results.append(record)
    return {"status": "ok" if results else "no_match", "total_matches": len(results),
            "selection": "module and optional literal keyword; no automatic diagnosis",
            "methods": results[:limit]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", choices=list(kb.MODULES))
    parser.add_argument("--query", default="", help="可选的字面关键词，不作语义或因果判断")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--full-text", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("limit 必须在1到50之间")
    try:
        result = query(args.module, args.query, args.limit, args.full_text)
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception as exc:
        result = {"status": "invalid_kb", "methods": [], "errors": [kb.safe_error(exc)]}
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    print(output)
    return 1 if result["status"] == "invalid_kb" else 0


if __name__ == "__main__":
    raise SystemExit(main())
