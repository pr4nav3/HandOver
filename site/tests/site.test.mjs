import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

const site = resolve(import.meta.dirname, "..");
const html = await readFile(resolve(site, "index.html"), "utf8");
const install = await readFile(resolve(site, "install.html"), "utf8");
const css = await readFile(resolve(site, "styles.css"), "utf8");
const js = await readFile(resolve(site, "main.js"), "utf8");

test("local anchors all resolve", () => {
  const ids = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]));
  for (const [, anchor] of html.matchAll(/href="#([^"]+)"/g)) assert.ok(ids.has(anchor), `missing #${anchor}`);
});

test("landing stays sparse and uses three real repository visuals", async () => {
  const sources = [...html.matchAll(/src="(assets\/product\/[^"]+\.(?:png|jpg))"/g)].map((match) => match[1]);
  assert.equal(new Set(sources).size, 3);
  assert.ok(sources.length <= 4, "landing should not become a screenshot gallery");
  await Promise.all([...new Set(sources)].map((source) => access(resolve(site, source))));
  assert.equal((html.match(/data-provenance=/g) ?? []).length, 3);
});

test("device scene and spring choreography are present", () => {
  assert.match(html, /data-device-stage/);
  assert.match(html, /class="device-pair"/);
  assert.match(js, /class Spring/);
  assert.match(js, /minJerk/);
  assert.match(js, /initDeviceScene/);
  assert.match(css, /\.device-stage\[data-scene="3"\]/);
});

test("canonical mark and favicon are wired into the standalone build", async () => {
  assert.match(html, /assets\/brand\/handover-favicon\.svg/);
  assert.match(css, /assets\/brand\/handover-favicon\.svg/);
  await access(resolve(site, "assets/brand/handover-mark.svg"));
  await access(resolve(site, "assets/brand/handover-favicon.svg"));
});

test("technical detail stays linked away from the landing", () => {
  assert.doesNotMatch(html, /<table|<details|quickstart command|Troubleshooting/i);
  assert.match(html, /Technical docs/);
  assert.match(html, /docs\/project\.md/);
});

test("page keeps accessible navigation and reduced motion", () => {
  assert.match(html, /class="skip"/);
  assert.match(html, /<main id="main">/);
  assert.match(html, /aria-controls="mobile-menu"/);
  assert.match(css, /prefers-reduced-motion:reduce/);
  assert.match(css, /:focus-visible/);
  assert.match(js, /reducedMotion/);
});

test("only the opening image is eager", () => {
  const images = [...html.matchAll(/<img\s[^>]*>/g)].map((match) => match[0]);
  assert.equal(images.length, 3);
  assert.match(images[0], /fetchpriority="high"/);
  images.slice(1).forEach((image) => assert.match(image, /loading="lazy"/));
});

test("download page offers real platform paths without pretending an iPhone binary is public", () => {
  assert.match(html, /href="install\.html">Download/);
  assert.match(install, /HandOver-0\.1\.0-macos-arm64\.dmg/);
  assert.match(install, /HandOver-0\.1\.0-android\.apk/);
  assert.match(install, /tree\/main\/apps\/apple/);
  assert.match(install, /There is no App Store or TestFlight release yet/);
  assert.doesNotMatch(install, /\.ipa/);
});

test("platform picker is keyboard accessible and build emits the install page", async () => {
  assert.equal((install.match(/role="tab"/g) ?? []).length, 3);
  assert.equal((install.match(/role="tabpanel"/g) ?? []).length, 3);
  assert.match(js, /initInstallPicker/);
  assert.match(js, /ArrowLeft/);
  await access(resolve(site, "dist/install.html"));
});
