const fs = require("fs");
const page = fs.readFileSync(process.argv[2] || "启动台.html", "utf8");
const raw = page.slice(page.indexOf("<script>") + 8, page.lastIndexOf("</script>"));
const src = raw.slice(0, raw.indexOf("function hex2rgb"));

// 两个版本：只改速度符号，其余完全一致
const mk = sign => new Function(
  src.replace("this.velocity[0]+(motion[0]", "this.velocity[0]+(" + sign + "motion[0]")
       .replace("this.velocity[1]+(motion[1]", "this.velocity[1]+(" + sign + "motion[1]")
    + "\nreturn {Spider, CS};")();

for (const [label, sign] of [["原型已修正 (+motion/dt)", "+"], ["Python 现状 (-motion/dt)", "-"]]) {
  const { Spider } = mk(sign);
  const sp = new Spider(1);
  for (let f = 0; f < 300; f++) sp.update(1 / 60, "crawl", 60, [0.3, 0]); // 身体往局部 +x（屏幕右）走
  const deg = (((sp.heading * 180 / Math.PI) % 360) + 360) % 360;
  const facing = deg < 45 || deg > 315 ? "右（=行进方向 ✓）" : (deg > 135 && deg < 225 ? "左（背向行进 ✗）" : deg.toFixed(0) + "°");
  // 前瞻落点：新脚应落在身体前进方向的前方
  const L = sp.legs.find(x => x.slot === 0 && x.side === 1);
  const tgt = sp.stepTarget(L), rest = sp.restPos(L);
  console.log(`${label.padEnd(24)} heading=${deg.toFixed(0).padStart(3)}° 面朝 ${facing.padEnd(20)} 前瞻 dx=${(tgt[0] - rest[0]).toFixed(1)} (应>0)`);
}
