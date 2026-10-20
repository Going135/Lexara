# -*- coding: utf-8 -*-
"""启动台主题的**网页调参台**（本地，127.0.0.1）。

命令行改颜色还是要点记性：`btn.primaryHoverBg` 到底比 `btn.primaryBg` 深多少？
这个页面把 81 个令牌按组摊开，颜色一个色块点开就是取色器，尺寸是滑杆，改完
立刻写回 theme.json —— 启动器那边 200ms 内自己重绘，不用重启。

    python tools/theme_live.py                 # 打开 http://127.0.0.1:8765
    python tools/theme_live.py --port 9000
    python tools/theme_live.py --no-open       # 不自动弹浏览器
    python tools/theme_live.py --theme my.json # 调另一份主题

安全边界
--------
只绑 `127.0.0.1`，只允许读写**这一份** theme.json，不做目录遍历、不接受任意
路径参数。它是个本地开发工具，不该有半个网络攻击面。
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import ui_theme                                              # noqa: E402

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>LEXARA 主题调参台</title>
<style>
  :root{
    --bg:#12171a; --panel:#1a2124; --panel2:#212a2e; --line:#2e3a3f;
    --ink:#eef2f0; --muted:#96a3a4; --accent:#5ea9ff; --ok:#4fbf8b; --warn:#e0b062;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:13px/1.5 "Segoe UI","Microsoft YaHei UI",system-ui,sans-serif}
  header{position:sticky;top:0;z-index:5;background:rgba(18,23,26,.94);
         backdrop-filter:blur(10px);border-bottom:1px solid var(--line);
         padding:14px 20px 10px}
  h1{margin:0;font-size:15px;font-weight:650;letter-spacing:.3px}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;
       font-family:ui-monospace,Consolas,monospace;word-break:break-all}
  .bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
  input[type=search]{flex:1 1 180px;min-width:140px}
  input,select,button{background:var(--panel2);color:var(--ink);
       border:1px solid var(--line);border-radius:7px;padding:6px 9px;font:inherit}
  input:focus,select:focus{outline:1px solid var(--accent);border-color:var(--accent)}
  button{cursor:pointer}
  button:hover{border-color:#43555c}
  button.primary{background:#1d3b2c;border-color:#2f6047;color:#cfe9da}
  button.danger{background:#3a2220;border-color:#5a3230;color:#f0d3d0}
  .pill{font-size:11px;color:var(--muted);border:1px solid var(--line);
        border-radius:99px;padding:3px 9px}
  .pill.on{color:#bfe8d2;border-color:#2f6047;background:#16281f}
  main{padding:6px 20px 60px}
  section{margin-top:18px}
  h2{font-size:12.5px;color:var(--muted);font-weight:600;letter-spacing:.12em;
     text-transform:uppercase;margin:0 0 8px;padding-left:2px}
  .row{display:grid;grid-template-columns:150px 1fr 150px;gap:10px;
       align-items:center;padding:7px 10px;border-radius:9px;border:1px solid transparent}
  .row:hover{background:var(--panel)}
  .row.changed{background:#17251f;border-color:#274434}
  .name{font-weight:600}
  .key{display:block;color:#7b8a8b;font-family:ui-monospace,Consolas,monospace;
       font-size:10.5px;margin-top:1px}
  .desc{color:var(--muted);font-size:11px;margin-top:2px}
  .ctl{display:flex;gap:8px;align-items:center}
  input[type=color]{width:34px;height:30px;padding:0;border-radius:7px;
       background:none;cursor:pointer}
  input.hex{width:104px;font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
  input[type=range]{flex:1;accent-color:var(--accent)}
  input.num{width:74px;font-family:ui-monospace,Consolas,monospace}
  .ref{font-size:10.5px;color:#c9a86a;border:1px dashed #5d4a26;border-radius:99px;
       padding:1px 7px;white-space:nowrap}
  .right{display:flex;gap:8px;justify-content:flex-end;align-items:center}
  .reset{border:1px solid var(--line);background:transparent;color:var(--muted);
       font-size:11px;padding:4px 8px;border-radius:6px}
  .reset:hover{color:var(--ink);border-color:#43555c}
  #toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);
       background:#1f2a2e;border:1px solid var(--line);border-radius:9px;
       padding:9px 16px;font-size:12px;opacity:0;transition:opacity .18s;pointer-events:none}
  #toast.show{opacity:1}
  #toast.err{border-color:#5a3230;color:#f0d3d0}
  .empty{color:var(--muted);padding:24px 4px}
  footer{color:#5d6a6b;font-size:11px;padding:0 20px 30px}
</style>
</head>
<body>
<header>
  <h1>LEXARA 主题调参台</h1>
  <div class="sub" id="path">读取中…</div>
  <div class="bar">
    <input type="search" id="q" placeholder="搜键名 / 中文名，例如 primary、按钮">
    <select id="group"><option value="">全部分组</option></select>
    <select id="preset">
      <option value="">套用预设…</option>
    </select>
    <span class="pill" id="count">改过 0 处</span>
    <button class="danger" id="resetAll">全部恢复默认</button>
  </div>
</header>
<main id="main"></main>
<footer>改完即写入 theme.json；运行中的启动器会在 0.2 秒内自动重绘。</footer>
<div id="toast"></div>

<script>
let STATE = null;
const $ = (sel) => document.querySelector(sel);

function toast(text, isError) {
  const el = $("#toast");
  el.textContent = text;
  el.className = "show" + (isError ? " err" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.className = ""; }, 1600);
}

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function fillColor(value) {
  // 只给取色器 6 位：8 位（带 alpha）的颜色先退化到 RGB，透明度用滑杆另调
  let text = String(value || "#000000").replace("#", "");
  if (text.length === 3) text = text.split("").map((c) => c + c).join("");
  if (text.length === 8) text = text.slice(2);
  return "#" + (text.length === 6 ? text : "000000");
}

function rowFor(token) {
  const row = document.createElement("div");
  row.className = "row" + (token.changed ? " changed" : "");
  row.dataset.key = token.key;

  const left = document.createElement("div");
  left.innerHTML = '<div class="name">' + token.label + '</div>' +
                   '<span class="key">' + token.key + '</span>';
  row.appendChild(left);

  const ctl = document.createElement("div");
  ctl.className = "ctl";
  const desc = document.createElement("div");
  desc.className = "desc";
  desc.textContent = token.desc;

  if (token.kind === "color") {
    const picker = document.createElement("input");
    picker.type = "color";
    picker.value = fillColor(token.value);
    const hex = document.createElement("input");
    hex.className = "hex";
    hex.value = token.value;
    hex.spellcheck = false;
    picker.oninput = () => { hex.value = picker.value.toUpperCase(); commit(token.key, hex.value); };
    hex.onchange = () => { commit(token.key, hex.value.trim()); };
    ctl.appendChild(picker); ctl.appendChild(hex);
    if (token.raw && String(token.raw).startsWith("@")) {
      const ref = document.createElement("span");
      ref.className = "ref";
      ref.textContent = "跟随 " + token.raw;
      ref.title = "改这个值会断开跟随，变成固定颜色";
      ctl.appendChild(ref);
    }
  } else {
    const ui = token.ui || {min: 0, max: 100, step: 1};
    const range = document.createElement("input");
    range.type = "range";
    range.min = ui.min; range.max = ui.max; range.step = ui.step;
    range.value = token.value;
    const num = document.createElement("input");
    num.className = "num"; num.type = "number";
    num.min = ui.min; num.max = ui.max; num.step = ui.step;
    num.value = token.value;
    range.oninput = () => { num.value = range.value; commit(token.key, range.value); };
    num.onchange = () => { commit(token.key, num.value); };
    ctl.appendChild(range); ctl.appendChild(num);
  }
  desc.textContent = token.desc;
  ctl.appendChild(desc);
  row.appendChild(ctl);

  const right = document.createElement("div");
  right.className = "right";
  const btn = document.createElement("button");
  btn.className = "reset";
  btn.textContent = "默认";
  btn.title = "恢复这一项的默认值：" + token.default;
  btn.onclick = async () => {
    try { await api("/api/reset", {key: token.key}); await refresh(); toast("已恢复 " + token.label); }
    catch (error) { toast(error.message, true); }
  };
  right.appendChild(btn);
  row.appendChild(right);
  return row;
}

let pending = {};
function commit(key, value) {
  clearTimeout(pending[key]);
  pending[key] = setTimeout(async () => {
    try {
      await api("/api/set", {key: key, value: value});
      const row = document.querySelector('.row[data-key="' + key + '"]');
      if (row) row.classList.add("changed");
      toast("已写入 " + key + " = " + value);
      const state = await api("/api/state");
      $("#count").textContent = "改过 " + state.changedCount + " 处";
    } catch (error) {
      toast(error.message, true);
    }
  }, 120);
}

function render() {
  const main = $("#main");
  main.innerHTML = "";
  const needle = $("#q").value.trim().toLowerCase();
  const only = $("#group").value;
  let shown = 0;
  for (const group of STATE.groups) {
    if (only && group.key !== only) continue;
    const tokens = group.tokens.filter((token) =>
      !needle || token.key.toLowerCase().includes(needle) ||
      token.label.toLowerCase().includes(needle) ||
      (token.desc || "").toLowerCase().includes(needle));
    if (!tokens.length) continue;
    const section = document.createElement("section");
    const h2 = document.createElement("h2");
    h2.textContent = group.label + " · " + tokens.length;
    section.appendChild(h2);
    tokens.forEach((token) => section.appendChild(rowFor(token)));
    main.appendChild(section);
    shown += tokens.length;
  }
  if (!shown) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "没有匹配的令牌。";
    main.appendChild(empty);
  }
  $("#path").textContent = STATE.path + "　（" + STATE.total + " 个令牌）";
  $("#count").textContent = "改过 " + STATE.changedCount + " 处";
  $("#count").className = "pill" + (STATE.changedCount ? " on" : "");
}

async function refresh() {
  STATE = await api("/api/state");
  const group = $("#group");
  if (group.options.length <= 1) {
    for (const item of STATE.groups) {
      const option = document.createElement("option");
      option.value = item.key; option.textContent = item.label;
      group.appendChild(option);
    }
    const preset = $("#preset");
    for (const item of STATE.presets) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.label + (item.name === STATE.preset ? "（当前）" : "");
      preset.appendChild(option);
    }
  }
  render();
}

$("#q").oninput = render;
$("#group").onchange = render;
$("#preset").onchange = async (event) => {
  const name = event.target.value;
  if (!name) return;
  try { await api("/api/preset", {name: name}); await refresh(); toast("已套用预设 " + name); }
  catch (error) { toast(error.message, true); }
  event.target.value = "";
};
$("#resetAll").onclick = async () => {
  if (!confirm("把所有自定义值清掉，回到默认配色？")) return;
  try { await api("/api/reset", {all: true}); await refresh(); toast("已恢复默认"); }
  catch (error) { toast(error.message, true); }
};

refresh().catch((error) => { $("#path").textContent = "读取失败：" + error.message; });
</script>
</body>
</html>
"""


def state_payload(path: str) -> dict:
    raw, problems = ui_theme.read_raw(path)
    values = ui_theme.resolve_refs(raw)
    changed = ui_theme.diff(values)
    groups = []
    for group, label, tokens in ui_theme.GROUPS:
        rows = []
        for token in tokens:
            key = token["key"]
            rows.append({
                "key": key,
                "label": token["label"],
                "desc": token["desc"],
                "kind": token["kind"],
                "ui": token.get("ui"),
                "value": values.get(key),
                "raw": raw.get(key),
                "default": token["default"],
                "changed": key in changed,
            })
        groups.append({"key": group, "label": label, "tokens": rows})

    preset_names = []
    for name, (label, overrides) in ui_theme.PRESETS.items():
        target = ui_theme.resolve_refs({**ui_theme.DEFAULT_VALUES, **overrides})
        preset_names.append({"name": name, "label": label,
                             "current": values == target})

    return {
        "path": path,
        "total": len(ui_theme.SPEC),
        "changedCount": len(changed),
        "groups": groups,
        "problems": problems,
        "presets": preset_names,
        "preset": next((item["name"] for item in preset_names if item["current"]), ""),
    }


class Handler(BaseHTTPRequestHandler):
    theme_path = ""

    # ---- 基础 -----------------------------------------------------------
    def log_message(self, fmt, *args):        # 静音默认访问日志，只报错误
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    # ---- 路由 -----------------------------------------------------------
    def do_GET(self):                          # noqa: N802 —— BaseHTTPRequestHandler 约定
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path.startswith("/api/state"):
            self._json(200, state_payload(self.theme_path))
            return
        self._json(404, {"error": "没有这个地址"})

    def do_POST(self):                         # noqa: N802
        payload = self._body()
        if self.path == "/api/set":
            key = str(payload.get("key") or "")
            value = payload.get("value")
            if key not in ui_theme.SPEC:
                self._json(400, {"error": "没有这个键：%s" % key})
                return
            coerced, error = ui_theme.coerce(key, value, strict=True)
            if error:
                self._json(400, {"error": error})
                return
            raw, _ = ui_theme.read_raw(self.theme_path)
            raw[key] = coerced
            ui_theme.write_file(self.theme_path, raw)
            self._json(200, {"ok": key, "value": coerced})
            return
        if self.path == "/api/reset":
            raw, _ = ui_theme.read_raw(self.theme_path)
            if payload.get("all"):
                raw = dict(ui_theme.DEFAULT_VALUES)
            else:
                key = str(payload.get("key") or "")
                if key not in ui_theme.SPEC:
                    self._json(400, {"error": "没有这个键：%s" % key})
                    return
                raw[key] = ui_theme.SPEC[key]["default"]
            ui_theme.write_file(self.theme_path, raw)
            self._json(200, {"ok": True})
            return
        if self.path == "/api/preset":
            name = str(payload.get("name") or "")
            if name not in ui_theme.PRESETS:
                self._json(400, {"error": "没有预设：%s" % name})
                return
            _label, overrides = ui_theme.PRESETS[name]
            raw = dict(ui_theme.DEFAULT_VALUES)
            raw.update(overrides)
            ui_theme.write_file(self.theme_path, raw)
            self._json(200, {"ok": name})
            return
        self._json(404, {"error": "没有这个接口"})


def serve(path: str, port: int, open_browser: bool) -> int:
    ui_theme.ensure_file(path)
    Handler.theme_path = path
    server = None
    last_error = None
    for offset in range(12):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port + offset), Handler)
            break
        except OSError as error:
            last_error = error
    if server is None:
        print("端口 %d 起不来：%s" % (port, last_error))
        return 1
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("主题文件：%s" % path)
    print("调参台：  %s" % url)
    print("（Ctrl+C 退出；启动器开着的话改完就能看到）")
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止。")
    finally:
        server.server_close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="theme_live.py",
        description="LEXARA 启动台主题的网页调参台（本地 127.0.0.1）")
    parser.add_argument("--theme", metavar="PATH", help="主题文件（默认同 theme_tool）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)
    return serve(args.theme or ui_theme.default_path(), args.port, not args.no_open)


if __name__ == "__main__":
    sys.exit(main())
