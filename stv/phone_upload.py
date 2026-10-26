"""Фото с телефона по QR-коду: на время открывается маленький сервер в домашней сети.

Телефон сканирует QR-код, открывается страница со «Сфотографировать», снимок уходит прямо в программу —
без мессенджеров и кабеля. Адрес содержит случайный ключ: чужой в той же сети страницу не угадает. Сервер
работает, только пока открыто окно с QR-кодом, и принимает лишь картинки до 30 МБ.
Телефон перед отправкой сам переводит снимок в JPEG (iPhone снимает в HEIC) и уменьшает до 3200 точек.
"""

import json
import secrets
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BYTES = 30 * 1024 * 1024


class UploadError(Exception):
    pass


def lan_ip() -> str:
    """Адрес компьютера в домашней сети (по нему телефон его найдёт). Наружу ничего не отправляется:
    UDP-«подключение» только выбирает сетевую карту."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        ip = socket.gethostbyname(socket.gethostname())
    if ip.startswith("127.") or ip == "0.0.0.0":
        raise UploadError("Компьютер не подключён к сети. Подключите его к тому же Wi-Fi, что и телефон.")
    return ip


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>KonspektAI — фото</title>
<style>
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#F7F5F0;color:#1F1E1C}
main{max-width:460px;margin:0 auto;padding:28px 20px}
h1{font-size:22px;margin:0 0 6px}p{color:#6E6A63;line-height:1.45;margin:0 0 18px}
label,button{display:block;width:100%;box-sizing:border-box;border:0;border-radius:14px;padding:16px;
font-size:17px;font-weight:600;text-align:center;margin-bottom:12px;font-family:inherit}
label,button{background:#2F55D4;color:#fff}input{display:none}[hidden]{display:none!important}
#st{font-weight:600;min-height:24px;line-height:1.4;margin-bottom:14px}.ok{color:#2E7D4F}.err{color:#C0392B}
img{width:100%;border-radius:12px;margin-top:8px}
@media(prefers-color-scheme:dark){body{background:#1F1E1C;color:#EDEBE6}p{color:#A5A19A}
label,button{background:#7C9BFF;color:#11131A}.ok{color:#7FD19B}.err{color:#FF8A7A}}
</style></head><body><main>
<h1 id="t"></h1><p id="h"></p>
<div id="st"></div>
<label for="f" id="pick">📷 Сфотографировать или выбрать</label>
<input id="f" type="file" accept="image/*" capture="environment" __MULTI__>
<button id="next" hidden>Дальше →</button>
<img id="pv" alt="" hidden>
</main><script>
// Состояние задаёт программа на компьютере; страница опрашивает его и показывает нужную кнопку:
// wait — сфотографировать, busy — ждать, ok — «Дальше», error — «Переснять», idle/sent — только текст
let S=__STATE__,local=null,fails=0;
const $=id=>document.getElementById(id);
function show(){const s=local||S;$('t').textContent=s.title||'';$('h').textContent=s.hint||'';
$('st').className=s.stage==='ok'||s.stage==='sent'?'ok':s.stage==='error'?'err':'';$('st').textContent=s.msg||'';
$('pick').hidden=!['wait','error'].includes(s.stage);
$('pick').textContent=s.stage==='error'?'📷 Переснять':
 (s.count?'📷 Сфотографировать ещё':'📷 Сфотографировать или выбрать');
$('next').hidden=!(s.stage==='ok'&&s.next);
if(!local&&['wait','idle'].includes(s.stage))$('pv').hidden=true;}
async function poll(){try{const r=await fetch('state',{cache:'no-store'});const n=await r.json();fails=0;
if(n.v!==S.v||(local&&local.lost)){S=n;if(!local||local.stage!=='busy')local=null;show();}}
catch(e){if(++fails===4){local={...S,stage:'idle',lost:true,msg:'Нет связи с компьютером. Если окно на компьютере '+
 'закрыто — откройте его и отсканируйте QR-код снова.'};show();}}}
setInterval(poll,1200);show();
async function toJpeg(file){const bmp=await createImageBitmap(file);
const k=Math.min(1,3200/Math.max(bmp.width,bmp.height));
const c=document.createElement('canvas');c.width=Math.round(bmp.width*k);c.height=Math.round(bmp.height*k);
c.getContext('2d').drawImage(bmp,0,0,c.width,c.height);return await new Promise(r=>c.toBlob(r,'image/jpeg',0.92));}
$('f').onchange=async e=>{for(const file of e.target.files){
local={...S,stage:'busy',msg:'Отправляю…'};show();
const ctl=new AbortController(),tm=setTimeout(()=>ctl.abort(),90000);
try{const jpg=await toJpeg(file);$('pv').src=URL.createObjectURL(jpg);$('pv').hidden=false;
const r=await fetch('upload',{method:'POST',headers:{'Content-Type':'image/jpeg'},body:jpg,signal:ctl.signal});
if(!r.ok)throw new Error(await r.text());local=null;await poll();}
catch(err){local={...S,stage:'error',msg:'Не получилось отправить: '+
 (err.name==='AbortError'?'нет ответа от компьютера':err.message)};show();}
finally{clearTimeout(tm);}}e.target.value='';};
$('next').onclick=async()=>{$('next').hidden=true;try{await fetch('next',{method:'POST'});}catch(e){}await poll();};
</script></body></html>"""


class PhoneUpload:
    """Сервер на время окна с QR-кодом. on_photo(путь) и on_next() вызываются из потока сервера — в интерфейсе
    передавайте их через сигнал Qt.

    live=False — страница сама пишет «отправлено» после каждого фото. live=True — что показать на телефоне,
    решает программа через set_state: так телефон видит, распознался ли снимок, и может переснять или
    перейти дальше, не сканируя код заново."""

    def __init__(self, on_photo, title: str, hint: str, multiple: bool = False, ip: str | None = None,
                 live: bool = False, on_next=None):
        self.token = secrets.token_urlsafe(12)
        self.on_photo, self.on_next, self.live, self.multiple = on_photo, on_next, live, multiple
        self.folder = Path(tempfile.mkdtemp(prefix="konspektai_phone_"))
        self.count = 0
        self.lock = threading.Lock()
        self.state = {"v": 0, "stage": "wait", "title": title, "hint": hint, "msg": "", "next": False, "count": 0}
        self.multi_attr = "multiple" if multiple else ""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # без вывода в консоль
                pass

            def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.rstrip("/") == f"/{owner.token}":
                    self._send(200, owner.page(), "text/html; charset=utf-8")
                elif self.path == f"/{owner.token}/state":
                    self._send(200, owner.state_json().encode("utf-8"), "application/json")
                else:
                    self._send(404, b"not found")

            def do_POST(self):
                if self.path == f"/{owner.token}/next":
                    self._send(200, b"ok")
                    if owner.on_next:
                        owner.on_next()
                    return
                if self.path != f"/{owner.token}/upload":
                    self._send(404, b"not found")
                    return
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 < size <= MAX_BYTES:
                    self._send(413, "Фото больше 30 МБ".encode())
                    return
                data = self.rfile.read(size)
                if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
                    self._send(415, "Это не фото".encode())
                    return
                with owner.lock:
                    owner.count += 1
                    path = owner.folder / f"phone_{owner.count}.jpg"
                path.write_bytes(data)
                owner._received()
                self._send(200, b"ok")
                owner.on_photo(str(path))

        self.ip = ip or lan_ip()  # ip — для тестов (127.0.0.1: без запроса брандмауэра Windows)
        self.server = ThreadingHTTPServer((self.ip, 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def set_state(self, **kw):
        """Что показать на телефоне: stage (wait | busy | ok | error | idle), title, hint, msg, next."""
        with self.lock:
            self.state.update(kw)
            self.state["v"] += 1

    def state_json(self) -> str:
        with self.lock:
            return json.dumps(self.state, ensure_ascii=False)

    def page(self) -> bytes:
        st = self.state_json().replace("</", "<\\/")  # текст состояния не закроет <script>
        return PAGE.replace("__STATE__", st).replace("__MULTI__", self.multi_attr).encode("utf-8")

    def _received(self):
        if self.live:
            self.set_state(stage="busy", msg="Фото получено, распознаю…", next=False, count=self.count)
        elif self.multiple:
            self.set_state(stage="wait", msg=f"✓ Отправлено фото: {self.count}. Можно сфотографировать ещё.",
                           count=self.count)
        else:
            self.set_state(stage="sent", msg="✓ Готово — фото уже в программе", count=self.count)

    @property
    def url(self) -> str:
        return f"http://{self.ip}:{self.server.server_address[1]}/{self.token}/"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def qr_png(text: str, scale: int = 8) -> bytes:
    import io

    import segno
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()
