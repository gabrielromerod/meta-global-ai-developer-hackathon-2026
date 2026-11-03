// Samples real R3F camera/controls after rendering, independently of diagnostics.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";
const sha =
  process.env.QA_SHA ??
  execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    encoding: "utf8",
  }).trim();
const root = path.resolve(
  "..",
  "qa",
  "screens",
  sha,
  process.env.TWIN_QA_REDUCED === "1"
    ? "twin-actual-frame-reduced"
    : "twin-actual-frame",
);
const url =
  process.env.TWIN_QA_URL ?? "http://127.0.0.1:8102/next/src/twin/preview.html";
const full = process.env.TWIN_QA_MATRIX === "1";
const reduced = process.env.TWIN_QA_REDUCED === "1";
const sizes = full
  ? [
      [1470, 870],
      [1512, 895],
      [1728, 1030],
      [1920, 960],
      [1536, 730],
      [1280, 600],
      [1366, 650],
      [1024, 768],
      [1180, 820],
      [2560, 1000],
      [390, 844],
    ]
  : [
      [1470, 870],
      [390, 844],
    ];
const browser = await chromium.launch(),
  results = [],
  errors = [];
try {
  for (const [width, height] of sizes) {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.emulateMedia({
      reducedMotion: reduced ? "reduce" : "no-preference",
    });
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("requestfailed", (r) => errors.push(r.url()));
    await page.goto(url);
    await page.locator("[data-webgl=ready]").waitFor();
    await page.waitForTimeout(800);
    await page.evaluate(async () => {
      const fiber =
        await import("/next/node_modules/.vite/deps/@react-three_fiber.js");
      window.__actualTwin = {
        phase: "pan",
        frames: 0,
        violations: [],
        maxNdc: 0,
      };
      window.__stopActualTwin = fiber.addAfterEffect(() => {
        const s = [...fiber._roots.values()][0]?.store.getState();
        if (!s?.controls) return;
        const sample = window.__actualTwin,
          c = s.controls,
          p = s.camera.position,
          t = c.target;
        sample.frames++;
        if (
          p.y < 0.6 - 1e-8 ||
          t.x < -9 - 1e-8 ||
          t.x > 9 + 1e-8 ||
          t.y !== 0 ||
          t.z < -10 - 1e-8 ||
          t.z > 14 + 1e-8 ||
          p.distanceTo(t) < c.minDistance - 1e-8 ||
          p.distanceTo(t) > c.maxDistance + 1e-8
        ) {
          if (sample.violations.length < 8)
            sample.violations.push({
              kind: "bounds",
              position: p.toArray(),
              target: t.toArray(),
            });
        }
        const diagnostics = document.querySelector(".twin-canvas")?.dataset;
        const actualPosition = p.toArray(),
          reportedPosition = diagnostics?.cameraPosition
            ?.split(",")
            .map(Number),
          reportedTarget = diagnostics?.target?.split(",").map(Number);
        if (
          (reportedPosition &&
            reportedTarget &&
            actualPosition.some(
              (v, i) => Math.abs(v - reportedPosition[i]) > 1e-7,
            )) ||
          (reportedTarget &&
            t.toArray().some((v, i) => Math.abs(v - reportedTarget[i]) > 1e-7))
        ) {
          if (sample.violations.length < 8)
            sample.violations.push({
              kind: "diagnostics",
              position: actualPosition,
              target: t.toArray(),
              reportedPosition,
              reportedTarget,
            });
        }
        if (sample.phase === "framing")
          for (const x of [-9, 9])
            for (const y of [0, 3])
              for (const z of [-10, 14]) {
                const point = p.clone().set(x, y, z).project(s.camera),
                  ndc = Math.max(Math.abs(point.x), Math.abs(point.y));
                sample.maxNdc = Math.max(sample.maxNdc, ndc);
                if (ndc > 1 + 1e-6 && sample.violations.length < 8)
                  sample.violations.push({
                    kind: "frustum",
                    point: [x, y, z],
                    ndc: point.toArray(),
                    position: p.toArray(),
                    target: t.toArray(),
                  });
              }
      });
    });
    const folder = path.join(root, `${width}x${height}`);
    await mkdir(folder, { recursive: true });
    const capture = async (name) =>
      page.screenshot({
        path: path.join(folder, `${name}.png`),
        fullPage: true,
      });
    for (let i = 0; i < (width === 1470 ? 8 : 2); i++) {
      const box = await page.locator("canvas").boundingBox();
      await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.15);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 1.8, {
        steps: 20,
      });
      await page.mouse.up();
      await page.waitForTimeout(80);
    }
    for (const button of ["right", "middle"])
      for (let i = 0; i < (width === 1470 ? 5 : 2); i++) {
        const box = await page.locator("canvas").boundingBox();
        await page.mouse.move(
          box.x + box.width * 0.4,
          box.y + box.height * 0.4,
        );
        await page.mouse.down({ button });
        await page.mouse.move(
          box.x + box.width * 1.7,
          box.y + box.height * 1.8,
          { steps: 12 },
        );
        await page.mouse.up({ button });
        await page.waitForTimeout(100);
      }
    await page.waitForTimeout(500);
    for (const wheel of [-100000, 100000]) {
      await page.mouse.wheel(0, wheel);
      await page.waitForTimeout(300);
    }
    await capture("actual-pan");
    results.push({
      width,
      height,
      kind: "pan",
      sample: await page.evaluate(() => window.__actualTwin),
    });
    await page.evaluate(() => {
      window.__actualTwin.phase = "none";
    });
    await page.getByRole("button", { name: "Reset view", exact: true }).click();
    await page.waitForTimeout(800);
    for (const theme of ["dark", "light"]) {
      await page.evaluate(
        (t) => (document.documentElement.dataset.theme = t),
        theme,
      );
      for (const preset of ["Front", "Left passage", "Backyard", "Top-down"]) {
        await page.evaluate(() => {
          window.__actualTwin = {
            phase: "framing",
            frames: 0,
            violations: [],
            maxNdc: 0,
          };
        });
        await page.getByRole("tab", { name: preset, exact: true }).click();
        await page.waitForTimeout(800);
        await capture(`${theme}-${preset.replaceAll(" ", "-")}`);
        results.push({
          width,
          height,
          theme,
          preset,
          sample: await page.evaluate(() => window.__actualTwin),
        });
      }
    }
    await page.evaluate(() => window.__stopActualTwin());
    await page.close();
  }
  await writeFile(
    path.join(root, "results.json"),
    JSON.stringify({ sha, url, reduced, results, errors }, null, 2),
  );
  console.log(
    JSON.stringify({
      sha,
      cases: results.length,
      failed: results
        .filter((r) => r.sample.violations.length)
        .map((r) => ({
          width: r.width,
          height: r.height,
          kind: r.kind,
          preset: r.preset,
          maxNdc: r.sample.maxNdc,
          first: r.sample.violations[0],
        })),
      errors,
    }),
  );
  assert.deepEqual(errors, []);
  assert.ok(
    results.every((result) => result.sample.frames >= 2),
    "real after-render samples were collected for every case",
  );
  assert.equal(
    results.filter((r) => r.sample.violations.length).length,
    0,
    "real post-render camera/controls violations",
  );
} finally {
  await browser.close();
}
