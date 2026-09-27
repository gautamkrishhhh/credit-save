// End-to-end browser check: loads every screen of the running app, exercises
// the key flows, fails on JS errors / error panels, and saves screenshots.
//   node scripts/e2e.mjs [baseUrl] [outDir]
import { createRequire } from "module";
import fs from "fs";
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch { ({ chromium } = require(require("child_process").execSync("npm root -g").toString().trim() + "/playwright")); }

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const OUT = process.argv[3] || "screenshots";
fs.mkdirSync(OUT, { recursive: true });

const exe = fs.existsSync("/opt/pw-browsers/chromium") ? undefined : undefined;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: "light" });
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));

const results = [];
async function check(name, fn) {
  const before = errors.length;
  try {
    await fn();
    const bad = await page.locator(".panel.bad").count();
    if (bad) throw new Error(await page.locator(".panel.bad").first().innerText());
    if (errors.length > before) throw new Error(errors.slice(before).join("; "));
    results.push({ name, ok: true });
    console.log("PASS", name);
  } catch (e) {
    results.push({ name, ok: false, error: String(e.message || e) });
    console.log("FAIL", name, "-", e.message);
  }
}
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: false });
const go = async (route, waitFor) => { await page.goto(`${BASE}/#/${route}`); await page.waitForSelector(waitFor, { timeout: 20000 }); await page.waitForTimeout(300); };

await page.goto(BASE);
await page.waitForFunction(async () => (await (await fetch("/api/health")).json()).ml_ready, null, { timeout: 60000, polling: 1000 });
await page.evaluate(() => fetch("/api/demo/seed", { method: "POST" }));

await check("dashboard", async () => { await go("dashboard", ".stat .value"); await shot("01-dashboard"); });
await check("which-card", async () => {
  await go("which-card", "#wcQuery");
  await page.fill("#wcQuery", "Swiggy"); await page.fill("#wcAmt", "800"); await page.click("#wcGo");
  await page.waitForSelector(".rank.best"); await shot("02-which-card");
  await page.fill("#wcQuery", "Nayara Energy petrol"); await page.click("#wcGo");
  await page.waitForSelector(".tag.blue");
});
await check("sage-chat", async () => {
  await go("sage", "#chatIn");
  for (const q of ["Which card for Swiggy ₹800?", "what about 3000", "How much are my points worth?", "Suggest a new card"]) {
    const n = await page.locator(".msg.assistant").count();
    await page.fill("#chatIn", q); await page.press("#chatIn", "Enter");
    await page.waitForFunction((n) => document.querySelectorAll(".msg.assistant:not(.muted)").length > n, n, { timeout: 20000 });
  }
  await shot("03-sage");
});
await check("wallet", async () => { await go("wallet", ".ccard"); await shot("04-wallet"); });
await check("transactions+sms", async () => {
  await go("transactions", "#smsText");
  await page.click("#smsPrev"); await page.waitForSelector("#smsOut table");
  const ok = await page.locator("#smsOut td:has-text('✅')").count();
  if (ok < 3) throw new Error(`only ${ok}/3 SMS parsed`);
  await page.fill("#tDesc", "Vinayaka Medicals"); await page.waitForSelector("#tPred b", { timeout: 5000 });
  await shot("05-transactions");
});
await check("rewards", async () => { await go("rewards", "#gGo"); await page.click("#gGo"); await page.waitForSelector("#gOut table, #gOut .warn"); await shot("06-rewards"); });
await check("discover", async () => { await go("discover", ".rank"); await shot("07-discover"); });
await check("compare", async () => { await go("compare", "#cOut table"); await shot("08-compare"); });
await check("offers", async () => { await go("offers", "#offGrid .panel"); });
await check("insights", async () => { await go("insights", "#retrain"); await shot("09-insights"); });
await check("mobile", async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await go("dashboard", ".stat .value");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) throw new Error("horizontal overflow on mobile");
  await shot("10-mobile");
});

await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2));
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
