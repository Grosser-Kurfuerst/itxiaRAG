"""公众号本地采集目录连接器：第三方账号无法在线批量读取，人工保存网页与旁注后离线导入。

目录结构为 `<dir>/<账号目录>/<条目>.html` 加同名 `<条目>.json` 旁注，旁注字段为
title（必填）、url、date（YYYY-MM-DD）、author、account（账号显示名，缺省用目录名）。
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from contracts.errors import DomainError
from contracts.types import FetchedSource, RawDocument, SourceRef
from sources.manifest import valid_component


CATEGORIES = {"product_review", "purchase_guide"}
SIDECAR_FIELDS = {"title", "url", "date", "author", "account"}


def article_identity(url: str | None, key: str) -> tuple[str, str | None]:
    """永久链接得到稳定身份与规范链接；临时链接带签名会过期，退回采集键且不保存链接。"""
    parts = urlsplit(url or "")
    if parts.scheme in {"http", "https"} and parts.hostname == "mp.weixin.qq.com":
        query = parse_qs(parts.query)
        biz, mid, idx, sn = (query.get(name, [""])[0] for name in ("__biz", "mid", "idx", "sn"))
        if parts.path == "/s" and re.fullmatch(r"[A-Za-z0-9+/=]+", biz) and mid.isdigit() and idx.isdigit():
            params = {"__biz": biz, "mid": mid, "idx": idx, **({"sn": sn} if sn else {})}
            return f"mp:{biz}:{mid}:{idx}", "https://mp.weixin.qq.com/s?" + urlencode(params)
        match = re.fullmatch(r"/s/([A-Za-z0-9_-]+)", parts.path)
        if match:
            return f"mp:s:{match[1]}", f"https://mp.weixin.qq.com/s/{match[1]}"
    return f"wechat-capture:{key}", None


def _sidecar(path: Path, key: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DomainError("INVALID_CAPTURE", f"{key} 缺少旁注或旁注不是 UTF-8 JSON") from None
    if not isinstance(data, dict) or set(data) - SIDECAR_FIELDS:
        raise DomainError("INVALID_CAPTURE", f"{key} 旁注必须是对象，字段限于 {', '.join(sorted(SIDECAR_FIELDS))}")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise DomainError("INVALID_CAPTURE", f"{key} 旁注缺少标题")
    if any(data.get(name) is not None and not isinstance(data[name], str) for name in SIDECAR_FIELDS):
        raise DomainError("INVALID_CAPTURE", f"{key} 旁注字段必须是文本")
    if data.get("date") is not None:
        try:
            date.fromisoformat(data["date"])
        except ValueError:
            raise DomainError("INVALID_CAPTURE", f"{key} 旁注 date 必须是 YYYY-MM-DD") from None
    return data


class WechatCaptureConnector:
    source_type = "wechat"

    def __init__(self, root, accounts: list[str]):
        self.root, self.accounts = Path(root), accounts

    def list(self) -> list[SourceRef]:
        refs = []
        for account in self.accounts:
            directory = self.root / account
            if not valid_component(account) or not directory.is_dir():
                raise DomainError("INVALID_CAPTURE", f"采集目录缺少账号目录：{account}")
            for page in sorted(directory.glob("*.html")):
                key = f"{account}/{page.stem}"
                if not valid_component(page.stem):
                    raise DomainError("INVALID_CAPTURE", f"采集文件名非法：{page.name}")
                sidecar = _sidecar(page.with_suffix(".json"), key)
                canonical, url = article_identity(sidecar.get("url"), key)
                refs.append(SourceRef(
                    collection=account, key=key, canonical_locator=canonical, title=sidecar["title"].strip(),
                    extra={"source_url": url, "date": sidecar.get("date"),
                           "account": sidecar.get("account") or account, "author": sidecar.get("author")},
                ))
        return refs

    def fetch(self, ref: SourceRef) -> FetchedSource:
        path = self.root / ref.collection / (ref.key.split("/", 1)[1] + ".html")
        try:
            content = path.read_bytes()
        except OSError:
            raise DomainError("CAPTURE_READ_FAILED", f"无法读取采集网页：{ref.key}.html") from None
        extra = ref.extra
        metadata = {"title": ref.title}
        if extra["date"]:
            metadata["source_date"] = extra["date"]
        metadata["wechat"] = {name: extra[name] for name in ("account", "author") if extra[name]}
        return FetchedSource(ref, RawDocument(content, "text/html", metadata), extra["source_url"])
