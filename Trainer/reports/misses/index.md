# 漏识别与错误框报告（engine=rapid）

> 生成方式：`python Trainer/scripts/visualize_misses.py`；底层数据来自 `Trainer/reports/eval_rapid_latest.json`。
> 默认只列出「没全对」的图（`--all` 可全出）。绿=命中，蓝=预测框，橙虚线=漏词，黄=文本识别错，品红=IoU<0.5 的歪框。

| 图片 | 场景 | 真实/正确 | 漏 | 错字 | 多余 | 粘连 | 错切 | IoU<0.5 | 漏掉的词 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [size_medium](misses/size_medium.png) | size_medium | 5/6 | 0 | 1 | 6 | 0 | 5 | 0 | - |
| [style_regular](misses/style_regular.png) | style_regular | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | - |
| [contrast_light_gray](misses/contrast_light_gray.png) | contrast_light_gray | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | - |
| [contrast_semi_transparent](misses/contrast_semi_transparent.png) | contrast_semi_transparent | 6/6 | 0 | 0 | 5 | 1 | 6 | 0 | - |
| [contrast_low](misses/contrast_low.png) | contrast_low | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | - |
| [contrast_on_gradient](misses/contrast_on_gradient.png) | contrast_on_gradient | 2/6 | 2 | 2 | 0 | 1 | 0 | 0 | `river`, `candle` |
| [rotate_tilt_5](misses/rotate_tilt_5.png) | rotate_tilt_5 | 5/5 | 0 | 0 | 2 | 0 | 1 | 0 | - |
| [layout_phrase](misses/layout_phrase.png) | layout_phrase | 7/7 | 0 | 0 | 0 | 0 | 0 | 1 | - |
| [layout_paragraph](misses/layout_paragraph.png) | layout_paragraph | 26/28 | 1 | 1 | 1 | 2 | 1 | 7 | `future` |
| [layout_two_column](misses/layout_two_column.png) | layout_two_column | 8/24 | 9 | 7 | 4 | 4 | 0 | 8 | `motion`, `window`, `thunder`, `digital`, `cotton`, `system`, `summer`, `smooth`, `nature` |
| [layout_web_ui](misses/layout_web_ui.png) | layout_web_ui | 3/17 | 7 | 7 | 2 | 0 | 0 | 2 | `Overview`, `Logout`, `planet`, `system`, `object`, `mountain`, `laptop` |
| [layout_code_subtitle](misses/layout_code_subtitle.png) | layout_code_subtitle | 0/4 | 0 | 4 | 14 | 0 | 3 | 0 | - |
| [bg_noisy](misses/bg_noisy.png) | bg_noisy | 1/6 | 4 | 1 | 4 | 2 | 0 | 1 | `thunder`, `candle`, `travel`, `orange` |
| [hires_page](misses/hires_page.png) | hires_page | 276/312 | 36 | 0 | 0 | 0 | 0 | 3 | `camera`, `pocket`, `island`, `garden`, `travel`, `release`, `laptop`, `orange`, `cotton`, `yellow`, `village`, `circle` |
| [distract_mixed](misses/distract_mixed.png) | distract_mixed | 2/12 | 4 | 6 | 2 | 0 | 1 | 2 | `well-known`, `Spider`, `数据release同步`, `café naïve` |
| [dpi_100](misses/dpi_100.png) | dpi_100 | 5/5 | 0 | 0 | 1 | 0 | 1 | 0 | - |
| [dynamic_subtitle_seq_00](misses/dynamic_subtitle_seq_00.png) | dynamic_subtitle_seq | 0/1 | 0 | 1 | 3 | 0 | 1 | 0 | - |
| [dynamic_subtitle_seq_01](misses/dynamic_subtitle_seq_01.png) | dynamic_subtitle_seq | 0/1 | 0 | 1 | 6 | 0 | 1 | 0 | - |
| [dynamic_subtitle_seq_02](misses/dynamic_subtitle_seq_02.png) | dynamic_subtitle_seq | 0/1 | 0 | 1 | 3 | 0 | 0 | 0 | - |
