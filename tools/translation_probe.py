"""Real bundled-model Chinese OCR → local mock HTTP → rendered translation card.

No external translation service or user credentials are used. Output lives in
the ignored .tmp-shot directory. Run with the project's Python environment.
"""
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ai.translation import TranslationService
from ocr_engine import qimage_to_ndarray
from translation_dialog import TranslationDialog

OUT = BASE / ".tmp-shot"
OUT.mkdir(exist_ok=True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
# The offscreen Qt plugin does not enumerate Windows fonts automatically.
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
if font_path.exists():
    QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 10))
image = QImage(900, 220, QImage.Format_RGB888)
image.fill(QColor("white"))
painter = QPainter(image)
painter.setPen(QColor("#151515"))
painter.setFont(QFont("Microsoft YaHei UI", 20))
painter.drawText(28, 65, "今天的学习计划是阅读英文文章。")
painter.drawText(28, 115, "每天练习 30 分钟，使用 AI 辅助学习。")
painter.end()
image.save(str(OUT / "translation-source.png"))
received = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        received.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for text in ("Today's study plan is to read English articles. ",
                     "Practice for 30 minutes every day, ",
                     "using AI to support your learning."):
            packet = {"choices": [{"delta": {"content": text}}]}
            self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(0.12)
        self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()


class Config:
    def api_key(self):
        return "local-probe-only"

    def base_url(self):
        return "http://127.0.0.1:%d/v1" % server.server_port

    def model(self):
        return "local-probe"


service = TranslationService(Config())
dialog = TranslationDialog({}, service=service)
try:
    started = time.monotonic()
    dialog.begin(qimage_to_ndarray(image), QRect(40, 40, 900, 220))
    stream_preview = False
    while service.state["state"] in ("recognizing", "translating", "review"):
        if service.state["state"] == "review":
            dialog.grab().save(str(OUT / "translation-review.png"))
            # This fixture is self-authored; simulate explicitly confirming its
            # recognized source. Production UI never skips this review step.
            service.translate(service.state["source"])
        app.processEvents()
        if service.state["state"] == "translating" and service.state["text"] and not stream_preview:
            dialog.grab().save(str(OUT / "translation-stream.png"))
            stream_preview = True
        if time.monotonic() - started > 50:
            raise TimeoutError("translation probe timed out")
        time.sleep(0.01)
    assert service.state["state"] == "done", service.state
    source = service.state["source"]
    for expected in ("今天", "学习计划", "英文文章", "30", "AI", "辅助学习"):
        assert expected in source, (expected, source)
    assert len(received) == 1
    assert received[0]["messages"][-1]["content"] == source
    app.processEvents()
    dialog.grab().save(str(OUT / "translation-preview.png"))
    print("PASS: real Chinese OCR -> text-only local HTTP -> translation card")
    print("OCR:", source)
    print("Elapsed: %.2fs" % (time.monotonic() - started))
    print("Preview:", OUT / "translation-preview.png")
finally:
    dialog.close()
    service.shutdown()
    app.processEvents()
    server.shutdown()
    server.server_close()
    server_thread.join(2)
