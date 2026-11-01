"""Verify a frozen preview's code, runtime, QML launcher and offline OCR.

Run with the build environment's Python (same Python minor version as the exe).
Uses isolated APPDATA and temporary extraction directories under .tmp-shot.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.utils.hooks import get_package_paths

BASE = Path(__file__).resolve().parents[1]


def verify(exe):
    exe = exe.resolve()
    exe.relative_to(BASE / "dist")
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive(next(k for k in archive.toc if k.endswith(".pyz")))
    for name, path in (("ai.translation", "src/ai/translation.py"),
                       ("translation_dialog", "src/translation_dialog.py"),
                       ("pet_window", "src/pet_window.py")):
        bundled = pyz.extract(name)
        current = compile((BASE / path).read_text(encoding="utf-8"), bundled.co_filename, "exec")
        assert bundled == current, "Stale packaged code: " + name
    qt_dir = Path(get_package_paths("PySide6")[1])
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        assert archive.extract(name) == (qt_dir / name).read_bytes(), "Wrong runtime: " + name
    assert "icuuc.dll" not in archive.toc, "Non-Windows ICU shadows the OS ICU API"
    print("PASS: packaged modules and native runtime", flush=True)
    output = BASE / ".tmp-shot/packaged-smoke" / uuid.uuid4().hex[:8]
    temp = output / "temp"
    temp.mkdir(parents=True)
    results = []
    for scenario in ("qml", "ocr"):
        profile = output / scenario
        profile.mkdir()
        env = dict(os.environ, APPDATA=str(profile), TEMP=str(temp), TMP=str(temp),
                   QT_QPA_PLATFORM="offscreen",
                   QT_QPA_FONTDIR=str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))
        for key in list(env):
            if key.startswith("LEXARA_AI_") or key in ("PYTHONPATH", "LEXARA_QML_TEST"):
                env.pop(key)
        args = [str(exe)]
        if scenario == "qml":
            env["LEXARA_QML_TEST"] = "1"
        else:
            args.append("--ocr-test")
        started = time.monotonic()
        child = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = child.wait(timeout=50)
        except subprocess.TimeoutExpired:
            # This PID is the exact child created above, including its onefile
            # child process. No unrelated Lexara session is touched.
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise
        log = profile / "Lexara/run.log"
        content = log.read_text(encoding="utf-8") if log.exists() else ""
        assert code == 0, (scenario, code, content[-1000:])
        if scenario == "qml":
            assert "portal校验=True" in content, content[-1000:]
        else:
            ocr = temp / "dist/ocr_result.txt"
            assert ocr.exists()
            recognized = ocr.read_text(encoding="utf-8")
            assert "FAILED:" not in recognized
            assert "abandon" in recognized.lower(), "Test font not rendered or OCR failed: " + recognized[:200]
        results.append({"scenario": scenario, "passed": True,
                        "seconds": round(time.monotonic() - started, 3)})
        print("PASS: packaged " + scenario + " smoke", flush=True)
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Evidence:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=BASE / "dist/translation-preview/Lexara.exe")
    verify(parser.parse_args().exe)
