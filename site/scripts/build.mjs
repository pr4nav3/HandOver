import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = resolve(here, "..");
const dist = resolve(site, "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(resolve(site, "assets"), resolve(dist, "assets"), { recursive: true });

await cp(resolve(site, "index.html"), resolve(dist, "index.html"));
await cp(resolve(site, "install.html"), resolve(dist, "install.html"));
await cp(resolve(site, "styles.css"), resolve(dist, "styles.css"));
await cp(resolve(site, "main.js"), resolve(dist, "main.js"));

console.log(`Built ${dist}`);
