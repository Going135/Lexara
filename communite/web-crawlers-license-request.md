# web-crawlers 许可申请记录

## 日期
2026-10-22

## 渠道
GitHub Issue —— 发布在 <https://github.com/cyohei9907/web-crawlers/issues>

## 申请原文
```
Hi cyohei9907,

I'm the author of LEXARA (https://github.com/Going135/Lexara), a Windows desktop
vocabulary learning tool with a procedural spider pet. The spider's threshold-gait
and two-bone IK design were inspired by your web-crawlers project.

Your repository currently has no LICENSE file, so I'd like to formally ask:

1. Would you be willing to add an open-source license (MIT preferred, to match my
   project) to web-crawlers?
2. Alternatively, do you grant permission for me to distribute the gait/IK ideas from
   your project under MIT license in LEXARA?

To be clear, I did not copy any code verbatim — geometry parameters, gait
thresholds, and rendering are all independently rewritten — but the structural
design (threshold-gait skeleton, two-bone IK with fixed bend side) originates from
your project. I want to make sure the licensing is clean before publishing LEXARA's
first release.

Thanks for your time and for publishing web-crawlers!
```

## 回复状态
截至本 release 发布日（2026-10-22）未收到回复。

## 后续动作
- 若作者回复同意 MIT / 补充 LICENSE → 更新 `THIRD_PARTY_NOTICES.md` 第 3 节与 `LICENSE` 附录，将 `crawler_spider.py` / `spider_painter.py` 纳入 MIT 覆盖
- 若作者回复不同意 → 撤下 release 中的骨架文件或重写，移除对 web-crawlers 的依赖
- 持续未回复 → 当前披露口径保持不变（明确参考、明确上游未声明许可、明确无代码复制）
