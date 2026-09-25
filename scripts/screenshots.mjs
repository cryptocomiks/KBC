// Regenerates the README screenshots from a running instance (demo mode).
//
//   cd scripts && npm i --no-save playwright && npx playwright install chromium
//   BASE_URL=http://localhost:5173 node screenshots.mjs
//
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:5173";
const OUT = new URL("../docs/screenshots/", import.meta.url).pathname;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

async function run(theme) {
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
  await page.addInitScript((t) => localStorage.setItem("kbc-theme", t), theme);
  await page.goto(BASE);
  await page.waitForSelector("text=Know who is behind");
  if (theme === "light") await page.screenshot({ path: `${OUT}01_search.png` });
  await page.click("text=Mohamed Qadrany");
  await page.waitForSelector("text=candidates for");
  if (theme === "light") await page.screenshot({ path: `${OUT}02_disambiguation.png` });
  await page.locator("button:has-text('Investigate')").first().click();
  await page.waitForSelector("text=Linked people & companies", { timeout: 30000 });
  await page.waitForTimeout(1500);
  if (theme === "light") await page.screenshot({ path: `${OUT}00_overview.png`, fullPage: true });
  await page.locator("[role=tab]:has-text('Network')").click();
  await page.waitForSelector("[data-testid=graph] canvas", { timeout: 20000 });
  await page.waitForTimeout(1200);
  if (theme === "light") await page.screenshot({ path: `${OUT}03_ownership_chart.png` });
  await page.locator("text=Network view").click();
  await page.waitForTimeout(1500);
  if (theme === "dark") await page.screenshot({ path: `${OUT}04_network_dark.png` });
  if (theme === "light") {
    await page.locator("[role=tab]:has-text('Evidence')").click();
    await page.locator("text=Why this score?").scrollIntoViewIfNeeded();
    await page.locator("td:has-text('Sanctions list match'), td:has-text('Circular ownership')").first().click();
    await page.screenshot({ path: `${OUT}05_risk_explained.png` });
    await page.locator("button:has-text('Sanctions, PEP')").click();
    await page.locator("button:has-text('Sanctions, PEP')").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}06_tables.png` });
  }
  await page.close();
}

await run("light");
await run("dark");
await browser.close();
console.log(`Screenshots written to ${OUT}`);
