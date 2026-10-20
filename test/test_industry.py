# -*- coding: utf-8 -*-
"""行业词库（工业英语权威词汇表）测试。

钉的是三件容易悄悄坏掉的事：

1. **行业义项要排在最前面**。`tolerance` 在 ECDICT 里是「宽容；忍受」，
   在工业文件里它是「公差」。合并顺序一变，卡片就成了错的。
2. **多词术语要真的能被挑出来**。`scan_text` 只按 `WORD_RE` 切单词，
   138 条带空格的术语（`preventive maintenance`）切不出来就等于没加。
   同时不能重复：`heavy industry` 选上了，就不该再选一个单独的 `industry`。
3. **缺库要安静降级**。行业词表是加分项，它不在不能把识词链路带崩。

运行：  python test/test_industry.py
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import industry
import lexicon
from lexicon import Lexicon

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DICT_PATH = os.path.join(BASE, "assets", "ecdict.sqlite")
TAGS_PATH = os.path.join(BASE, "assets", "exam-tags.sqlite")
IND_PATH = os.path.join(BASE, "assets", "industry.sqlite")

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("%s %s %s" % ("[ok]  " if condition else "[FAIL]", name, detail))


lx = Lexicon(DICT_PATH, TAGS_PATH, IND_PATH)

# ---------------------------------------------------------------- A 词库本身
check("A1 行业词库文件存在", os.path.isfile(IND_PATH), IND_PATH)
check("A2 行业词库已加载", lx.industry.available,
      "%s 条" % lx.industry.entry_count)
check("A3 条目数在 300~320 之间（原表 330 行，跨分类合并后 307 条）",
      300 <= lx.industry.entry_count <= 320,
      "实际 %d 条" % lx.industry.entry_count)
check("A4 多词术语已编成正则", len(lx.industry._phrases) >= 130,
      "%d 条" % len(lx.industry._phrases))
check("A5 多词术语按长度降序（长的先匹配）",
      all(len(lx.industry._phrases[i][1]) >= len(lx.industry._phrases[i + 1][1])
          for i in range(len(lx.industry._phrases) - 1)))

con = sqlite3.connect(IND_PATH)
dupes = con.execute(
    "SELECT word, count(*) c FROM entries GROUP BY word HAVING c > 1").fetchall()
check("A6 词表内无重复词条（跨分类的已合并）", not dupes,
      "重复 %s" % (dupes[:3],))
no_cn = con.execute(
    "SELECT count(*) FROM entries WHERE cn IS NULL OR trim(cn) = ''").fetchone()[0]
check("A7 每条都有中文释义", no_cn == 0, "缺释义 %d 条" % no_cn)
cats = con.execute("SELECT count(DISTINCT category) FROM entries").fetchone()[0]
check("A8 分类齐全（7 大类，合并产生的复合分类另算）", cats >= 7, "%d 类" % cats)
con.close()

# ---------------------------------------------------------------- B 单条查询
# B1/B2 是这份词表的核心价值：ECDICT 有这词，但通用释义不是屏幕上那个意思
info = lx.lookup("tolerance")
check("B1 `tolerance` 查得到", info is not None)
check("B2 `tolerance` 行业义项排第一",
      info and info["meanings"] and info["meanings"][0] == "公差",
      info and str(info["meanings"][:3]))
check("B3 `tolerance` 带上了 industry 标签",
      info and industry.LABEL in info["tags"], info and str(info["tags"]))
check("B4 `tolerance` 级别文字含「工业」",
      info and industry.LEVEL_TEXT in info["level"], info and info["level"])
check("B5 `tolerance` 通用义项没有被丢掉",
      info and any(m in info["meanings"] for m in ("容忍", "忍受", "宽容")),
      info and str(info["meanings"]))

info = lx.lookup("industry")
check("B6 `industry` 行业义项排第一",
      info and info["meanings"][0] == "工业", info and str(info["meanings"][:2]))

# 缩写：ECDICT 里没有，全靠行业词库兜底
for term, key in (("PLC", "可编程逻辑控制器"), ("SMED", "快速换模"),
                  ("P&ID", "管道仪表流程图"), ("OEE", "设备综合效率")):
    got = lx.lookup(term)
    check("B7 缩写 `%s` 查得到且释义正确" % term,
          got is not None and key in "；".join(got["meanings"]),
          got and "；".join(got["meanings"])[:26])

# ---------------------------------------------------------------- C 短语优先
TEXT = ("Preventive maintenance and heavy industry require strict tolerance "
        "control; PLC and SCADA are standard.\nQuality assurance checks OEE.")

hits = lx.industry.find_phrases(TEXT)
names = [w for w, _, _ in hits]
check("C1 文本里能扫出多词术语", len(hits) >= 3, str(names))
check("C2 扫到 `preventive maintenance`", "preventive maintenance" in names)
check("C3 扫到 `heavy industry`", "heavy industry" in names)
check("C4 扫到 `quality assurance`", "quality assurance" in names)
check("C5 短语之间不重叠",
      all(not (a[1] < b[2] and b[1] < a[2])
          for i, a in enumerate(hits) for b in hits[i + 1:]))

picked = lx.scan_text(TEXT, mode="all", limit=8)
lemmas = [p["lemma"] for p in picked]
check("C6 挑词结果里有多词术语", "preventive maintenance" in lemmas, str(lemmas))
check("C7 `heavy industry` 入选后不再单挑一个 `industry`",
      "heavy industry" in lemmas and "industry" not in lemmas, str(lemmas))
check("C8 `preventive maintenance` 入选后不再单挑 `maintenance`",
      "maintenance" not in lemmas, str(lemmas))
check("C9 挑词不超上限", len(picked) <= 8, "%d 个" % len(picked))
check("C10 挑词结果无重复", len(lemmas) == len(set(lemmas)), str(lemmas))

# ---------------------------------------------------------------- D 模式筛选
check("D1 `industry` 已登记为挑词模式", "industry" in lexicon.MODE_LABELS)
check("D2 `industry` 有中文显示名",
      lexicon.MODE_DISPLAY.get("industry") == "工业英语")
check("D3 `industry` 进了模式顺序表（界面下拉由此生成）",
      "industry" in lexicon.MODE_ORDER)
check("D4 模式顺序表里 industry 排在「全部词汇」之前",
      lexicon.MODE_ORDER.index("industry") < lexicon.MODE_ORDER.index("all"))

ind_picked = lx.scan_text(TEXT, mode="industry", limit=8)
ind_lemmas = [p["lemma"] for p in ind_picked]
ind_hits = [p for p in ind_picked if industry.LABEL in p["tags"]]
check("D5 工业模式下行业词优先排在最前",
      [p["lemma"] for p in ind_picked[:len(ind_hits)]] ==
      [p["lemma"] for p in ind_hits], str(ind_lemmas))
check("D6 工业模式下行业词数量 ≥ 4",
      len(ind_hits) >= 4, "%d 个：%s" % (len(ind_hits),
                                        [p["lemma"] for p in ind_hits]))
check("D7 工业模式下非行业词被标成表外",
      all(p["off_syllabus"] for p in ind_picked
          if industry.LABEL not in p["tags"]),
      str([(p["lemma"], p["off_syllabus"]) for p in ind_picked]))
check("D8 `matches` 认行业标签",
      lx.matches("plc", "industry") and not lx.matches("plc", "cet4"),
      "plc/industry=%s plc/cet4=%s" % (lx.matches("plc", "industry"),
                                       lx.matches("plc", "cet4")))
check("D9 普通词不受影响（`control` 不是行业词）",
      not lx.matches("control", "industry"))

# ---------------------------------------------------------------- E 缺库降级
bare = Lexicon(DICT_PATH, TAGS_PATH)          # 不传行业词库
check("E1 缺行业词库时不崩", bare.available)
check("E2 缺行业词库时安静降级", not bare.industry.available)
check("E3 缺行业词库时普通查词照常",
      bare.lookup("tolerance") is not None,
      bare.lookup("tolerance") and bare.lookup("tolerance")["meaning"][:24])
check("E4 缺行业词库时缩写查不到（不假装有）", bare.lookup("SMED") is None)
check("E5 缺行业词库时挑词照常",
      len(bare.scan_text(TEXT, mode="cet6", limit=5)) > 0)
check("E6 缺行业词库时工业模式退化成「只收表外补充词」，不报异常",
      isinstance(bare.scan_text(TEXT, mode="industry", limit=5), list))

# ---------------------------------------------------------------- F 落点换算
from pet_window import OcrWorker                      # noqa: E402


class _W:
    """假 OCR 词。

    形状要和生产 `ocr_engine.Word` 一致：除了 `cx/cy`（`phrase_point` 用），
    还得有 `left/top/right/bottom`（`phrase_box` 用）—— 少给一半属性，
    测出来的「通过」是假的，生产路径一走 `phrase_box` 就炸 AttributeError。
    """

    def __init__(self, text, cx, cy, width=80.0, height=24.0):
        self.text, self.cx, self.cy = text, cx, cy
        self.left = cx - width / 2.0
        self.right = cx + width / 2.0
        self.top = cy - height / 2.0
        self.bottom = cy + height / 2.0


class _L:
    def __init__(self, words):
        self.words = words


line_a = _L([_W("Preventive", 100, 200), _W("maintenance", 240, 200),
             _W("and", 340, 200)])
line_b = _L([_W("heavy", 100, 260), _W("industry", 200, 260)])

point = OcrWorker.phrase_point("preventive maintenance", [line_a, line_b])
check("F1 同行凑齐的短语取中点",
      point is not None and abs(point[0] - 170) < 0.01 and point[1] == 200,
      str(point))
check("F2 跨行的短语不硬拼（返回 None）",
      OcrWorker.phrase_point("maintenance heavy", [line_a, line_b]) is None)
check("F3 单个词不走短语路径",
      OcrWorker.phrase_point("industry", [line_a, line_b]) is None)
check("F4 缺行信息时不炸", OcrWorker.phrase_point("heavy industry", None) is None)
check("F5 行里缺词时返回 None",
      OcrWorker.phrase_point("preventive assurance", [line_a]) is None)

# 走一遍真实的 locate：确认多词术语能拿到 screen_pos，腿才有地方踩
worker = OcrWorker.__new__(OcrWorker)
worker.capture_rect = __import__("PySide6.QtCore", fromlist=["QRect"]).QRect(50, 60, 400, 200)
worker.dpr = 1.0
words = [{"surface": "preventive maintenance"},
         {"surface": "Preventive"},
         {"surface": "assurance"}]
worker.locate(words, {"Preventive": (100, 200), "maintenance": (240, 200)},
              [line_a, line_b])
check("F6 多词术语能拿到屏幕坐标",
      words[0].get("screen_pos") is not None, str(words[0].get("screen_pos")))
check("F7 坐标已换算到屏幕系（加了选区原点）",
      words[0].get("screen_pos") == (50 + 170, 60 + 200),
      str(words[0].get("screen_pos")))
check("F8 单词照旧按 positions 换算",
      words[1].get("screen_pos") == (150, 260), str(words[1].get("screen_pos")))
check("F9 查不到落点的词条不带 screen_pos（瞄准层会当够不着处理）",
      "screen_pos" not in words[2])

# ---------------------------------------------------------------- 汇总
print()
print("=" * 60)
print("通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：")
    for name in FAIL:
        print("  - %s" % name)
sys.exit(1 if FAIL else 0)
