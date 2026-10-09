"""公众号采集目录的合成样本，供单元与集成测试共用；不含真实文章。"""
import json


REVIEW_HTML = ('<html><body><div id="js_content"><h2>合成笔记本 A</h2><p><strong>配置</strong></p><p>16GB 内存。</p>'
               '<p><strong>续航</strong></p><p>续航约 9 小时。</p></div></body></html>')
GUIDE_HTML = ('<div id="js_content"><h1>合成选购指南</h1><h2>6000元</h2><h3>合成笔记本 A</h3><p>续航好。</p>'
              '<h3>合成笔记本 B</h3><p>游戏快。</p></div>')
PERMANENT = "https://mp.weixin.qq.com/s?__biz=MzA5MDAwMDAwMA==&mid=2650000001&idx=2&sn=abc123&chksm=x&scene=21"


def write(directory, name, html, **sidecar):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.html").write_text(html, encoding="utf-8")
    (directory / f"{name}.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")


def build_capture(tmp_path):
    root = tmp_path / "capture"
    account = root / "synthetic-lab"
    write(account, "2026-09-28-review", REVIEW_HTML, title="合成评测：笔记本 A", url=PERMANENT,
          date="2026-09-28", author="合成作者", account="合成评测室")
    write(account, "2026-09-30-guide", GUIDE_HTML, title="合成选购指南",
          url="https://mp.weixin.qq.com/s/AbC-123_x")
    write(account, "2026-10-01-reprint", "<p>合成转载</p>", title="合成转载评测")
    write(account, "2026-10-02-new", "<p>合成新文章</p>", title="未登记文章")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('''version = 2
source_type = "wechat"
[collections.synthetic-lab]
visibility = "internal"
[docs."synthetic-lab/2026-09-28-review"]
category = "product_review"
metadata = { entity_title = "合成笔记本 A" }
[docs."synthetic-lab/2026-09-30-guide"]
category = "purchase_guide"
visibility = "public"
[docs."synthetic-lab/2026-10-01-reprint"]
skip = "reprint"
''', encoding="utf-8")
    return root, manifest


SEARCH_PAGE = '''<ul>
<li id="sogou_vr_11002601_box_0"><div class="txt-box"><h3><a href="/link?url=AAA&amp;query=合成 评测">合成评测<em>:笔记本</em> A</a></h3>
<div class="s-p"><span class="all-time-y2">合成评测室</span><span class="s2"><script>document.write(timeConvert('1790560814'))</script></span></div></div></li>
<li id="sogou_vr_11002601_box_1"><div class="txt-box"><h3><a href="/link?url=BBB">合成评测：笔记本 A</a></h3>
<div class="s-p"><span class="all-time-y2">合成评测室</span><span class="s2"><script>document.write(timeConvert('1700000000'))</script></span></div></div></li>
<li id="sogou_vr_11002601_box_2"><div class="txt-box"><h3><a href="/link?url=CCC">合成评测：笔记本 A</a></h3>
<div class="s-p"><span class="all-time-y2">转载号</span></div></div></li>
</ul>'''
JUMP_PAGE = "<script>var url = '';\nurl += 'https://mp.';\nurl += 'weixin.qq.com/s?src=11&signature=x';\n</script>"
ARTICLE_PAGE = ('<html><head><style>p { color: red; }</style><script>var biz = "MzA5MDAwMDAwMA==" || "";\n'
                'var mid = "2650000001" || "" || "";\nvar idx = "2" || "" || "";\nvar ct = "1790560814";\n'
                'var nickname = htmlDecode("合成评测室");</script></head><body>' + REVIEW_HTML[12:])
FETCH_MANIFEST = '''version = 2
source_type = "wechat"
[connector.accounts]
synthetic-lab = "合成评测室"
[connector.articles]
"synthetic-lab/2026-09-28-review" = { title = "合成评测：笔记本 A", date = "2026-09-28" }
[collections.synthetic-lab]
visibility = "internal"
[docs."synthetic-lab/2026-09-28-review"]
category = "product_review"
metadata = { entity_title = "合成笔记本 A" }
'''
