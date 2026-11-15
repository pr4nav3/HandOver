# HandOver for Apple platforms

The SwiftUI HandOver app runs on iPhone, iPad, and Mac. It can follow and control a course, stream the device camera to a hub, record an expert take, and—on iPhone—bridge a supported Meta glasses camera through Meta's Wearables Device Access Toolkit.

This is a development build. It is not on the App Store or TestFlight.

## Requirements

- macOS with Xcode 26.4 or later; the project targets iOS 18 and macOS 15
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)
- Swift 6
- An Apple ID in Xcode for a physical iPhone build
- For the glasses path: Meta AI, paired glasses, current firmware, and Developer Mode

The project pins [`meta-wearables-dat-ios`](https://github.com/facebook/meta-wearables-dat-ios) 1.0.1. Developer Mode uses Meta app ID and client token `0`; a distributable integration would need its own registered credentials and release process. Meta's toolkit reference lives in the [Wearables Developer Center](https://wearables.developer.meta.com/docs/reference/ios_swift/dat/latest/).

## Generate and open the project

```sh
cd apps/apple
xcodegen generate
open HandOver.xcodeproj
```

The generated `.xcodeproj` is intentionally not committed. `project.yml` is the source of truth for targets, resources, package versions, deployment targets, entitlements, and signing defaults.

### Run on a physical iPhone

1. Select the HandOver target and open **Signing & Capabilities**.
2. Enable automatic signing and choose your Team.
3. If the checked-in bundle identifier is not available to that team, give the target a unique reverse-domain identifier in `project.yml`, then regenerate.
4. Plug in and unlock the phone, trust the Mac, and enable iPhone Developer Mode when Xcode asks.
5. Choose the phone as the destination and press **Run**.

A free Personal Team is sufficient for a local development install. See [the full install guide](../../docs/install.md) for the hub, pairing, and seven-day signing note.

## Connect to a hub

Start the local hub from the repository root:

```sh
scripts/run_server.sh
```

In HandOver, scan the computer's **Pair a Phone** code or enter the printed `http://<laptop-ip>:8000` address. Both devices must be on a network that allows them to reach each other.

The normal learner flow is:

1. Confirm the hub connection.
2. Choose **iPhone Camera** or **Meta Glasses**.
3. Wait for the live preview.
4. Start a course.

Connection, camera source, and account are separate states. A connected hub does not imply that a camera is sending, and a glasses camera connection does not imply that iOS audio is routed to the glasses.

## Meta glasses

On the iPhone, pair the glasses in Meta AI, enable Developer Mode, then choose **Meta Glasses → Connect Meta Glasses** in HandOver. Registration and camera permission complete in Meta AI before the app receives frames. With the pinned toolkit 1.0.1, use Meta AI V292 or later and glasses firmware V128 or later.

The implementation is contained in:

| File | Responsibility |
| --- | --- |
| `Sources/Features/Record/GlassesToolkit.swift` | Toolkit configuration, registration, permission, discovery, stream lifecycle, frame conversion, and toolkit errors |
| `Sources/Features/Record/GlassesSource.swift` | App-facing states, actions, source model, and recording adapter |
| `Sources/Features/Camera/CameraView.swift` | Glasses preview and newest-frame upload to `/ws/camera` |
| `Sources/Features/Learn/CameraChoiceSheet.swift` | The learner's phone-camera / glasses choice and setup state |

The repository has one recorded signed Ray-Ban Meta Gen 2 live-flow result. Other phone, firmware, and glasses combinations remain manual release evidence. See [validation.md](../../docs/validation.md).

## Audio behavior

Expert clips, spoken guidance, and verification chimes share one lesson lifecycle:

- changing steps invalidates the previous clip and speech generation;
- leaving Learn, ending the course, or backgrounding the app hard-stops all lesson audio;
- the iOS audio session allows Bluetooth A2DP and reports the current destination;
- the user still chooses the physical output in iOS Control Center.

This boundary is covered by focused tests in `Tests/LearnTests.swift`.

## Tests

Generate the project first, then run the macOS test host:

```sh
cd apps/apple
xcodegen generate
xcodebuild -project HandOver.xcodeproj -scheme HandOver \
  -destination 'platform=macOS' test
```

A successful macOS test is not a signed iPhone or physical-glasses result. Before claiming a device flow, build for that exact iPhone and complete the checklist in [docs/validation.md](../../docs/validation.md).

## Screenshots

`screenshots/` contains deterministic application snapshots backed by synthetic fixtures. They prove layout and state rendering, not camera accuracy, Bluetooth behavior, or provider performance. Do not replace them with real learner content.

## More documentation

- [Install and connect](../../docs/install.md)
- [Troubleshooting](../../docs/troubleshooting.md)
- [Protocol](../../CONTRACT.md)
- [Privacy](../../docs/privacy.md)
- [Validation](../../docs/validation.md)
