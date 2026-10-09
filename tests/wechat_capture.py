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
