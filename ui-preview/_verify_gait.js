const fs = require("fs");
const page = fs.readFileSync(process.argv[2] || "启动台.html", "utf8");
const raw = page.slice(page.indexOf("<script>") + 8, page.lastIndexOf("</script>"));
const src = raw.slice(0, raw.indexOf("function hex2rgb"));
const { Spider } = new Function(src + "\nreturn {Spider};")();

function probe(localPerFrame, label) {
  const sp = new Spider(1);
  let peak = 0, adj = 0, over = 0, settle = null;
  const dt = 1 / 60, speed = localPerFrame / dt;
  for (let f = 0; f < 900; f++) {
    sp.update(dt, "crawl", speed, [localPerFrame, 0]);
    const st = sp.legs.filter(L => L.stepping);
    peak = Math.max(peak, st.length);
    for (const a of st) for (const b of st)
      if (a !== b && a.index < b.index && a.side === b.side &&
          Math.abs(a.slot - b.slot) === 1 && a.slot < 4 && b.slot < 4) adj++;
    for (const L of sp.legs)
      if (Math.hypot(L.tip[0] - L.hipPos[0], L.tip[1] - L.hipPos[1]) > L.l1 + L.l2 + 0.5) over++;
  }
  // 停步后多久站稳（脚离静止位的偏差收敛）
  for (let f = 0; f < 300; f++) sp.update(dt, "idle", 0, [0, 0]);
  settle = Math.max(...sp.legs.filter(L => !L.palp)
    .map(L => Math.hypot(L.tip[0] - sp.restPos(L)[0], L.tip[1] - sp.restPos(L)[1])));
  console.log(`${(label || (localPerFrame.toFixed(2) + " 局部单位/帧")).padEnd(22)} 峰值同时迈步 ${String(peak).padStart(2)} | 同侧相邻违规 ${String(adj).padStart(4)} | 越界帧 ${String(over).padStart(4)} | 停步后最大偏差 ${settle.toFixed(1)}`);
}

console.log("--- 局部速度扫描（腿长 reach≈171 局部单位）---");
for (const v of [0.25, 0.27, 0.30, 0.32, 0.34]) probe(v);
