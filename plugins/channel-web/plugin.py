"""channel-web: a LAN chat bridge — talk to JARVIS from your phone's browser.

Serves a minimal chat page on http://<mac-ip>:8237 (0.0.0.0, so any device
on the same Wi-Fi can reach it). Zero external services — pure stdlib HTTP.

Run with:  uv run jarvis web
Then open http://<this-mac-ip>:8237 on your phone.

Session "web" keeps its own history (memory-sql), while cross-session facts
(mem.store/recall) are shared with every other channel.
"""
from __future__ import annotations

import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.types import KernelApi

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS</title>
<style>
  body{margin:0;background:#0d1117;color:#e6edf3;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;display:flex;flex-direction:column;height:100vh}
  #log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px}
  .msg{padding:10px 14px;border-radius:12px;white-space:pre-wrap;word-break:break-word;max-width:88%;line-height:1.5}
  .user{align-self:flex-end;background:#1f6feb;color:#fff}
  .jarvis{align-self:flex-start;background:#21262d;border:1px solid #30363d;color:#e6edf3}
  .who{font-size:11px;opacity:.65;margin-bottom:3px}
  #row{display:flex;gap:8px;padding:12px;border-top:1px solid #30363d;background:#161b22}
  #in{flex:1;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:10px;padding:10px 12px;font-size:16px}
  #btn{background:#238636;color:#fff;border:0;border-radius:10px;padding:10px 20px;font-size:16px}
  #btn:disabled{opacity:.5}
</style></head><body>
<div id="log"><div class="msg jarvis"><div class="who">jarvis</div>你好，我是 JARVIS。用局域网聊天，随时找我。</div></div>
<div id="row"><input id="in" placeholder="跟 JARVIS 说点什么…"><button id="btn" onclick="send()">发送</button></div>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),btn=document.getElementById('btn');
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function add(cls,who,html){const d=document.createElement('div');d.className='msg '+cls;d.innerHTML='<div class="who">'+who+'</div>'+html;log.appendChild(d);log.scrollTop=log.scrollHeight;}
async function send(){
  const t=inp.value.trim(); if(!t) return;
  add('user','you',esc(t)); inp.value=''; inp.disabled=true; btn.disabled=true;
  add('jarvis','jarvis…','');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});
    const j=await r.json();
    const m=log.lastChild;
    m.innerHTML='<div class="who">jarvis</div>'+(j.reply?esc(j.reply):'<i>(无回复)</i>');
  }catch(e){
    log.lastChild.innerHTML='<div class="who">jarvis</div>[web] 连接失败: '+esc(String(e));
  }
  inp.disabled=false; btn.disabled=false; inp.focus();
}
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
inp.focus();
</script></body></html>"""


def _lan_ip() -> str:
    """Pick the real LAN IPv4 (skip loopback/VPN/APIPA ranges)."""
    import re
    import subprocess

    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3).stdout
        for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)", out):
            ip = m.group(1)
            if ip.startswith(("127.", "169.254.", "198.18.", "0.")):
                continue
            return ip
    except Exception:  # noqa: BLE001
        pass
    return "127.0.0.1"


def _serve(kernel: KernelApi, port: int) -> None:
    class _H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                return self._send(200, _PAGE, "text/html; charset=utf-8")
            self._send(404, '{"error":"not found"}', "application/json")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/chat":
                return self._send(404, '{"error":"not found"}', "application/json")
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:  # noqa: BLE001
                data = {}
            text = (data or {}).get("message", "").strip()
            if not text:
                return self._send(400, '{"error":"empty message"}', "application/json")
            parts: list[str] = []
            try:
                kernel.chat("web", text, on_chunk=lambda c: parts.append(c.text or ""))
                reply = "".join(parts).strip()
            except Exception as exc:  # noqa: BLE001
                reply = f"[web] chat failed: {exc}"
            self._send(200, json.dumps({"reply": reply}, ensure_ascii=False), "application/json; charset=utf-8")

        def log_message(self, *a) -> None:  # noqa: N802 - keep the console quiet
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), _H)
    print(f"[channel-web] JARVIS LAN chat: http://{_lan_ip()}:{port}  (phone on same Wi-Fi)", flush=True)
    srv.serve_forever()


class _WebChannel:
    kind = "web"

    def __init__(self, kernel: KernelApi) -> None:
        self._kernel = kernel

    def run(self, kernel: KernelApi) -> None:
        self._kernel = kernel
        port = int(os.environ.get("JARVIS_WEB_PORT", "8237"))
        _serve(self._kernel, port)


def setup(kernel: KernelApi) -> None:
    kernel.service("channel", _WebChannel(kernel))


def teardown(kernel: KernelApi) -> None:
    pass

# --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 05:27:23 ---
