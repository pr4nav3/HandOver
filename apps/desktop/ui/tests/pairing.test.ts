import assert from "node:assert/strict";
import test from "node:test";

import { hubRequiresAccount, pairedCamera } from "../src/pairing.ts";

const state = (source: "phone" | "glasses" | "browser" | null, connected = true) =>
  ({ camera_connected: connected, camera: source ? { source, name: "Camera", platform: "ios" } : null }) as never;

test("pairing completes only for the camera requested by the QR", () => {
  assert.equal(pairedCamera(state("phone"), "phone"), true);
  assert.equal(pairedCamera(state("phone"), "glasses"), false);
  assert.equal(pairedCamera(state("glasses"), "glasses"), true);
  assert.equal(pairedCamera(state("browser"), "phone"), false);
  assert.equal(pairedCamera(state(null, false), "phone"), false);
});

test("connect onboarding asks for an account only when the hub requires one", () => {
  assert.equal(hubRequiresAccount(null), false);
  assert.equal(hubRequiresAccount({ auth: "optional", setup_needed: false, user: null } as never), false);
  assert.equal(hubRequiresAccount({ auth: "required", setup_needed: false, user: null } as never), true);
  assert.equal(hubRequiresAccount({ auth: "required", setup_needed: false, user: { id: "u" } } as never), false);
});
