# Screenshots

These come from the mock server (`web/mock/mock-server.mjs`), not the real hub. Its checks pass on a timer and its camera frames are the lesson's reference frames, so a "Verified" or "Checked by camera" in these images shows the UI, not a real camera check.

- `01`–`14b`: Community and Learn (mid lesson at 1440x900 and 1366x768, check settings, verified, manual step, mistake cards, camera lost, hub error, recording banner, checks off, Done with and without mock checks, resume after a hub restart, End confirm, Connect camera on localhost and on a LAN address).
- `15`–`18b`: Teach (home, processing, lost job, ready, review, a step clip).

Retake all of these with `node e2e/screenshots.mjs` (steps at the top of that file).

The exceptions:

- `19-real-server-verified.png` and `20-real-server-done.png`, taken against the real hub by `e2e/real-server.mjs`. That hub ran with `HANDOVER_CHECK=mock` and a replay file as the camera, so those checks were timer based too.
- `21-capture-sending.png` and `22-capture-revive-failed.png`, the phone capture page, taken by `e2e/capture.mjs`.
