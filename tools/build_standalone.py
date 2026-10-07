"""把 design/*.dc.html（Claude 設計畫布格式）轉成可直接開啟的一般網頁。

用法：python3 tools/build_standalone.py
輸出：index.html（生成器）、poster.html（A4 安全約定海報）
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 畫布上傳資源 → 專案內的檔案
BLOBS = {
    "/_blob/b81c5ad41c5b3691b830031d44b94cc4": "images/classroom.jpg",
    "/_blob/c3234ec18454ebe0eeb28007556fdd93": "images/hero.svg",
    "/_blob/5035b591407472fdbbe96a9567600589": "vendor/jspdf.umd.min.js",
    "/_blob/2d547069a9ac516de225c37563b79edb": "vendor/pptxgen.bundle.js",
}

# 迷你執行環境：支援 {{hole}}、<sc-for>、<sc-if>、onClick/onChange 與 setState 重繪
RUNTIME = r"""
(function () {
  var SVG = 'http://www.w3.org/2000/svg';
  var HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  var WHOLE = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/;
  function lookup(expr, scopes) {
    if (expr === 'true') return true;
    if (expr === 'false') return false;
    if (expr === 'null') return null;
    if (/^-?\d+(\.\d+)?$/.test(expr)) return Number(expr);
    var parts = expr.split('.');
    for (var i = scopes.length - 1; i >= 0; i--) {
      var s = scopes[i];
      if (s && typeof s === 'object' && parts[0] in s) {
        var v = s;
        for (var k = 0; k < parts.length; k++) { if (v == null) return undefined; v = v[parts[k]]; }
        return v;
      }
    }
    return undefined;
  }
  function interp(str, scopes) {
    return str.replace(HOLE, function (_, e) { var v = lookup(e, scopes); return v == null ? '' : String(v); });
  }
  function setAttr(el, name, val, scopes) {
    if (name.indexOf('hint-') === 0) return;
    var m = val.match(WHOLE);
    if (m) {
      var v = lookup(m[1], scopes);
      if (name.indexOf('on') === 0) {
        if (typeof v !== 'function') return;
        var ev = name.slice(2);
        if (ev === 'change' && el.localName === 'input' && el.type !== 'range') ev = 'input';
        el.addEventListener(ev, v);
        return;
      }
      if (name === 'disabled') { el.disabled = !!v; return; }
      if (name === 'value') { el.value = v == null ? '' : v; el.setAttribute('value', v == null ? '' : String(v)); return; }
      el.setAttribute(name, v == null ? '' : String(v));
      return;
    }
    el.setAttribute(name, interp(val, scopes));
  }
  function walk(src, scopes, out) {
    var kids = (src.content || src).childNodes;
    for (var i = 0; i < kids.length; i++) {
      var n = kids[i];
      if (n.nodeType === 3) { out.appendChild(document.createTextNode(interp(n.data, scopes))); continue; }
      if (n.nodeType !== 1) continue;
      var tag = n.localName;
      if (tag === 'sc-for') {
        var list = lookup((n.getAttribute('list').match(WHOLE) || [0, ''])[1], scopes) || [];
        var as = n.getAttribute('as') || 'item';
        for (var j = 0; j < list.length; j++) { var sc = { $index: j }; sc[as] = list[j]; walk(n, scopes.concat([sc]), out); }
        continue;
      }
      if (tag === 'sc-if') {
        if (lookup((n.getAttribute('value').match(WHOLE) || [0, 'false'])[1], scopes)) walk(n, scopes, out);
        continue;
      }
      var el = n.namespaceURI === SVG ? document.createElementNS(SVG, tag) : document.createElement(tag);
      if (tag === 'input') { var t = n.getAttribute('type'); if (t) el.type = t; }
      for (var a = 0; a < n.attributes.length; a++) setAttr(el, n.attributes[a].name, n.attributes[a].value, scopes);
      walk(n, scopes, el);
      out.appendChild(el);
    }
  }
  var comp, root, tpl, pending = false;
  function render() {
    pending = false;
    var ae = document.activeElement, fid = ae && ae.id, ss = null;
    try { ss = ae && ae.selectionStart; } catch (e) {}
    var frag = document.createDocumentFragment();
    walk(tpl, [comp.renderVals()], frag);
    root.replaceChildren(frag);
    if (fid) {
      var f = document.getElementById(fid);
      if (f) { f.focus({ preventScroll: true }); try { if (ss != null) f.setSelectionRange(ss, ss); } catch (e) {} }
    }
  }
  window.DCLogic = function DCLogic(props) { this.props = props || {}; this.state = {}; };
  window.DCLogic.prototype.setState = function (p) {
    Object.assign(this.state, typeof p === 'function' ? p(this.state) : p);
    if (!pending) { pending = true; Promise.resolve().then(render); }
  };
  window.DCLogic.prototype.forceUpdate = function () { render(); };
  // 下載：一般瀏覽器直接存檔
  window.claude = {
    use: function (name) {
      if (name !== 'downloads') return Promise.resolve(null);
      return Promise.resolve({
        save: function (req) {
          var blob = req.data instanceof Blob ? req.data : new Blob([req.data]);
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob); a.download = req.filename;
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
          return Promise.resolve({ status: 'saved' });
        }
      });
    }
  };
  window.__mountDC = function (Component) {
    tpl = document.getElementById('dc-template');
    root = document.getElementById('dc-root');
    comp = new Component({});
    render();
    if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
  };
})();
"""


def build(src_name, out_name):
    src = (ROOT / "design" / src_name).read_text(encoding="utf-8")
    for blob, local in BLOBS.items():
        src = src.replace(blob, local)
    title = re.search(r"<title>(.*?)</title>", src, re.S).group(1).strip()
    lang = re.search(r'<html lang="([^"]+)"', src).group(1)
    head_scripts = re.findall(r'<script src="(vendor/[^"]+)"></script>', src)
    xdc = re.search(r"<x-dc>(.*?)</x-dc>", src, re.S).group(1)
    helmet = re.search(r"<helmet>(.*?)</helmet>", xdc, re.S).group(1)
    body_tpl = re.sub(r"<helmet>.*?</helmet>", "", xdc, flags=re.S)
    logic = re.search(r"<script type=\"text/x-dc\" data-dc-script[^>]*>(.*?)</script>", src, re.S).group(1)
    scripts = "".join(f'<script src="{s}" defer></script>\n' for s in head_scripts)
    html = f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<!-- 由 tools/build_standalone.py 從 design/{src_name} 產生，請改原檔後重新產生 -->
{helmet.strip()}
{scripts}</head>
<body>
<div id="dc-root"></div>
<template id="dc-template">{body_tpl}</template>
<script>{RUNTIME}</script>
<script>{logic}
window.__mountDC(Component);
</script>
</body>
</html>
"""
    (ROOT / out_name).write_text(html, encoding="utf-8")
    print("wrote", out_name)


if __name__ == "__main__":
    build("Main.dc.html", "index.html")
    build("SafetyPoster.dc.html", "poster.html")
