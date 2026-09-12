#!/usr/bin/env python3
"""Preflight all modules, then refresh only their README FILELIST blocks."""
import argparse
import json
import os
import re
import tempfile
from urllib.parse import quote

import kb_common as kb

START, END = "<!-- FILELIST:START -->", "<!-- FILELIST:END -->"


def build_plan():
    paths, errors = kb.method_inventory()
    plan, ids = [], set()
    for module, name in kb.MODULES.items():
        directory = kb.METHODS / f"{module}_{name}"
        rows = []
        for method in (path for path in paths if path.parent == directory):
            try:
                meta, body, _ = kb.read_doc(method)
                problems = kb.method_errors(method, meta, body)
                if problems:
                    raise kb.KBError("；".join(problems))
                if meta["method_id"] in ids:
                    raise kb.KBError("重复 method_id")
                ids.add(meta["method_id"])
                # Escape label markup and reserved filename characters without changing Unicode names.
                title = re.sub(r"([\\`*_[\]<>])", r"\\\1", " ".join(meta["title"].splitlines()))
                filename = "".join(char if ord(char) > 127 else quote(char, safe="-_.~") for char in method.name)
                rows.append(f"- [{meta['method_id']} {title}]({filename})")
            except Exception as exc:
                errors.append(f"{kb.relative_name(method)}: {kb.safe_error(exc)}")
        block = f"{START}\n" + "\n".join(rows) + f"\n{END}"
        readme = directory / "README.md"
        try:
            kb.safe_path(directory)
            kb.safe_path(readme)
            old = kb.read_text(readme) if readme.exists() else None
            original = old if old is not None else f"# {module} {name}\n\n方法与新增记录统一见[域总表](../INDEX.md)。\n\n## 方法文件\n\n{START}\n{END}\n"
            if original.count(START) != 1 or original.count(END) != 1:
                raise kb.KBError("FILELIST 标记必须成对且唯一")
            if original.index(START) >= original.index(END):
                raise kb.KBError("FILELIST 标记顺序错误")
            new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, original, flags=re.S)
            if old != new:
                plan.append((readme, old, new))
        except Exception as exc:
            errors.append(f"{kb.relative_name(readme)}: {kb.safe_error(exc)}")
    return plan, list(dict.fromkeys(errors))


def apply_plan(plan):
    staged, written, errors = [], [], []
    try:
        # Create all temporary files before replacing anything; I/O errors here leave READMEs untouched.
        for path, old, new in plan:
            kb.safe_path(path)
            current = kb.read_text(path) if path.exists() else None
            if current != old:
                raise kb.KBError("预检后 README 已变化，请重新运行")
            handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".kb-filelist-", dir=path.parent, delete=False)
            temp = kb.safe_path(handle.name)
            staged.append((temp, path, old))
            with handle:
                handle.write(new)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        for temp, path, old in staged:
            kb.safe_path(path)
            if (kb.read_text(path) if path.exists() else None) != old:
                raise kb.KBError("预检后 README 已变化，请重新运行")
            os.replace(temp, path)
            written.append(kb.relative_name(path))
    except Exception as exc:
        errors.append(kb.safe_error(exc))
    finally:
        for temp, _, _ in staged:
            try:
                temp.unlink(missing_ok=True)
            except Exception as exc:
                errors.append(f"{kb.relative_name(temp)}: 暂存文件清理失败（{type(exc).__name__}）")
    return written, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查列表是否最新，不写文件")
    args = parser.parse_args(argv)
    try:
        plan, errors = build_plan()
        written = []
        if not errors and not args.check:
            written, errors = apply_plan(plan)
        result = {"ok": not errors and not (args.check and plan),
                  "mode": "check" if args.check else "rebuild", "pending_count": len(plan),
                  "pending": [kb.relative_name(path) for path, _, _ in plan],
                  "written": written, "errors": errors}
    except Exception as exc:
        result = {"ok": False, "written": [], "errors": [kb.safe_error(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
