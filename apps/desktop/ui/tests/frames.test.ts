// The live view keeps only the newest frame: while one frame is fetched and decoded, every
// frame that arrives replaces the one waiting, so the picture never falls behind.
// Run with `npm test` (Node's own test runner, no extra packages).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fitLongSide, LatestOnly } from "../src/frames.ts";

function gate() {
  let open!: () => void;
  const p = new Promise<void>((r) => (open = r));
  return { p, open };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("works on the newest frame only and drops the rest", async () => {
  const worked: number[] = [];
  const dropped: number[] = [];
  const gates = new Map<number, ReturnType<typeof gate>>();
  const pump = new LatestOnly<number>(
    (n) => {
      worked.push(n);
      const g = gate();
      gates.set(n, g);
      return g.p;
    },
    (n) => dropped.push(n),
  );
  pump.offer(1);
  assert.equal(pump.busy, true);
  for (let n = 2; n <= 6; n++) pump.offer(n);
  assert.deepEqual(worked, [1]);
  assert.deepEqual(dropped, [2, 3, 4, 5]);
  gates.get(1)!.open();
  await tick();
  assert.deepEqual(worked, [1, 6], "the newest waiting frame runs next");
  gates.get(6)!.open();
  await tick();
  assert.equal(pump.busy, false);
  pump.offer(7);
  assert.deepEqual(worked, [1, 6, 7], "an idle pump starts at once");
  gates.get(7)!.open();
  await tick();
});

test("a failed frame does not stop the pump", async () => {
  const worked: number[] = [];
  const pump = new LatestOnly<number>(async (n) => {
    worked.push(n);
    if (n === 1) throw new Error("decode failed");
  });
  pump.offer(1);
  pump.offer(2);
  await tick();
  await tick();
  assert.deepEqual(worked, [1, 2]);
  assert.equal(pump.busy, false);
});

test("clear forgets the waiting frame", async () => {
  const worked: number[] = [];
  const dropped: number[] = [];
  const g = gate();
  const pump = new LatestOnly<number>(
    (n) => {
      worked.push(n);
      return n === 1 ? g.p : Promise.resolve();
    },
    (n) => dropped.push(n),
  );
  pump.offer(1);
  pump.offer(2);
  pump.clear();
  g.open();
  await tick();
  assert.deepEqual(worked, [1]);
  assert.deepEqual(dropped, [2]);
});

test("webcam frames are scaled to a long side of 640, never up", () => {
  assert.deepEqual(fitLongSide(1280, 720), { w: 640, h: 360 });
  assert.deepEqual(fitLongSide(720, 1280), { w: 360, h: 640 });
  assert.deepEqual(fitLongSide(320, 240), { w: 320, h: 240 });
});
