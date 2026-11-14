# Screenshots

These come from the mock server (`web/mock/mock-server.mjs`), not the real hub. Its checks pass on a timer and its camera frames are the lesson's reference frames, so a "Verified" or "Camera" in these images shows the UI, not a real camera check.

The exceptions are `11-real-server-verified.png` and `12-real-server-done.png`, taken against the real hub by `e2e/real-server.mjs`. That hub ran with `HANDOVER_CHECK=mock` and a replay file as the camera, so those checks were timer based too.

Retake them with `node e2e/screenshots.mjs` (steps at the top of that file).
