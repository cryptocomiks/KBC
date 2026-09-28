// node render.mjs stills 90,180,...   -> reel/stills/f0090.png ...
// node render.mjs video out.mp4 [sub]  -> 900 frames piped to ffmpeg
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { writeFile } from "node:fs/promises";

// Expects reel.html next to this file, fonts/inter.woff2 + fonts/mono.woff2 (Inter, JetBrains Mono: Google Fonts) and Playwright.
const DIR = new URL("./", import.meta.url).pathname;
const FFMPEG = "/tmp/claude-0/vid/lib/python3.11/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2";
const [mode, arg, subArg] = process.argv.slice(2);
const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on("pageerror", (e) => console.error("PAGE ERROR", e.message));
page.on("console", (m) => console.log("console:", m.text()));
await page.goto("file://" + DIR + "reel.html");
await page.waitForFunction("window.READY === true");
const sub = Number(subArg || 6);
const shot = async (f) => {
  await page.evaluate(([f, s]) => window.renderFrame(f, s), [f, sub]);
  return page.screenshot({ type: "png" });
};
if (mode === "stills") {
  mkdirSync(DIR + "stills", { recursive: true });
  for (const f of arg.split(",").map(Number)) await writeFile(`${DIR}stills/f${String(f).padStart(4, "0")}.png`, await shot(f));
} else {
  const ff = spawn(FFMPEG, ["-y", "-f", "image2pipe", "-framerate", "60", "-c:v", "png", "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-tune", "grain", "-pix_fmt", "yuv420p", "-r", "60", arg], { stdio: ["pipe", "ignore", "inherit"] });
  const t0 = Date.now();
  for (let f = 0; f < 900; f++) {
    const buf = await shot(f);
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (f % 60 === 0) console.log(`frame ${f} ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on("close", r));
}
await browser.close();
