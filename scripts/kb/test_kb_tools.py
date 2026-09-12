"""Contract regressions using synthetic data in temporary repositories only."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
import json
import os
import shutil
import unittest

import yaml
import kb_common as kb
import kb_index_rebuild as index
import kb_query as query
import kb_validate as validator


class KnowledgeToolBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="kanshan-kb-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.methods = self.root  # 主仓结构：方法卡在根 M*/ 目录
        self.cases = self.root / "知识库" / "知乎知识库"
        self.global_sources = self.root / "知识库" / "全球研究资料"
        self.writing = self.root / "知识库" / "写作表述方法论"
        self.modules = {"M1": "定位与赛道选择", "M4": "内容生产与爆款公式", "M5": "平台算法与分发机制", "M10": "合规与风险"}
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for key, value in {"ROOT": self.root, "METHODS": self.methods, "CASES": self.cases,
                           "WRITING": self.writing, "MODULES": self.modules}.items():
            self.patches.enter_context(patch.object(kb, key, value))
        for directory in (self.cases, self.global_sources, self.writing):
            directory.mkdir(parents=True, exist_ok=True)
        (self.root / "README.md").write_text("# 临时合成库\n\n## 已知标题\n\n用于本地边界测试。\n")
        (self.methods / "INDEX.md").write_text("# 合成导航\n\n## 更新记录\n\n仅供测试。\n")
        self.source = self.cases / "synthetic-source.md"
        self.source_meta = {"title": "合成来源", "type": "source", "source_url": "https://www.zhihu.com/question/0",
                            "author": "合成作者", "accessed_at": "2000-01-01", "published_at": None,
                            "verification": "synthetic_test_fixture_not_researched"}
        self.write_doc(self.source, self.source_meta, "这是合成来源摘要，链接未经在线访问或事实核验，仅用于工具测试。")
        self.standard = self.writing / "synthetic-writing.md"
        self.standard_meta = {"title": "合成写作规则", "type": "writing_standard", "standard_id": "W01",
                              "updated": "2000-01-01", "evidence_level": "合成测试规则"}
        self.write_doc(self.standard, self.standard_meta, "这是用于边界测试的合成写作正文，不是运营建议。")
        self.prefix = "# 人工维护标题\n\n必须保留：范围说明。\n\n"
        self.suffix = "\n\n## 待填清单\n\n人工备注。\n"
        self.readmes = []
        for module, name in self.modules.items():
            directory = self.methods / f"{module}_{name}"
            directory.mkdir()
            for number in (1, 2):
                meta = {"title": f"合成方法 {module}-{number:02d}", "type": "method",
                        "method_id": f"{module}-{number:02d}", "module": module, "适用平台": "知乎",
                        "适用阶段": "全阶段", "数据信号": "仅供测试的合成信号", "evidence_level": "合成测试"}
                body = "## 诊断\n\n" + "合成文字仅用于工具测试，不是实际运营建议，也没有经过平台核验。" * 20
                body += "\n\n## 处方\n\n1. 只在临时目录执行测试。\n\n## 依据\n\n[合成案例](../知识库/知乎知识库/synthetic-source.md)\n"
                if module == "M4":
                    body += "\n[合成真源](../知识库/写作表述方法论/synthetic-writing.md)\n"
                self.write_doc(directory / f"{number:02d}.md", meta, body)
            readme = directory / "README.md"
            readme.write_text(self.prefix + index.START + "\n旧文件清单\n" + index.END + self.suffix)
            self.readmes.append(readme)
        self.first = self.methods / "M5_平台算法与分发机制" / "01.md"
        self.m1 = self.methods / "M1_定位与赛道选择" / "01.md"
        self.assert_valid()

    def write_doc(self, path, meta, body):
        path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n", encoding="utf-8")

    def set_meta(self, path, key, value):
        meta, body, _ = kb.read_doc(path)
        meta[key] = value
        self.write_doc(path, meta, body)

    def append(self, path, content):
        path.write_text(path.read_text() + content)

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file() and not path.is_symlink()}

    def assert_valid(self):
        result = validator.validate()
        self.assertTrue(result["ok"], result["errors"])
        return result

    def assert_invalid(self, message=None):
        result = validator.validate()
        self.assertFalse(result["ok"])
        if message:
            self.assertTrue(any(message in error for error in result["errors"]), result["errors"])
        return result

    def run_cli(self, function, *args):
        stream = StringIO()
        with redirect_stdout(stream):
            code = function(list(args)) if function is not validator.main else function()
        def reject_constant(value):
            raise AssertionError(f"CLI 输出不是严格 JSON：{value}")
        return code, json.loads(stream.getvalue(), parse_constant=reject_constant)

    def replace_cases(self, replacement):
        self.first.write_text(self.first.read_text().replace("[合成案例](../知识库/知乎知识库/synthetic-source.md)", replacement))

    def add_alias(self, name="alias.md", canonical="synthetic-source.md"):
        path = self.cases / name
        self.write_doc(path, {"title": "合成别名", "type": "source_alias", "canonical": canonical},
                       f"该合成旧路径统一引用 [canonical](<{canonical}>)。")
        return path

    def test_rebuild_and_check_preserve_surroundings_and_are_idempotent(self):
        before = self.snapshot()
        code, result = self.run_cli(index.main, "--check")
        self.assertEqual(code, 1)
        self.assertEqual(result["pending_count"], 4)
        self.assertEqual(self.snapshot(), before)
        code, result = self.run_cli(index.main)
        self.assertEqual(code, 0)
        for readme in self.readmes:
            text = readme.read_text()
            self.assertTrue(text.startswith(self.prefix))
            self.assertTrue(text.endswith(self.suffix))
            self.assertEqual(len(kb.links(text)), 2)
        generated = self.snapshot()
        for command in (("--check",), (), ("--check",)):
            self.assertEqual(self.run_cli(index.main, *command)[0], 0)
            self.assertEqual(self.snapshot(), generated)
        readme_names = {str(path.relative_to(self.root)) for path in self.readmes}
        self.assertEqual({k: v for k, v in before.items() if k not in readme_names},
                         {k: v for k, v in generated.items() if k not in readme_names})

    def test_reversed_markers_are_rejected_without_writing(self):
        final = self.readmes[-1]
        final.write_text(self.prefix + index.END + "\n损坏\n" + index.START + self.suffix)
        self.set_meta(self.m1, "title", "应等待全部预检")
        original = self.snapshot()
        for args in ((), ("--check",)):
            code, result = self.run_cli(index.main, *args)
            self.assertEqual(code, 1)
            self.assertIn("标记顺序错误", str(result["errors"]))
            self.assertEqual(result["written"], [])
            self.assertEqual(self.snapshot(), original)

    def test_late_bad_frontmatter_prevents_earlier_writes(self):
        last = self.methods / "M10_合规与风险" / "02.md"
        last.write_text("---\ninvalid: [\n---\n")
        self.set_meta(self.m1, "title", "合成修改")
        before = self.snapshot()
        code, result = self.run_cli(index.main)
        self.assertEqual(code, 1)
        self.assertEqual(result["written"], [])
        self.assertEqual(self.snapshot(), before)

    def test_method_id_from_another_module_is_rejected(self):
        self.set_meta(self.first, "method_id", "M1-99")
        self.assert_invalid("method_id 前缀与模块不一致")

    def test_duplicate_method_ids_and_non_ascii_digits_are_rejected(self):
        original = self.first.read_text()
        for value in ("M5-02", "M5-０１"):
            with self.subTest(value=value):
                self.first.write_text(original)
                self.set_meta(self.first, "method_id", value)
                self.assert_invalid("method_id")

    def test_required_method_fields_reject_invalid_types(self):
        original = self.first.read_text()
        for key, value in (("title", ["bad"]), ("适用平台", True), ("适用阶段", 42),
                           ("数据信号", {"bad": "value"}), ("method_id", None)):
            with self.subTest(key=key):
                self.first.write_text(original)
                self.set_meta(self.first, key, value)
                self.assert_invalid(key)

    def test_duplicate_yaml_keys_equal_conflicting_and_nested_are_rejected(self):
        original = self.first.read_text()
        for extra in ("method_id: M5-01\n", "method_id: M5-99\n", "nested:\n  x: first\n  x: second\n"):
            with self.subTest(extra=extra):
                self.first.write_text(original.replace("---\n", "---\n" + extra, 1))
                self.assert_invalid("YAML 字段重复")
                with self.assertRaisesRegex(kb.KBError, "第 .* 行"):
                    kb.read_doc(self.first)
                self.assertEqual(self.run_cli(query.main, "--module", "M5")[1]["status"], "invalid_kb")

    def test_unsafe_yaml_objects_remain_rejected(self):
        self.first.write_text(self.first.read_text().replace("title: 合成方法 M5-01", "title: !!python/object/apply:os.system ['synthetic-command']"))
        with patch.object(os, "system") as execute:
            self.assert_invalid("YAML 解析失败")
            execute.assert_not_called()

    def test_wrong_module_directory_is_not_counted_or_queried(self):
        wrong = self.methods / "M1_误放目录"
        wrong.mkdir()
        for path in list((self.methods / "M1_定位与赛道选择").glob("[0-9]*.md")):
            path.rename(wrong / path.name)
        result = self.assert_invalid("未登记")
        self.assertEqual(result["module_counts"]["M1"], 0)
        self.assertIn("M1: 0", str(result["errors"]))
        before = self.snapshot()
        self.assertEqual(self.run_cli(index.main)[0], 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_cli(query.main, "--module", "M1")[1]["methods"], [])

    def test_empty_unregistered_module_directory_is_rejected(self):
        (self.methods / "M1_空副本").mkdir()
        self.assert_invalid("未登记模块目录")

    def test_missing_local_zhihu_case_is_rejected(self):
        original = self.first.read_text()
        for replacement in ("没有案例。", "[外链](https://www.zhihu.com/question/0)", "[断链](../知识库/知乎知识库/missing.md)"):
            with self.subTest(replacement=replacement):
                self.first.write_text(original)
                self.replace_cases(replacement)
                self.assert_invalid("缺少有效本地知乎案例引用")

    def test_non_source_file_cannot_satisfy_case_requirement(self):
        (self.cases / "synthetic.txt").write_text("这不是来源卡。")
        self.replace_cases("[文本](../知识库/知乎知识库/synthetic.txt)")
        self.assert_invalid("缺少有效本地知乎案例引用")

    def test_source_schema_and_nonempty_body_are_required(self):
        original = self.source.read_text()
        invalid_values = (("title", ["bad"]), ("verification", True), ("author", []),
                          ("accessed_at", "not-a-date"), ("accessed_at", "2999-01-01"),
                          ("accessed_at", "2026-02-30"), ("published_at", "2026-19"))
        for key, value in invalid_values:
            with self.subTest(key=key, value=value):
                self.source.write_text(original)
                self.set_meta(self.source, key, value)
                self.assert_invalid(key)
        for body in ("", "  \n", "# 只有标题\n\n<!-- comment -->"):
            with self.subTest(body=body):
                self.write_doc(self.source, self.source_meta, body)
                self.assert_invalid("来源卡缺少非空原创摘要正文")

    def test_source_dates_and_multiple_authors_accept_documented_forms(self):
        self.set_meta(self.source, "author", ["合成作者一", "合成作者二"])
        self.set_meta(self.source, "updated_at", "2025-01")
        self.set_meta(self.source, "published_at", None)
        self.assert_valid()

    def test_source_urls_reject_non_http_userinfo_bad_hosts_and_controls(self):
        original = self.source.read_text()
        for url in ("file://www.zhihu.com/private", "javascript://www.zhihu.com/test", "//www.zhihu.com/question/0",
                    "https://synthetic-user:synthetic-secret@www.zhihu.com/question/0", "https://www.zhihu.com:bad/q",
                    "https://[invalid", "https://%5Binvalid", "https://www.zhihu.com/%00", "https://zhihu.com.evil.invalid/q"):
            with self.subTest(url=url):
                self.source.write_text(original)
                self.set_meta(self.source, "source_url", url)
                result = self.assert_invalid()
                self.assertNotIn("synthetic-secret", str(result))
                self.assertNotIn(str(self.root), str(result))

    def test_global_source_uses_same_url_rules(self):
        source = self.global_sources / "global.md"
        meta = dict(self.source_meta, source_url="https://example.org/public")
        self.write_doc(source, meta, "这是合成全球来源的测试摘要，不声称在线核验。")
        self.assert_valid()
        self.set_meta(source, "source_url", "https://synthetic:secret@example.org/public")
        self.assert_invalid("URL")

    def test_duplicate_canonical_urls_across_source_directories_are_rejected(self):
        self.write_doc(self.global_sources / "duplicate.md", self.source_meta, "同一来源不应复制为另一 canonical。")
        self.assert_invalid("重复 canonical 来源 URL")

    def test_empty_or_wrong_schema_writing_truth_is_rejected(self):
        original = self.standard.read_text()
        for text in ("", "---\ntitle: no schema\n---\n\n空壳。", original.split("---", 2)[0] + "---" + original.split("---", 2)[1] + "---\n"):
            with self.subTest(text=text[:30]):
                self.standard.write_text(text)
                self.assert_invalid()
                self.assertIn("M4 必须引用通过验证", str(validator.validate()["errors"]))

    def test_alias_resolves_to_canonical_and_is_counted_separately(self):
        self.add_alias()
        self.replace_cases("[别名](../知识库/知乎知识库/alias.md)")
        result = self.assert_valid()
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["source_alias_count"], 1)
        self.assertEqual(result["distinct_primary_source_urls"], 1)
        self.assertEqual(self.run_cli(query.main, "--module", "M5")[0], 0)

    def test_alias_chains_resolve_without_duplicate_metadata(self):
        self.add_alias("second.md")
        self.add_alias("first.md", "second.md")
        result = self.assert_valid()
        self.assertEqual(result["source_alias_count"], 2)
        self.assertEqual(result["source_count"], 1)

    def test_alias_cycles_missing_targets_escape_and_wrong_extension_rejected(self):
        for name, canonical in (("self.md", "self.md"), ("missing.md", "missing-source.md"),
                                ("escape.md", "../global.md"), ("bad.md", "synthetic.txt")):
            with self.subTest(name=name):
                alias = self.add_alias(name, canonical)
                self.assert_invalid("来源别名")
                alias.unlink()
        a = self.add_alias("a.md", "b.md")
        b = self.add_alias("b.md", "a.md")
        self.assert_invalid("循环")
        a.unlink(); b.unlink()

    def test_alias_requires_actual_link_and_forbids_copied_metadata(self):
        alias = self.add_alias()
        self.set_meta(alias, "source_url", "https://www.zhihu.com/question/0")
        self.assert_invalid("仅允许")
        alias.unlink()
        alias = self.add_alias()
        meta, _, _ = kb.read_doc(alias)
        self.write_doc(alias, meta, "只有文字，没有 canonical 链接。")
        self.assert_invalid("正文必须")

    def test_alias_to_invalid_source_cannot_satisfy_method_case(self):
        self.add_alias()
        self.replace_cases("[别名](../知识库/知乎知识库/alias.md)")
        self.set_meta(self.source, "verification", None)
        self.assert_invalid("未解析到通过验证")
        self.assertIn("缺少有效本地知乎案例引用", str(validator.validate()["errors"]))

    def test_reference_style_and_html_links_are_checked(self):
        for content in ("\n[missing][evidence]\n\n[evidence]: missing.md\n", '\n<a href="missing.md">missing</a>\n', '\n<img src="missing.png">\n'):
            with self.subTest(content=content):
                original = self.first.read_text()
                self.append(self.first, content)
                self.assert_invalid("本地链接指向不存在")
                self.first.write_text(original)
        self.replace_cases("[case][evidence]\n\n[evidence]: ../../知乎知识库/synthetic-source.md")
        self.assert_valid()

    def test_code_links_never_satisfy_actual_case_requirement(self):
        original = self.first.read_text()
        for replacement in ("`[case](../知识库/知乎知识库/synthetic-source.md)`", "```md\n[case](../知识库/知乎知识库/synthetic-source.md)\n```", "    [case](../知识库/知乎知识库/synthetic-source.md)"):
            with self.subTest(replacement=replacement):
                self.first.write_text(original)
                self.replace_cases(replacement)
                self.assert_invalid("缺少有效本地知乎案例引用")
        self.first.write_text(original)
        self.append(self.first, "\n`[missing](missing.md)`\n\n```md\n[missing](missing.md)\n```\n")
        self.assert_valid()

    def test_angle_spaces_parentheses_percent_unicode_and_fragment_links(self):
        unusual = self.first.parent / "合成 空格(1).txt"
        unusual.write_text("合成文件")
        self.append(self.first, '\n[angle](<合成 空格(1).txt>)\n[encoded](%E5%90%88%E6%88%90%20%E7%A9%BA%E6%A0%BC%281%29.txt)\n[readme](<../../../README.md>)\n[fragment](../../../README.md?test=yes#unknown-title)\n')
        self.assert_valid()
        self.assertIn("合成 空格(1).txt", [unquote(urlsplit(x).path) for x in kb.links(self.first.read_text())])

    def test_percent_encoded_traversal_is_rejected(self):
        self.append(self.first, "\n[out](%2e%2e/%2e%2e/%2e%2e/%2e%2e/outside.md)\n")
        self.assert_invalid("仓库范围")

    def test_malformed_links_return_safe_json_and_continue_to_later_errors(self):
        for bad in ("[bad](https://[invalid)", "[bad](%00.md)"):
            with self.subTest(bad=bad):
                original = self.first.read_text()
                self.append(self.first, "\n" + bad + "\n")
                later = self.methods / "M10_合规与风险" / "02.md"
                later_original = later.read_text()
                self.set_meta(later, "适用平台", None)
                code, result = self.run_cli(validator.main)
                self.assertEqual(code, 1)
                self.assertIn("链接无效", str(result["errors"]))
                self.assertIn("适用平台", str(result["errors"]))
                self.assertNotIn(str(self.root), str(result))
                self.assertNotIn("Traceback", str(result))
                self.first.write_text(original)
                later.write_text(later_original)

    def test_invalid_utf8_returns_json_instead_of_traceback(self):
        self.first.write_bytes(b'\xff\xfe\x00')
        code, result = self.run_cli(validator.main)
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", str(result["errors"]))
        self.assertNotIn(str(self.root), str(result))

    def test_symlink_readme_rejected_before_external_write(self):
        readme = self.readmes[0]
        external = Path(self.temp.name) / "outside-readme.md"
        external.write_text(readme.read_text())
        readme.unlink(); readme.symlink_to(external)
        self.set_meta(self.m1, "title", "合成修改")
        original = external.read_bytes()
        for args in ((), ("--check",)):
            code, result = self.run_cli(index.main, *args)
            self.assertEqual(code, 1)
            self.assertEqual(result["written"], [])
            self.assertEqual(external.read_bytes(), original)
            self.assertNotIn(str(external), str(result))
        self.assert_invalid()

    def test_method_and_writing_root_symlinks_are_rejected(self):
        for directory in (self.methods, self.writing):
            with self.subTest(directory=directory.name):
                external = Path(self.temp.name) / ("outside-" + directory.name)
                directory.rename(external)
                directory.symlink_to(external, target_is_directory=True)
                before = {str(p.relative_to(external)): p.read_bytes() for p in external.rglob("*") if p.is_file()}
                self.assert_invalid()
                self.assertEqual(self.run_cli(index.main)[0], 1)
                self.assertEqual(self.run_cli(query.main)[1]["status"], "invalid_kb")
                after = {str(p.relative_to(external)): p.read_bytes() for p in external.rglob("*") if p.is_file()}
                self.assertEqual(before, after)
                directory.unlink(); external.rename(directory)

    def test_inside_repo_symlink_and_late_symlink_change_are_rejected(self):
        self.set_meta(self.m1, "title", "合成修改")
        plan, errors = index.build_plan()
        self.assertEqual(errors, [])
        target = self.root / "synthetic-copy.md"
        first_readme = self.readmes[0]
        target.write_text(first_readme.read_text())
        original = target.read_bytes()
        first_readme.unlink(); first_readme.symlink_to(target)
        written, errors = index.apply_plan(plan)
        self.assertEqual(written, [])
        self.assertTrue(errors)
        self.assertEqual(target.read_bytes(), original)

    def test_query_reference_contract_resolves_actual_local_files(self):
        code, result = self.run_cli(query.main, "--limit", "50", "--full-text")
        self.assertEqual(code, 0)
        self.assertEqual(result["total_matches"], 8)
        references = 0
        for method in result["methods"]:
            self.assertEqual(method["reference_base"], "method_directory")
            method_path = self.root / method["path"]
            self.assertIn("## 诊断", method["full_text"])
            for reference in method["references"]:
                target = kb.local_target(method_path, reference)
                if target:
                    references += 1
                    self.assertTrue(target.is_relative_to(self.root))
                    self.assertTrue(target.is_file())
        self.assertGreater(references, 0)

    def test_query_keyword_casefold_no_match_and_limit(self):
        self.append(self.first, "\n这是合成 OAuth 示例。\n")
        code, result = self.run_cli(query.main, "--module", "M5", "--query", "oauth", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(len(result["methods"]), 1)
        self.assertNotIn("full_text", result["methods"][0])
        self.assertEqual(self.run_cli(query.main, "--query", "NO_SUCH_KEYWORD")[1]["status"], "no_match")

    def test_query_rejects_invalid_schema_before_returning_records(self):
        self.set_meta(self.first, "适用平台", True)
        code, result = self.run_cli(query.main, "--module", "M1")
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "invalid_kb")
        self.assertEqual(result["methods"], [])

    def test_optional_evidence_level_requires_nonempty_string(self):
        original = self.first.read_text()
        for value in (None, "", "  ", True, 42, [], {"level": "test"}):
            with self.subTest(value=value):
                self.first.write_text(original)
                self.set_meta(self.first, "evidence_level", value)
                self.assert_invalid("evidence_level 存在时必须为非空字符串")
        self.first.write_text(original)
        meta, body, _ = kb.read_doc(self.first)
        del meta["evidence_level"]
        self.write_doc(self.first, meta, body)
        self.assert_valid()
        code, result = self.run_cli(query.main, "--module", "M5", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertIsNone(result["methods"][0]["evidence_level"])

    def test_recursive_and_nonfinite_yaml_return_safe_invalid_json(self):
        original = self.first.read_text()
        for value in ("&loop [*loop]", ".nan", ".inf"):
            with self.subTest(value=value):
                changed = original.replace("evidence_level: 合成测试", f"evidence_level: {value}")
                self.assertNotEqual(changed, original)
                self.first.write_text(changed)
                self.assert_invalid("evidence_level")
                code, result = self.run_cli(query.main, "--module", "M5")
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "invalid_kb")
                self.assertEqual(result["methods"], [])
                self.assertNotIn(str(self.root), str(result))

    def test_query_serialization_errors_also_return_safe_json(self):
        recursive = []
        recursive.append(recursive)
        class Unserializable:
            def __str__(self):
                raise RuntimeError("synthetic value must not be stringified or echoed")
        for value in (recursive, float("nan"), float("inf"), Unserializable()):
            with self.subTest(value_type=type(value).__name__):
                invalid_output = {"status": "ok", "methods": [{"evidence_level": value}]}
                with patch.object(query, "query", return_value=invalid_output):
                    code, result = self.run_cli(query.main)
                self.assertEqual(code, 1)
                self.assertEqual(result["status"], "invalid_kb")
                self.assertEqual(result["methods"], [])
                self.assertTrue(result["errors"])
                self.assertNotIn("synthetic value", str(result))

    def test_image_targets_do_not_satisfy_case_or_writing_hyperlinks(self):
        original = self.first.read_text()
        for replacement in ("![case](../知识库/知乎知识库/synthetic-source.md)",
                            '<img src="../../知乎知识库/synthetic-source.md">'):
            with self.subTest(replacement=replacement):
                self.first.write_text(original)
                self.replace_cases(replacement)
                self.assert_invalid("缺少有效本地知乎案例引用")
        self.first.write_text(original)
        method = self.methods / "M4_内容生产与爆款公式" / "01.md"
        original_writing = method.read_text()
        for replacement in ("![真源](../知识库/写作表述方法论/synthetic-writing.md)",
                            '<img src="../../写作表述方法论/synthetic-writing.md">'):
            with self.subTest(replacement=replacement):
                method.write_text(original_writing.replace("[合成真源](../知识库/写作表述方法论/synthetic-writing.md)", replacement))
                self.assert_invalid("M4 必须引用通过验证的写作表述真源")

    def test_alias_requires_a_hyperlink_not_an_image(self):
        alias = self.add_alias()
        meta, _, _ = kb.read_doc(alias)
        for body in ("旧路径说明。 ![canonical](synthetic-source.md)",
                     '旧路径说明。 <img src="synthetic-source.md">'):
            with self.subTest(body=body):
                self.write_doc(alias, meta, body)
                self.assert_invalid("来源别名正文必须有指向 canonical 的实际链接")

    def test_linked_images_preserve_outer_navigation_and_query_references(self):
        (self.first.parent / "visual.png").write_bytes(b"synthetic image target")
        body = "[![说明图](visual.png)](../知识库/知乎知识库/synthetic-source.md)"
        self.replace_cases(body)
        self.assert_valid()
        destinations = kb.link_targets(body)
        self.assertEqual([kind for kind, _ in destinations], ["hyperlink", "image"])
        self.assertEqual(kb.links(body), [target for _, target in destinations])
        code, result = self.run_cli(query.main, "--module", "M5", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(result["methods"][0]["references"], kb.links(body))

    def test_image_alt_links_are_plain_text_not_navigation(self):
        (self.first.parent / "visual.png").write_bytes(b"synthetic image target")
        body = "![[case](../知识库/知乎知识库/synthetic-source.md)](visual.png)"
        self.replace_cases(body)
        self.assertEqual(kb.link_targets(body), [("image", "visual.png")])
        self.assertNotIn("<a ", kb.MARKDOWN.render(body))
        self.assert_invalid("缺少有效本地知乎案例引用")

    def test_query_invalid_arguments_exit_two(self):
        from contextlib import redirect_stderr
        for args in (("--limit", "0"), ("--limit", "51"), ("--limit", "bad"), ("--module", "M11")):
            with self.subTest(args=args), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
                query.main(list(args))
            self.assertEqual(caught.exception.code, 2)

    def test_schema_parser_errors_are_collected_per_file_without_early_exit(self):
        original_parse = kb.MARKDOWN.parse
        def fail_one(text):
            if "SYNTHETIC_PARSE_ERROR" in text:
                raise ValueError("synthetic parser error with a value that must not be echoed")
            return original_parse(text)
        for damaged in (self.first, self.source, self.standard):
            with self.subTest(damaged=damaged.name):
                original = damaged.read_text()
                self.append(damaged, "\nSYNTHETIC_PARSE_ERROR\n")
                other = self.methods / "M10_合规与风险" / "02.md"
                other_original = other.read_text()
                self.set_meta(other, "适用平台", None)
                with patch.object(kb.MARKDOWN, "parse", side_effect=fail_one):
                    code, result = self.run_cli(validator.main)
                self.assertEqual(code, 1)
                self.assertIn("Markdown 无法解析", str(result["errors"]))
                self.assertIn("适用平台", str(result["errors"]))
                self.assertNotIn("must not be echoed", str(result))
                damaged.write_text(original)
                other.write_text(other_original)

    def test_staging_io_failure_leaves_all_readmes_unchanged(self):
        real_open = index.tempfile.NamedTemporaryFile
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic temporary-file failure")
            return real_open(*args, **kwargs)
        before = self.snapshot()
        with patch.object(index.tempfile, "NamedTemporaryFile", side_effect=fail_second):
            code, result = self.run_cli(index.main)
        self.assertEqual(code, 1)
        self.assertEqual(result["written"], [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.root.rglob(".kb-filelist-*")), [])

    def test_second_replace_failure_reports_actual_written_paths(self):
        real_replace = index.os.replace
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic replace failure")
            return real_replace(*args, **kwargs)
        before = self.snapshot()
        with patch.object(index.os, "replace", side_effect=fail_second):
            code, result = self.run_cli(index.main)
        self.assertEqual(code, 1)
        self.assertEqual(result["written"], [str(self.readmes[0].relative_to(self.root))])
        changed = [name for name, value in self.snapshot().items() if before[name] != value]
        self.assertEqual(changed, result["written"])
        self.assertEqual(list(self.root.rglob(".kb-filelist-*")), [])

    def test_cleanup_failures_preserve_partial_written_and_primary_error(self):
        real_replace, real_unlink = index.os.replace, Path.unlink
        calls = 0
        def fail_second_replace(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic replacement detail must not be echoed")
            return real_replace(*args, **kwargs)
        def fail_remaining_cleanup(path, *args, **kwargs):
            if path.name.startswith(".kb-filelist-") and path.exists():
                raise PermissionError("synthetic cleanup detail must not be echoed")
            return real_unlink(path, *args, **kwargs)
        before = {p: p.read_bytes() for p in self.readmes}
        with patch.object(index.os, "replace", side_effect=fail_second_replace), patch.object(Path, "unlink", fail_remaining_cleanup):
            code, result = self.run_cli(index.main)
        self.assertEqual(code, 1)
        actual = [str(p.relative_to(self.root)) for p in self.readmes if p.read_bytes() != before[p]]
        self.assertEqual(actual, [str(self.readmes[0].relative_to(self.root))])
        self.assertEqual([w.replace("\\", "/") for w in result["written"]], [a.replace("\\", "/") for a in actual])
        self.assertEqual(result["errors"][0], "无法处理文档（OSError）")
        self.assertEqual(len(result["errors"]), len(self.readmes))
        self.assertEqual(len(list(self.root.rglob(".kb-filelist-*"))), len(self.readmes) - 1)
        self.assertNotIn("synthetic", str(result))
        self.assertNotIn(str(self.root), str(result))

    def test_cleanup_continues_after_staging_and_one_cleanup_failure(self):
        real_open, real_unlink = index.tempfile.NamedTemporaryFile, Path.unlink
        calls = 0
        cleanup_failures = 0
        def fail_third_stage(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("synthetic staging detail must not be echoed")
            return real_open(*args, **kwargs)
        def fail_first_cleanup(path, *args, **kwargs):
            nonlocal cleanup_failures
            if path.name.startswith(".kb-filelist-") and path.exists() and cleanup_failures == 0:
                cleanup_failures += 1
                raise PermissionError("synthetic cleanup detail must not be echoed")
            return real_unlink(path, *args, **kwargs)
        before = {p: p.read_bytes() for p in self.readmes}
        with patch.object(index.tempfile, "NamedTemporaryFile", side_effect=fail_third_stage), patch.object(Path, "unlink", fail_first_cleanup):
            code, result = self.run_cli(index.main)
        self.assertEqual(code, 1)
        self.assertEqual(result["written"], [])
        self.assertEqual({p: p.read_bytes() for p in self.readmes}, before)
        self.assertEqual(result["errors"][0], "无法处理文档（OSError）")
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(len(list(self.root.rglob(".kb-filelist-*"))), 1)
        self.assertNotIn("synthetic", str(result))
        self.assertNotIn(str(self.root), str(result))

    def test_alias_encoded_parent_path_is_rejected(self):
        self.add_alias(canonical="%2e%2e/知乎知识库/synthetic-source.md")
        self.assert_invalid("来源别名 canonical 不得")

    def test_filename_and_title_markup_are_escaped_in_rebuilt_filelist(self):
        renamed = self.first.with_name("合成 空格(1).md")
        self.first.rename(renamed)
        self.set_meta(renamed, "title", "合成 [标题] *带强调*")
        code, _ = self.run_cli(index.main)
        self.assertEqual(code, 0)
        readme = renamed.parent / "README.md"
        local = [kb.local_target(readme, link) for link in kb.links(readme.read_text())]
        self.assertIn(renamed, local)
        self.assert_valid()


if __name__ == "__main__":
    unittest.main()
