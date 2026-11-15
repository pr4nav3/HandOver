import CoreGraphics
import Testing
@testable import HandOver

/// The pure pieces behind landscape: camera angles and the layout picks.
struct LandscapeTests {
    // MARK: - Camera angles

    @Test func anglesSnapToRightAngles() {
        #expect(CameraRotation.snapped(0) == 0)
        #expect(CameraRotation.snapped(90) == 90)
        #expect(CameraRotation.snapped(180) == 180)
        #expect(CameraRotation.snapped(270) == 270)
        #expect(CameraRotation.snapped(360) == 0)
        #expect(CameraRotation.snapped(450) == 90)
        #expect(CameraRotation.snapped(-90) == 270)
        #expect(CameraRotation.snapped(89.6) == 90)
        #expect(CameraRotation.snapped(316) == 0)
        #expect(CameraRotation.snapped(.nan) == 0)
        #expect(CameraRotation.snapped(.infinity) == 0)
    }

    // MARK: - Learn layout

    static func near(_ a: CGFloat, _ b: CGFloat) -> Bool { abs(a - b) < 1e-9 }

    /// iPhone 17 and 18 Pro, inside the safe area.
    static let phonePortrait = CGSize(width: 402, height: 778)
    static let phoneLandscape = CGSize(width: 750, height: 381)
    static let maxLandscape = CGSize(width: 832, height: 419)
    static let miniLandscape = CGSize(width: 690, height: 354)
    static let iPadLandscape = CGSize(width: 1180, height: 800)
    static let iPadPortrait = CGSize(width: 820, height: 1160)

    @Test func phoneOnItsSideGetsThePhoneSideBySide() {
        #expect(LearnLayout.pickTouch(size: Self.phoneLandscape, compactHeight: true) == .sideBySide(phone: true))
        #expect(LearnLayout.pickTouch(size: Self.maxLandscape, compactHeight: true) == .sideBySide(phone: true))
        #expect(LearnLayout.pickTouch(size: Self.miniLandscape, compactHeight: true) == .sideBySide(phone: true))
        // Without a size class (snapshots), the height alone decides.
        #expect(LearnLayout.pickTouch(size: Self.phoneLandscape, compactHeight: false) == .sideBySide(phone: true))
    }

    @Test func uprightPhoneGetsPiPAndIPadGetsTheFullLayout() {
        #expect(LearnLayout.pickTouch(size: Self.phonePortrait, compactHeight: false) == .pip)
        #expect(LearnLayout.pickTouch(size: Self.iPadLandscape, compactHeight: false) == .sideBySide(phone: false))
        #expect(LearnLayout.pickTouch(size: Self.iPadPortrait, compactHeight: false) == .sideBySide(phone: false))
        // iPad Slide Over and narrow Split View are upright phones in shape.
        #expect(LearnLayout.pickTouch(size: CGSize(width: 320, height: 1000), compactHeight: false) == .pip)
    }

    @Test func landscapeColumnLeavesTheClipMostOfTheScreen() {
        for size in [Self.miniLandscape, Self.phoneLandscape, Self.maxLandscape] {
            let column = LearnLayout.phoneColumnWidth(for: size.width)
            #expect(column >= 240 && column <= 320)
            #expect(size.width - column > size.width / 2, "clip gets more than half at \(size.width)")
        }
        #expect(LearnLayout.phoneColumnWidth(for: 500) == 240)
        #expect(LearnLayout.phoneColumnWidth(for: 2000) == 320)
    }

    @Test func liveTileTakesThePictureShape() {
        // Frames from another device keep their own shape.
        #expect(Self.near(LearnLayout.liveAspect(frame: CGSize(width: 960, height: 540), ownCamera: false, landscape: true), 960.0 / 540.0))
        #expect(Self.near(LearnLayout.liveAspect(frame: CGSize(width: 540, height: 960), ownCamera: false, landscape: true), 540.0 / 960.0))
        // This phone's camera turns with the phone.
        #expect(Self.near(LearnLayout.liveAspect(frame: nil, ownCamera: true, landscape: true), 16.0 / 9.0))
        #expect(Self.near(LearnLayout.liveAspect(frame: nil, ownCamera: true, landscape: false), 9.0 / 16.0))
        // Nothing yet, or an empty size.
        #expect(Self.near(LearnLayout.liveAspect(frame: nil, ownCamera: false, landscape: true), 4.0 / 3.0))
        #expect(Self.near(LearnLayout.liveAspect(frame: .zero, ownCamera: false, landscape: true), 4.0 / 3.0))
    }

    // MARK: - Onboarding

    @Test func onboardingKnowsAShortScreen() {
        // iPhone landscape minus the top bar is short; portrait, iPad and the Mac window are not.
        #expect(HOLayout.isShort(381 - 52))
        #expect(!HOLayout.isShort(778 - 52))
        #expect(!HOLayout.isShort(720 - 52))
        #expect(!HOLayout.isShort(560 - 52))
    }

    @Test func welcomePagesGoSideBySideOnlyWhenShortAndWide() {
        #expect(WelcomePages.isSideBySide(CGSize(width: 750, height: 329)))
        #expect(!WelcomePages.isSideBySide(CGSize(width: 402, height: 726)))
        #expect(!WelcomePages.isSideBySide(CGSize(width: 720, height: 508)))  // Mac window
        #expect(!WelcomePages.isSideBySide(CGSize(width: 600, height: 668)))  // iPad card
    }
}
