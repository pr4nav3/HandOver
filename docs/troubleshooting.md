# Troubleshooting

Start with the symptom the screen shows. HandOver keeps connection, camera, motion, checking, and audio states separate, so changing unrelated settings usually makes diagnosis harder.

## The app is using old behavior or feels unexpectedly slow

Confirm that only one hub is listening and that it belongs to the checkout you are editing:

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -a -p <PID> -d cwd
```

If the working directory is an old clone, temporary worktree, or deleted folder, stop that exact process and start the current hub:

```sh
kill -TERM <PID>
scripts/run_server.sh
```

Do not kill every Python process. Resolve the listener on port 8000 first.

The current learner state explains where time is going:

| State | Meaning | What to do |
| --- | --- | --- |
| **Waiting for camera** | No active camera socket | Reconnect the phone/computer camera. |
| **Waiting for a frame** | Camera connected, no fresh JPEG yet | Keep the capture screen in front; check its sent-fps indicator. |
| **Moving** | Hands or paper are still changing | Finish the motion and hold the result briefly. |
| **Settling** | The hub is collecting still frames | Keep the result steady; do not repeat the fold. |
| **Checking** | A frame is with the configured vision provider | Check provider latency, timeout, key, and breaker status. |
| **Watching** | Latest result did not confidently complete the step | Read the feedback; use Next if the visible result is correct. |
| **Verified** | The step passed | The next step follows after the short confirmation moment. |

The default hub accepts a 15 fps sender, evaluates motion up to eight times a second, and offers a settled frame to the model at most every 0.5 seconds. Network and provider response time remain outside the local loop. Before tuning, make sure the running hub actually comes from this checkout.

## The phone cannot connect

1. Keep the hub terminal open.
2. Put the phone and computer on the same Wi-Fi or hotspot.
3. On the phone, open `http://<laptop-ip>:8000` in a browser.
4. If the page does not load, fix the network or firewall before changing the app.
5. If the page loads, enter that exact address in HandOver, including `http://` and `:8000`.

A corporate, school, hotel, or guest network may isolate wireless devices from each other. A phone hotspot is the quickest controlled alternative.

## Scanning the code does not update the computer

Use the code inside HandOver's **Pair a Phone** flow, not a screenshot of an older code. Pairing claims expire quickly and are single-use.

- Keep the computer's pairing sheet open while scanning.
- Open the link in the HandOver app when iOS asks.
- Confirm the phone is already signed in if the code is also approving account access.
- If the computer remains unchanged, close the sheet and create a fresh code rather than rescanning the old one.
- Confirm both apps show the same hub address; a code from another running hub can connect successfully to the wrong session.

The code never contains a reusable bearer token. The phone approves a short-lived claim and the computer receives its own token.

## Meta Developer Mode is missing

In Meta AI, open **Settings → App Info** and tap the version five times. Return to the paired glasses' settings and look for **Developer Mode**. Update Meta AI first if the row still does not appear.

Developer Mode is a setting in Meta AI, not iPhone Settings and not the HandOver Xcode project.

## Meta AI returns “internal error”

Reset only the registration path:

1. Force-quit HandOver and Meta AI on the iPhone.
2. Reopen Meta AI and confirm the glasses show connected.
3. Open the glasses' **Developer Mode**, turn it off, then back on.
4. If an **Install** or **Update** action appears beside the developer access app on the glasses, run it and wait for completion.
5. Reopen HandOver, choose **Meta Glasses**, and tap **Connect Meta Glasses** once.
6. Finish the approval in Meta AI and return to HandOver; do not start a second registration while the first is pending.

If it still fails, record the exact HandOver state and Xcode console error. `CAPABILITY_DENIED`, a registration callback failure, a firmware update requirement, and a camera-permission timeout are different failures and need different fixes.

## The glasses connect but no video arrives

- Open the hinges and keep the glasses on or awake.
- Confirm Meta AI still names the glasses as connected to this iPhone.
- Complete the camera permission prompt in Meta AI; registration alone is not camera permission.
- Return HandOver to the foreground and wait for its glasses preview before starting the lesson.
- If the screen says an update is required, update the glasses or the developer access app in Meta AI.
- Stop and reconnect once. Repeatedly tapping Connect while the toolkit is busy can turn one failure into overlapping requests.

HandOver falls back to the phone camera when a glasses stream fails. A hub-connected phone is not proof that the active source is the glasses; check the source label beside the preview.

## Audio plays from the phone instead of the glasses

The glasses camera stream and iPhone audio output are separate routes. Open iPhone Control Center, open the AirPlay/audio destination picker, and select the Ray-Ban output before the lesson. HandOver's audio control names the route iOS reports.

If the glasses do not appear as an audio destination, resolve their normal Bluetooth audio connection in Meta AI/iOS first. Camera permission cannot force an unavailable speaker route.

## Audio continues after Next or after closing Learn

The current app treats every step change, End action, Learn disappearance, inactive scene, and desktop window close as a hard media boundary: the outgoing player is muted and detached, speech callbacks are invalidated, chimes stop, and the iOS audio session deactivates.

For an older build that is already playing:

- iPhone: open the app switcher and swipe HandOver away.
- Mac desktop: quit HandOver with **⌘Q**; closing the current single window should also quit current builds.

Then install the latest build before reproducing. When reporting the problem, say whether the sound was the expert clip, spoken step guidance, a correction, or the verification chime; they use different playback paths.

## The browser camera does not open

Mobile browsers require a trusted secure page for camera access:

```sh
scripts/certs.sh
scripts/run_server.sh
```

Open the printed `https://<laptop-ip>:8443/capture` address and trust the local certificate authority on the phone as the script instructs. Rerun certificate setup when the laptop's LAN IP changes. The native phone apps do not use this browser certificate flow.

## Port 8000 is already in use

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Inspect the listed process and its working directory. Stop only the confirmed stale HandOver hub, then restart. On Windows, use:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000 | Select-Object LocalPort,OwningProcess
```

## Checks are off

The learner can always use **Next**. The screen and hub state distinguish the common causes:

| Reason | Fix |
| --- | --- |
| `no_key` | Add the selected provider's key to `.env` and restart. |
| `budget` | Review `python -m server.spend`; intentionally change the cap or switch providers. |
| `rate_limited` | Wait for the breaker retry or switch providers. |
| `errors` | Read the first `check failed` or timeout line in the hub log. |

Never put keys in a QR code, lesson file, screenshot, issue, or committed configuration.

## The app closes unexpectedly

First determine which app crashed: the iPhone app, native Apple Mac app, Tauri desktop app, or local hub. Save the crash report and the last hub log lines.

For the desktop app, verify that only one installed copy is being opened. Development bundles in build folders and an older copy in Applications can look identical. For the iPhone app, reinstall the current signed build from Xcode and reproduce once with the Xcode console attached.

## Analytics or profile numbers are missing

The profile is built from completed run metadata, not camera media. Finish a run while signed in and refresh the profile. Mock and replay runs remain labeled and may be excluded from production-oriented totals.

Databricks is optional. Missing credentials or an unavailable warehouse must not delay the learner loop; local events remain in the configured JSONL mirror. See [analytics.md](analytics.md) and [the Databricks runbook](../databricks/README.md).

## Collect a useful report

Include:

- commit and branch;
- phone/computer OS and app build;
- hub address and the hub process working directory;
- course and step;
- camera source (phone, computer, replay, or exact glasses model);
- the on-screen state and exact error;
- whether mock or a named real provider was active;
- the smallest action sequence that reproduces the problem.

Do not attach learner frames, API keys, auth tokens, `.env`, or real-person course media to a public issue.
