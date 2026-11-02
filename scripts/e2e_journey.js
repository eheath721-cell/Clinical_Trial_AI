// Usage: node scripts/e2e_journey.js <screenshot-dir> backend/data/synthetic/synthetic_lipid_panel.pdf
// Requires the API on :8000 and the web app on :3000 (see README). Uses the `playwright` package.
// End-to-end walk-through of the primary user journey with screenshots.
const { chromium } = require("playwright");
const path = require("path");

const BASE = "http://localhost:3000";
const OUT = process.argv[2];
const SAMPLE = process.argv[3];
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  const step = (s) => console.log(`- ${s}`);

  // 1. Landing
  await page.goto(BASE);
  await shot(page, "01-landing");
  step("landing rendered");

  // 2. Sign up
  await page.click("text=Get started");
  await page.fill('input[type="email"]', `journey+${Date.now()}@example.com`);
  await page.fill('input[type="password"]', "synthetic-demo-pass");
  const boxes = page.locator('input[type="checkbox"]');
  for (let i = 0; i < 3; i++) await boxes.nth(i).check();
  await page.click('button:has-text("Create account")');
  await page.waitForURL("**/app/onboarding");
  step("account created -> onboarding");

  // 3. Onboarding
  await page.fill('input[placeholder="e.g. Sam"]', "Jordan");
  await page.click('button:has-text("Continue")');
  await page.waitForSelector("text=The basics");
  await page.fill('input[type="date"]', "2002-03-02");
  await page.fill('input[placeholder="79401"]', "79401");
  await shot(page, "02-onboarding-basics");
  await page.click('button:has-text("Continue")');
  await page.waitForSelector("text=Not sure");
  // Heart attack: No, Coronary artery disease: No (as in the brief); everything else "Not sure"
  const answer = async (groupName, choice) => {
    await page.getByRole("radiogroup", { name: groupName }).getByRole("radio", { name: choice, exact: true }).click();
  };
  await answer("Heart attack (myocardial infarction)", "No");
  await answer("Coronary artery disease", "No");
  await page.selectOption("select >> nth=0", "not_current");
  await shot(page, "03-onboarding-history");
  await page.click('button:has-text("Continue")');
  await page.waitForSelector("text=Lipoprotein(a) — Lp(a)");
  await page.fill('input[placeholder="e.g. 185"]', "185");
  await page.click('button:has-text("Save & continue")');
  await page.waitForSelector("text=Upload lab reports");
  await page.click('button:has-text("Find my trials")');
  await page.waitForURL("**/app/trials**");
  await page.waitForSelector("text=Eligibility breakdown", { timeout: 60000 });
  step("onboarding complete -> matches");

  // 4. Upload & review a synthetic lab report
  await page.click('nav >> text=Documents');
  await page.waitForSelector("text=Medical records");
  await page.setInputFiles('input[type="file"]', SAMPLE);
  await page.waitForSelector("text=Lipoprotein(a) [Lp(a)]: 185 nmol/L", { timeout: 30000 });
  await shot(page, "04-document-review");
  await page.click('button:has-text("Accept all items without warnings")');
  await page.waitForSelector("text=Reviewed", { timeout: 30000 });
  step("lab report uploaded, extracted values reviewed and accepted");

  // 5. Matches dashboard (refresh with the updated profile)
  await page.click('nav >> text=Matches');
  await page.click('button:has-text("Search again")');
  await page.waitForSelector("text=How we searched", { timeout: 60000 });
  await page.click("text=How we searched");
  await shot(page, "05-matches-dashboard");
  const total = await page.locator("h1").first().innerText();
  step(`dashboard: ${total}`);

  // 6. Trial detail - MOVE-Lp(a)
  await page.click("text=MOVE-Lp(a)");
  await page.waitForSelector("text=Inclusion criteria");
  await page.click("text=Have Lp(a) ≥175");
  await shot(page, "06-trial-eligibility");
  const cls = await page.locator("text=Eligibility uncertain").first().isVisible();
  step(`MOVE-Lp(a) classification uncertain visible: ${cls}`);
  await page.click('[role="tab"]:has-text("Locations")');
  await page.waitForSelector("text=Draft inquiry to this site");
  await shot(page, "07-trial-locations");
  await page.click('button:has-text("Save")');
  await page.waitForSelector('button:has-text("Saved")');
  step("trial saved");

  // 7. Compare two trials from the dashboard
  await page.click('nav >> text=Matches');
  await page.waitForSelector("text=Eligibility breakdown");
  const compares = page.locator('input[aria-label^="Compare"]');
  await compares.nth(0).check();
  await compares.nth(1).check();
  await page.click('a:has-text("Compare")');
  await page.waitForSelector("text=Compare studies");
  await shot(page, "08-compare");
  step("comparison rendered");

  // 8. Start an inquiry for MOVE-Lp(a)
  await page.goBack();
  await page.waitForSelector("text=MOVE-Lp(a)");
  await page.click("text=MOVE-Lp(a)");
  await page.waitForSelector('button:has-text("Contact study team")');
  await page.click('button:has-text("Contact study team")');
  await page.waitForSelector("text=Draft an inquiry");
  await shot(page, "09-inquiry-dialog");
  await page.click('button:has-text("Prepare draft")');
  await page.waitForURL("**/app/enrollment/**");
  await page.waitForSelector("text=Your message");
  await shot(page, "10-inquiry-draft");
  await page.click('button:has-text("I sent it")');
  await page.waitForSelector("text=Sent");
  step("inquiry drafted and marked as sent by user");

  await page.click('nav >> text=Enrollment');
  await page.waitForSelector("text=Follow-up tasks");
  await shot(page, "11-enrollment-tracker");

  // 9. Profile with provenance
  await page.click('nav >> text=Health profile');
  await page.waitForSelector("text=Lab results");
  await shot(page, "12-profile-provenance");

  // 10. Mobile
  const m = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, storageState: await ctx.storageState() });
  const mp = await m.newPage();
  await mp.goto(`${BASE}/app/trials`);
  await mp.waitForSelector("text=Eligibility breakdown", { timeout: 60000 });
  await mp.screenshot({ path: path.join(OUT, "13-mobile-matches.png"), fullPage: false });
  await mp.goto(`${BASE}/app/trials/NCT07157774`);
  await mp.waitForSelector("text=Inclusion criteria");
  await mp.screenshot({ path: path.join(OUT, "14-mobile-trial.png"), fullPage: false });
  step("mobile views rendered");

  console.log(errors.length ? `console errors:\n${errors.join("\n")}` : "no console errors");
  await browser.close();
})().catch((e) => {
  console.error("E2E FAILED:", e);
  process.exit(1);
});
