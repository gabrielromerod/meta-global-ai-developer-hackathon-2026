import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { PerspectiveCamera, Vector3 } from "three";
import path from "node:path";
const sha =
  process.env.QA_SHA ??
  execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    encoding: "utf8",
  }).trim();
const root = path.resolve("..", "qa", "screens", sha);
const baseURL =
  process.env.TWIN_QA_URL ?? "http://127.0.0.1:8102/next/src/twin/preview.html";
const viewports = [
  ["air13", 1470, 870],
  ["pro14", 1512, 895],
  ["pro16", 1728, 1030],
  ["windows100", 1920, 960],
  ["windows125", 1536, 730],
  ["windows150", 1280, 600],
  ["laptop", 1366, 650],
  ["four-three", 1024, 768],
  ["tablet", 1180, 820],
  ["ultrawide", 2560, 1000],
  ["phone", 390, 844],
];
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const [name, width, height] of viewports) {
    const page = await browser.newPage({ viewport: { width, height } }),
      errors = [],
      failed = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("requestfailed", (r) =>
      failed.push(`${r.url()}: ${r.failure()?.errorText}`),
    );
    page.on("response", (r) => {
      if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
    });
    await page.goto(baseURL);
    await page.locator("[data-webgl=ready]").waitFor();
    await page.waitForTimeout(800);
    assert.deepEqual(errors, [], `${name}: console errors`);
    assert.deepEqual(failed, [], `${name}: failed requests`);
    const folder = path.join(root, `${width}x${height}`);
    await mkdir(folder, { recursive: true });
    const capture = async (state) => {
      const rectangles = await page
        .locator(".twin-annotation:visible")
        .evaluateAll((elements) =>
          elements.map((element) => {
            const box = element.getBoundingClientRect();
            return {
              id: element.getAttribute("data-label-id"),
              left: box.left,
              top: box.top,
              right: box.right,
              bottom: box.bottom,
            };
          }),
        );
      for (const rect of rectangles)
        for (const other of rectangles.filter((item) => item.id !== rect.id))
          assert.ok(
            !(
              rect.left < other.right - 0.5 &&
              rect.right > other.left + 0.5 &&
              rect.top < other.bottom - 0.5 &&
              rect.bottom > other.top + 0.5
            ),
            `${name}/${state} annotations overlap: ${rect.id}, ${other.id}`,
          );
      return page.screenshot({
        path: path.join(folder, `twin-${state}.png`),
        fullPage: true,
      });
    };
    const assertFramed = async () => {
      const pose = await page
        .locator("[data-testid=twin-canvas]")
        .evaluate((element) => ({
          position: element.dataset.cameraPosition.split(",").map(Number),
          target: element.dataset.target.split(",").map(Number),
          fov: Number(element.dataset.cameraFov),
          aspect: element.clientWidth / element.clientHeight,
        }));
      const camera = new PerspectiveCamera(pose.fov, pose.aspect, 0.1, 300);
      camera.position.fromArray(pose.position);
      camera.lookAt(new Vector3(...pose.target));
      camera.updateMatrixWorld();
      for (const x of [-9, 9])
        for (const y of [0, 3])
          for (const z of [-10, 14]) {
            const point = new Vector3(x, y, z).project(camera);
            assert.ok(
              Math.abs(point.x) < 1 && Math.abs(point.y) < 1,
              `${name}: preset clips public property bounds ${JSON.stringify({ pose, point })}`,
            );
          }
    };
    await assertFramed();
    for (const theme of ["dark", "light"]) {
      if (theme === "light")
        await page
          .getByRole("button", { name: "Light theme", exact: true })
          .click();
      await page.waitForTimeout(250);
      await capture(theme);
      const size = await page.evaluate(() => ({
        height: document.documentElement.scrollHeight,
        width: document.documentElement.scrollWidth,
        viewportHeight: innerHeight,
        viewportWidth: innerWidth,
      }));
      assert.ok(
        size.width <= size.viewportWidth,
        `${name}/${theme}: horizontal overflow ${JSON.stringify(size)}`,
      );
      if (name !== "phone")
        assert.ok(
          size.height <= size.viewportHeight,
          `${name}/${theme}: page scroll ${JSON.stringify(size)}`,
        );
      await assertFramed();
    }
    if (
      await page
        .getByRole("button", { name: "Select camera", exact: true })
        .isVisible()
    ) {
      await page
        .getByRole("button", { name: "Select camera", exact: true })
        .click();
      await capture("compact-camera-menu");
      await page.getByRole("menuitemradio", { name: /Backyard 2/ }).click();
      await capture("compact-camera-selected");
    }
    if (name === "air13" || name === "phone") {
      await page
        .getByRole("button", { name: "Dark theme", exact: true })
        .click();
      for (const preset of ["Left passage", "Backyard", "Top-down", "Front"]) {
        await page.getByRole("tab", { name: preset, exact: true }).click();
        await page.waitForTimeout(600);
        const framing = await page
          .locator("[data-testid=twin-canvas]")
          .evaluate((element) => ({
            fov: Number(element.dataset.cameraFov),
            aspect: element.clientWidth / element.clientHeight,
            base: parseFloat(
              getComputedStyle(document.documentElement).getPropertyValue(
                "--v-twin-camera-fov",
              ),
            ),
          }));
        const expectedFov =
          (2 *
            Math.atan(
              Math.tan((framing.base * Math.PI) / 360) /
                Math.min(1, framing.aspect),
            ) *
            180) /
          Math.PI;
        assert.ok(
          Math.abs(framing.fov - expectedFov) < 0.01,
          `camera framing reset after ${preset}: ${JSON.stringify(framing)}`,
        );
        await capture(`preset-${preset.toLowerCase().replaceAll(" ", "-")}`);
      }
      await page.getByRole("button", { name: "Zoom in", exact: true }).click();
      await page.getByRole("button", { name: "Zoom out", exact: true }).click();
      await page
        .getByRole("button", { name: "Toggle camera coverage" })
        .click();
      await capture("coverage-off");
      await page
        .getByRole("button", { name: "Toggle camera coverage" })
        .click();
      const cameraButtons = page.locator(".twin-camera-list button");
      for (let i = 0; i < (await cameraButtons.count()); i++) {
        await cameraButtons.nth(i).scrollIntoViewIfNeeded();
        await cameraButtons.nth(i).click();
        await capture(`camera-${i}`);
      }
      await page.getByRole("button", { name: "Reset view" }).click();
      await page.waitForTimeout(600);
      const canvas = page.locator("canvas"),
        box = await canvas.boundingBox();
      assert.ok(box);
      await page.mouse.move(
        box.x + box.width * 0.45,
        box.y + box.height * 0.25,
      );
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width * 0.45,
        box.y + box.height * 0.95,
        { steps: 12 },
      );
      await page.mouse.up();
      await page.waitForTimeout(300);
      const y = Number(
        await page
          .locator("[data-testid=twin-canvas]")
          .getAttribute("data-camera-y"),
      );
      assert.ok(y >= 0.6, `downward drag went underground: ${y}`);
      await capture("drag-down");
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
      await page.mouse.down({ button: "right" });
      await page.mouse.move(box.x + box.width * 1.2, box.y + box.height * 1.2, {
        steps: 10,
      });
      await page.mouse.up({ button: "right" });
      await page.waitForTimeout(250);
      const target = (
        await page
          .locator("[data-testid=twin-canvas]")
          .getAttribute("data-target")
      )
        .split(",")
        .map(Number);
      assert.ok(
        target[0] >= -9 &&
          target[0] <= 9 &&
          target[1] === 0 &&
          target[2] >= -10 &&
          target[2] <= 14,
        `pan target outside ground: ${target}`,
      );
      await capture("pan-bound");
      await page.mouse.wheel(0, 10000);
      await page.waitForTimeout(300);
      const distance = Number(
        await page
          .locator("[data-testid=twin-canvas]")
          .getAttribute("data-orbit-distance"),
      );
      assert.ok(distance <= 55.0001 && distance >= 8, `zoom bound ${distance}`);
      await capture("zoom-bound");
      await page.getByRole("button", { name: "Reset view" }).click();
      await page.waitForTimeout(600);
      await page.locator("#evidence-time").fill("15280");
      await capture("gap");
      await page.locator("#evidence-time").fill("15304");
      await capture("observed");
      for (const control of await page
        .locator(
          ".twin-toolbar button:visible,.twin-camera-list button:visible,.twin-blind-label:visible,.twin-pin:visible",
        )
        .all()) {
        await control.scrollIntoViewIfNeeded();
        await control.hover();
        const label =
          (await control.getAttribute("aria-label")) ??
          (await control.textContent());
        await capture(
          `hover-${String(label)
            .toLowerCase()
            .replaceAll(/[^a-z0-9]+/g, "-")
            .slice(0, 40)}`,
        );
      }
      await page
        .getByRole("button", { name: "Light theme", exact: true })
        .focus();
      for (let i = 0; i < 24; i++) {
        await page.keyboard.press("Tab");
        await page.waitForTimeout(50);
        const focus = await page.evaluate(() => {
          const el = document.activeElement;
          return el instanceof HTMLElement
            ? {
                tag: el.tagName,
                html: el.outerHTML.slice(0, 600),
                label: el.getAttribute("aria-label") ?? el.textContent,
                outline: getComputedStyle(el).outlineStyle,
              }
            : null;
        });
        if (focus && focus.tag !== "BODY")
          assert.notEqual(
            focus.outline,
            "none",
            `visible keyboard focus: ${JSON.stringify(focus)}`,
          );
      }
      await capture("keyboard-focus");
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.getByRole("tab", { name: "Top-down" }).click();
      await page.waitForTimeout(100);
      await capture("reduced-motion");
      await page.locator(".twin-camera-list").evaluate((el) => {
        el.scrollLeft = el.scrollWidth;
      });
      await capture("camera-scroll-end");
      await page.locator(".twin-camera-list").evaluate((el) => {
        el.scrollLeft = 0;
      });
    }
    if (name === "windows150") {
      await page.locator(".twin-preview-stage").evaluate((element) => {
        element.style.flex = "none";
        element.style.height = "266px";
        element.style.display = "flex";
      });
      await page.waitForTimeout(300);
      const panel = await page.locator(".house-view").boundingBox(),
        canvas = await page.locator("canvas").boundingBox();
      assert.ok(
        panel && canvas && panel.width > 100 && canvas.height >= 175,
        `compact hero collapsed ${JSON.stringify({ panel, canvas })}`,
      );
      await capture("compact-266px-parent");
    }
    await page
      .getByRole("button", { name: "Hide 3D view", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Show 3D view", exact: true })
      .click();
    await page.locator("[data-webgl=ready]").waitFor();
    await page.waitForTimeout(200);
    assert.deepEqual(errors, [], `${name}: console errors after interaction`);
    assert.deepEqual(failed, [], `${name}: failed requests after interaction`);
    results.push({
      name,
      width,
      height,
      consoleErrors: errors,
      failedRequests: failed,
      status: "passed",
    });
    await page.close();
  }
  await writeFile(
    path.join(root, "twin-results.json"),
    JSON.stringify(
      {
        sha,
        url: baseURL,
        viewports: results,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ sha, status: "passed", viewports: results.length, root }),
  );
} finally {
  await browser.close();
}
