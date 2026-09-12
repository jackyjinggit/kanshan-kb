"""Shared, bounded readers for the single Markdown knowledge tree."""
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import ipaddress
import os
import re

from markdown_it import MarkdownIt
import yaml

ROOT = Path(__file__).resolve().parents[2]
METHODS = ROOT  # 主仓结构：方法卡在根 M1~M10/ 目录（scripts/kb/ 上一层再上一层=仓库根）
CASES = ROOT / "知识库" / "知乎知识库"
WRITING = ROOT / "知识库" / "写作表述方法论"
MODULES = {
    "M1": "定位与赛道选择", "M2": "人设与账号包装", "M3": "选题方法论", "M4": "内容生产与爆款公式",
    "M5": "平台算法与分发机制", "M6": "发布与冷启动运营", "M7": "粉丝增长与互动运营", "M8": "数据复盘与迭代",
    "M9": "变现路径", "M10": "合规与风险",
}
# 方法卡所在根（M 层）；遗落判定只对这些目录生效
METHOD_DIRS = {f"{key}_{value}" for key, value in MODULES.items()}
KB_SUBDIRS = {"知识库", "scripts", "demo", "tests", "docs", "examples", "out", "评估"}
IGNORED = {".git", ".venv", "__pycache__", "_build", "_private"}
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")


class KBError(ValueError):
    """An error safe to report without document values or absolute paths."""


def relative_name(path):
    try:
        return Path(path).relative_to(ROOT).as_posix()
    except ValueError:
        return "[仓库外路径]"


def safe_error(exc):
    if isinstance(exc, KBError):
        return str(exc)
    return f"无法处理文档（{type(exc).__name__}）"


def safe_path(path):
    """Reject symlinks in any component, including links that stay in ROOT."""
    path = Path(path).absolute()
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(ROOT):
            raise KBError("路径超出仓库范围")
        for component in (path, *path.parents):
            if component.is_symlink():
                raise KBError("不允许符号链接文件或目录")
            if component == ROOT:
                break
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, KBError):
            raise
        raise KBError("路径无法安全解析") from None
    return resolved


def read_text(path):
    target = safe_path(path)
    try:
        if target.stat().st_size > MAX_DOCUMENT_BYTES:
            raise KBError("文档超过 2 MiB 读取上限")
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise KBError("文档不可读取或不是 UTF-8") from None


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in mapping:
                raise KBError(f"YAML 字段重复（frontmatter 第 {key_node.start_mark.line + 1} 行）")
        except TypeError:
            raise KBError("YAML 字段名必须可作为映射键") from None
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_doc(path):
    text = read_text(path)
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not match:
        raise KBError("缺少 YAML frontmatter")
    try:
        meta = yaml.load(match.group(1), Loader=UniqueSafeLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"（frontmatter 第 {mark.line + 1} 行）" if mark else ""
        raise KBError(f"YAML 解析失败{location}") from None
    if not isinstance(meta, dict):
        raise KBError("frontmatter 必须是映射")
    return meta, text[match.end():], text


def repository_files():
    """Enumerate without following symlinks; preserve all errors for the caller."""
    files, errors = [], []
    def onerror(error):
        errors.append(f"{relative_name(error.filename)}: 目录无法读取")
    for directory, dirs, names in os.walk(ROOT, followlinks=False, onerror=onerror):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in list(dirs) + sorted(names):
            path = Path(directory) / name
            if name in IGNORED:
                continue
            try:
                safe_path(path)
            except KBError as exc:
                errors.append(f"{relative_name(path)}: {exc}")
                if name in dirs:
                    dirs.remove(name)
                continue
            if name not in dirs:
                files.append(path)
    return sorted(files), errors


def method_inventory():
    """All tools use exact declared directories; stray method docs are errors."""
    files, errors = repository_files()
    directories = {ROOT / f"{key}_{value}" for key, value in MODULES.items()}
    for directory in sorted(directories):
        try:
            safe_path(directory)
            if not directory.is_dir():
                errors.append(f"缺少模块：{relative_name(directory)}")
        except KBError as exc:
            errors.append(f"{relative_name(directory)}: {exc}")
    paths = []
    for path in files:
        parent_name = path.parent.name
        is_method_dir = path.parent in directories
        if not is_method_dir:
            continue
        if path.suffix != ".md":
            continue
        if path.name != "README.md":
            paths.append(path)
    return sorted(paths), errors


def method_paths():
    paths, errors = method_inventory()
    if errors:
        raise KBError("；".join(errors))
    return paths


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.targets = []

    def handle_starttag(self, tag, attrs):
        field = {"a": "href", "img": "src"}.get(tag)
        if field:
            kind = "hyperlink" if tag == "a" else "image"
            self.targets.extend((kind, value) for key, value in attrs if key == field and value is not None)

    handle_startendtag = handle_starttag


def link_targets(body):
    """Return (kind, target) for rendered hyperlinks and images, excluding code."""
    targets = []
    def collect(tokens):
        for token in tokens:
            if token.type == "link_open":
                targets.append(("hyperlink", token.attrGet("href")))
            elif token.type == "image":
                targets.append(("image", token.attrGet("src")))
            elif token.type in {"html_inline", "html_block"}:
                parser = HTMLLinks()
                parser.feed(token.content)
                targets.extend(parser.targets)
            # Image children become plain alt text, not navigable links or images.
            if token.children and token.type != "image":
                collect(token.children)
    collect(MARKDOWN.parse(body))
    return [(kind, target) for kind, target in targets if target is not None]


def links(body):
    """Keep the query contract: a string array of hyperlink and image targets."""
    return [target for _, target in link_targets(body)]


def headings(body):
    tokens = MARKDOWN.parse(body)
    return [tokens[index + 1].content for index, token in enumerate(tokens[:-1])
            if token.type == "heading_open"]


def has_prose(body):
    # A heading, comment, or empty code fence alone is not an original summary.
    tokens = MARKDOWN.parse(body)
    return any(token.type == "inline" and index > 0
               and tokens[index - 1].type != "heading_open"
               and any(child.type == "text" and child.content.strip() for child in token.children or [])
               for index, token in enumerate(tokens))


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def valid_date(value, *, partial=False, nullable=False, not_future=False):
    if value is None:
        return nullable
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        if partial and re.fullmatch(r"[0-9]{4}(?:-[0-9]{2})?", value):
            value += "-01" if len(value) == 7 else "-01-01"
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return False
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return False
    else:
        return False
    return not not_future or parsed <= date.today()


def validate_web_url(value, *, zhihu=False):
    if not nonempty(value) or any(char.isspace() for char in value):
        raise KBError("来源 URL 必须为非空且不含原始空白字符的字符串")
    try:
        decoded = unquote(value, errors="strict")
        if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
            raise ValueError()
        _ = parsed.port
        host = parsed.hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host):
                raise ValueError()
        if zhihu and not (host.lower() == "zhihu.com" or host.lower().endswith(".zhihu.com")):
            raise KBError("必须是知乎站内来源 URL")
    except (ValueError, UnicodeError):
        raise KBError("URL 必须为有效 HTTP(S) 地址且不得含凭证或控制字符") from None
    return value


def local_target(path, link):
    """Local targets stay in ROOT; fragments locate a file, not a checked heading."""
    try:
        parsed = urlsplit(link)
        decoded = unquote(parsed.path, errors="strict")
        if any(ord(char) < 32 or ord(char) == 127 for char in unquote(link, errors="strict")):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise KBError("链接 URL 或路径编码无效") from None
    if parsed.scheme or parsed.netloc:
        validate_web_url(link)
        return None
    if decoded.startswith("/") or "\\" in decoded:
        raise KBError("本地链接必须使用仓库内相对路径")
    return safe_path(path if not decoded else path.parent / decoded)


def method_errors(path, meta, body):
    errors = []
    for key in ("title", "type", "method_id", "module", "适用平台", "适用阶段", "数据信号"):
        if not nonempty(meta.get(key)):
            errors.append(f"{key} 必须为非空字符串")
    if "evidence_level" in meta and not nonempty(meta["evidence_level"]):
        errors.append("evidence_level 存在时必须为非空字符串")
    if meta.get("type") != "method":
        errors.append("type 必须为 method")
    expected = {ROOT / f"{key}_{value}": key for key, value in MODULES.items()}.get(path.parent)
    if not expected or meta.get("module") != expected:
        errors.append("module 与完整目录不一致")
    identifier = meta.get("method_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"M(?:10|[1-9])-[0-9]{2}", identifier):
        errors.append("method_id 格式错误（只允许 ASCII 数字）")
    elif identifier.split("-", 1)[0] != expected:
        errors.append("method_id 前缀与模块不一致")
    if len(body.strip()) < 350 or not has_prose(body):
        errors.append("正文过短或无有效正文，需检查是否空壳")
    section_names = headings(body)
    if any(not any(word in heading for heading in section_names) for word in ("诊断", "处方", "依据")):
        errors.append("缺少诊断、处方或依据章节")
    return errors
