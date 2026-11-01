"""Reproducible webpage/PDF/chat fixtures and optional real-model acceptance.

--prepare creates public, self-authored fixtures; --live sends ONLY these test
sentences to the configured model. All results stay under ignored .tmp-shot.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
OUT = BASE / ".tmp-shot/translation-acceptance"
SAMPLES = {
    "web": [
        "今天的学习计划",
        "每天阅读一篇英文文章，并记录三个新单词。",
        "使用 AI 辅助理解上下文，不要只记住孤立的词义。",
        "第一周练习 30 分钟，第二周增加到 45 分钟。",
    ],
    "pdf": [
        "阅读与复习安排",
        "1. 阅读：先理解文章大意，再查阅生词。",
        "2. 复习：在第 1、3、7 天回顾学习内容。",
        "技术说明：API 请求只发送文字，不上传截图。",
    ],
    "chat": [
        "明天下午三点一起去图书馆吗？",
        "可以，我带上笔记本。我们先练习 English reading，再复习今天的单词。",
        "记得带水，预计学习 45 分钟。",
    ],
}


def prepare():
    from html import escape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("web", "chat"):
        rows = "".join("<p>" + escape(t) + "</p>" for t in SAMPLES[name])
        css = ("p{padding:16px 20px;border-radius:14px;background:#edf5ec;"
               "max-width:630px;margin:16px 0}p:nth-child(2){background:#f1f2f5}") if name == "chat" else (
               "p{margin:0 0 22px}p:first-child{font-size:28px;font-weight:700}")
        (OUT / (name + ".html")).write_text(
            '<!doctype html><meta charset="utf-8"><title>LEXARA '+name+' acceptance</title>'
            '<style>body{margin:0;background:white;color:#151515;font:20px/1.8 "Microsoft YaHei";}'
            'main{padding:32px;width:700px;}'+css+'</style><main>'+rows+'</main>', encoding="utf-8")
    pdfmetrics.registerFont(TTFont("AcceptanceChinese", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    canvas = Canvas(str(OUT / "reading.pdf"), pagesize=(720, 340))
    canvas.setFont("AcceptanceChinese", 18)
    for i, text in enumerate(SAMPLES["pdf"]):
        canvas.drawString(28, 290 - i * 54, text)
    canvas.save()
    subprocess.run(["pdftoppm", "-scale-to", "1100", "-singlefile", "-png",
                    str(OUT / "reading.pdf"), str(OUT / "pdf")], check=True,
                   capture_output=True)
    print("Prepared webpage, PDF and chat fixtures:", OUT)


def error_rate(expected, actual):
    import re
    expected, actual = [re.sub(r"\s+", "", t) for t in (expected, actual)]
    row = list(range(len(actual) + 1))
    for i, a in enumerate(expected, 1):
        current = [i]
        for j, b in enumerate(actual, 1):
            current.append(min(current[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = current
    return round(row[-1] / max(1, len(expected)), 4)


def run(label, live):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QImage
    from ai.config import AIConfig
    from ai.translation import TranslationService, lines_to_text, recognize_translation_lines
    from ocr_engine import OcrEngine, qimage_to_ndarray
    from settings_store import Settings
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    service = TranslationService(AIConfig(Settings())) if live else None
    results = []
    try:
        for name, expected in SAMPLES.items():
            path = OUT / (name + ".png")
            if not path.exists():
                raise FileNotFoundError("Render %s before acceptance" % path)
            array = qimage_to_ndarray(QImage(str(path)))
            started = time.monotonic()
            lines = recognize_translation_lines(array)
            source = lines_to_text(lines)
            result = {"sample": name, "expected": "\n".join(expected), "source": source,
                      "character_error_rate": error_rate("".join(expected), source),
                      "ocr_seconds": round(time.monotonic() - started, 3),
                      "lines": [{"text": ln.text, "score": round(ln.score, 4), "box": ln.box}
                                for ln in lines]}
            if service:
                first = []
                def observe():
                    if service.state["text"] and not first:
                        first.append(time.monotonic())
                service.changed.connect(observe)
                translated = time.monotonic()
                service.translate(source)
                while service.state["state"] in ("recognizing", "translating", "review"):
                    app.processEvents()
                    if time.monotonic() - translated > 70:
                        raise TimeoutError("Acceptance model request exceeded 70 seconds")
                    time.sleep(0.01)
                result.update({"state": service.state["state"], "translation": service.state["text"],
                               "error": service.state["error"],
                               "translation_seconds": round(time.monotonic() - translated, 3),
                               "first_text_seconds": round(first[0] - translated, 3) if first else None})
                service.changed.disconnect(observe)
            results.append(result)
            print(name, "CER=%.2f%%" % (result["character_error_rate"] * 100),
                  "OCR=%.3fs" % result["ocr_seconds"], result.get("state", "ocr-only"), flush=True)
            (OUT / (label + ".json")).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    finally:
        if service:
            service.shutdown()
            app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        run(args.label, args.live)
