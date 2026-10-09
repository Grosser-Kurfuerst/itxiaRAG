"""搜狗微信搜索客户端：按标题找文章、解析跳转并下载网页。

页面格式均非公开，解析失败按单篇报错；出现验证码时整批终止。
"""
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from contracts.errors import DomainError, SourceAccessError


BASE = "https://weixin.sogou.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class SogouBlockedError(SourceAccessError):
    def __init__(self):
        super().__init__("搜狗要求验证码，请稍后重跑；已下载的文章会跳过")


@dataclass(frozen=True)
class SearchHit:
    title: str
    account: str
    date: str | None
    link: str


@dataclass(frozen=True)
class Article:
    html: str
    account: str
    url: str
    date: str


def _date(timestamp: str) -> str:
    return datetime.fromtimestamp(int(timestamp), ZoneInfo("Asia/Shanghai")).date().isoformat()


def _var(page: str, name: str) -> str:
    match = re.search(rf'var {name} = (?:htmlDecode\()?"([^"]*)"', page)
    if not match or not match[1]:
        raise DomainError("WECHAT_PARSE_FAILED", f"文章网页缺少 {name}")
    return html.unescape(match[1])


class SogouWechatClient:
    def __init__(self, *, interval=3.0, timeout=20, opener=None):
        self.opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))
        self.interval, self.timeout = interval, timeout
        self._last = None
        self._search_url = None

    def _get(self, url, referer=None) -> str:
        if self._last is not None:
            time.sleep(max(0.0, self._last + self.interval - time.monotonic()))
        headers = {"User-Agent": USER_AGENT, **({"Referer": referer} if referer else {})}
        try:
            with self.opener.open(Request(url, headers=headers), timeout=self.timeout) as response:
                final, body = response.geturl(), response.read().decode("utf-8", "replace")
        except (URLError, HTTPException, OSError) as exc:
            raise DomainError("WECHAT_FETCH_FAILED", f"请求失败：{exc}") from None
        finally:
            self._last = time.monotonic()
        if "antispider" in final or "antispider" in body:
            raise SogouBlockedError()
        return body

    def search(self, query: str) -> list[SearchHit]:
        if self._search_url is None:
            self._get(BASE + "/")  # 首页下发后续请求需要的 cookie
        self._search_url = f"{BASE}/weixin?" + urlencode({"type": 2, "query": query})
        page = self._get(self._search_url)
        hits = []
        for item in re.findall(r'<li id="sogou_vr_11002601_box_\d+".*?</li>', page, re.S):
            title = re.search(r"<h3>(.*?)</h3>", item, re.S)
            link = re.search(r'<h3>\s*<a[^>]*href="(/link\?url=[^"]+)"', item)
            account = re.search(r'class="all-time-y2"[^>]*>([^<]*)<', item)
            stamp = re.search(r"timeConvert\('(\d+)'\)", item)
            if title and link and account:
                hits.append(SearchHit(
                    title=html.unescape(re.sub(r"<[^>]+>", "", title[1])).strip(),
                    account=html.unescape(account[1]).strip(),
                    date=_date(stamp[1]) if stamp else None,
                    link=html.unescape(link[1]).replace(" ", "%20"),
                ))
        return hits

    def download(self, hit: SearchHit) -> Article:
        jump = self._get(BASE + hit.link, referer=self._search_url)
        pieces = re.findall(r"url \+= '([^']*)'", jump)
        if not pieces:
            raise DomainError("WECHAT_PARSE_FAILED", "搜狗跳转页格式无法识别")
        page = self._get("".join(pieces))
        if 'id="js_content"' not in page:
            raise DomainError("WECHAT_PARSE_FAILED", "文章网页缺少正文")
        biz, mid, idx = (_var(page, name) for name in ("biz", "mid", "idx"))
        # 临时链接会过期且拿不到 sn，只保留可去重的 __biz/mid/idx。
        return Article(
            html=re.sub(r"<(script|style)\b.*?</\1\s*>", "", page, flags=re.S | re.I),
            account=_var(page, "nickname"),
            url="https://mp.weixin.qq.com/s?" + urlencode({"__biz": biz, "mid": mid, "idx": idx}),
            date=_date(_var(page, "ct")),
        )
