import CoreGraphics
import Foundation
import Testing
@testable import HandOver

// Onboarding, accounts, orgs, camera pipeline and window crop: the logic under the setup screens.

struct OnboardingStateTests {
    @Test func freshInstallStartsWithWelcomeThenConnect() {
        var p = OnboardingProgress()
        #expect(p.next == .welcome)
        #expect(p.stepLabel == nil)
        p.finishWelcome()
        #expect(p.next == .connect)
        #expect(p.backTarget == .welcome)
    }

    @Test func openHubSkipsAccounts() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .open)
        #expect(p.next == .role)
        #expect(p.visibleSteps == [.connect, .role, .theme])
        #expect(p.stepLabel == "Step 2 of 3")
        p.complete(.role)
        #expect(p.next == .theme)
        p.complete(.theme)
        #expect(p.next == .done)
        #expect(p.finished)
    }

    @Test func newHubRunsOwnerSetupThenProfile() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .needsOwner, signInOptional: false)
        #expect(p.next == .ownerSetup)
        #expect(p.backTarget == .connect)
        p.signedIn(madeAccount: true, orgsOffered: true)
        #expect(p.next == .profile)
        #expect(p.backTarget == nil, "Back never crosses a finished sign-in")
        #expect(p.visibleSteps == [.connect, .ownerSetup, .profile, .joinOrg, .role, .theme])
        p.complete(.profile, skipped: true)
        #expect(p.skipped.contains(.profile))
        #expect(p.next == .joinOrg)
        p.complete(.joinOrg)
        #expect(p.next == .role)
        #expect(p.backTarget == .joinOrg)
        p.goBack()
        #expect(p.next == .joinOrg)
    }

    @Test func someoneElseFinishingSetupMeansSignIn() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .needsOwner, signInOptional: false)
        p.ownerTaken()
        #expect(p.next == .account)
    }

    @Test func requiredSignInCannotBeSkippedButOptionalCan() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .accounts, signInOptional: false)
        p.complete(.account, skipped: true)
        #expect(p.next == .account)
        p.connected(kind: .accounts, signInOptional: true)
        p.complete(.account, skipped: true)
        #expect(p.next == .role)
    }

    @Test func existingMemberSkipsProfileAndOrgsWhenInOne() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .accounts)
        p.signedIn(madeAccount: false, orgsOffered: false)
        #expect(p.next == .role)
        #expect(p.visibleSteps == [.connect, .account, .role, .theme])
    }

    @Test func goingBackToConnectForgetsTheHubChoice() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .accounts)
        #expect(p.next == .account)
        p.goBack()
        #expect(p.next == .connect)
        #expect(p.hubKind == nil)
    }

    @Test func progressResumesFromStorage() {
        let suite = "handover.tests.onboarding.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = OnboardingStore(defaults: defaults)
        var p = store.load()
        #expect(p.next == .welcome)
        p.finishWelcome()
        p.connected(kind: .open)
        store.save(p)
        #expect(store.load().next == .role)
    }

    @Test func installsThatAlreadyHaveHubsSkipOnboarding() {
        let suite = "handover.tests.onboarding.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        HubRecents(defaults: defaults).save([HubURL(parsing: "10.0.0.2")!])
        #expect(OnboardingStore(defaults: defaults).load().finished)
    }

    @Test func replayShowsWelcomeAgainOnly() {
        var p = OnboardingProgress()
        p.finishWelcome()
        p.connected(kind: .open)
        p.complete(.role)
        p.complete(.theme)
        p.replayWelcome()
        #expect(p.next == .welcome)
        p.finishWelcome()
        #expect(p.next == .done)
    }
}

struct InviteCodeTests {
    @Test func keepsCaseAndDashesDropsSpaces() {
        let code = InviteCode(parsing: "  K7qM 2x-A 9bc_ dEfG ")
        #expect(code?.code == "K7qM2x-A9bc_dEfG")
        #expect(code?.hub == nil)
    }

    @Test func rejectsJunk() {
        #expect(InviteCode(parsing: "") == nil)
        #expect(InviteCode(parsing: "abc") == nil, "too short")
        #expect(InviteCode(parsing: "hello world!") == nil, "bad character")
        #expect(InviteCode(parsing: "ftp://x?y=1") == nil, "a link with no code")
    }

    @Test func readsJoinLinksWithHub() {
        let link = InviteCode.link(code: "AbC-123_xyz", hub: HubURL(parsing: "192.168.1.20:8000"))
        let parsed = InviteCode(parsing: link.absoluteString)
        #expect(parsed?.code == "AbC-123_xyz")
        #expect(parsed?.hub?.displayName == "192.168.1.20:8000")
        #expect(InviteCode.isJoinLink(link))
    }

    @Test func readsHostAndPortForm() {
        let parsed = InviteCode(parsing: "handover://join?host=10.0.0.5&port=9000&code=ZZZZ1111")
        #expect(parsed?.code == "ZZZZ1111")
        #expect(parsed?.hub?.displayName == "10.0.0.5:9000")
    }

    @Test func groupsInFoursAndSpellsOut() {
        #expect(InviteCode.grouped("K7qM2xPA9bc_") == "K7qM 2xPA 9bc_")
        #expect(InviteCode.spoken("K7-") == "capital K 7 dash")
    }

    @Test func expiryChoicesFitTheHub() {
        for choice in InviteExpiry.allCases { #expect((0.01...90).contains(choice.rawValue)) }
        #expect(InviteUses.unlimited.maxUses == nil)
        #expect(InviteUses.one.maxUses == 1)
    }
}

struct PasscodeStrengthTests {
    @Test func rules() {
        #expect(PasscodeStrength("12") == .tooShort)
        #expect(PasscodeStrength("1234") == .easy)
        #expect(PasscodeStrength("4821") == .easy, "4 to 5 characters is easy")
        #expect(PasscodeStrength("aaaaaaaa") == .easy, "one character repeated")
        #expect(PasscodeStrength("abcdefgh") == .easy, "a run")
        #expect(PasscodeStrength("hx7qpz") == .okay)
        #expect(PasscodeStrength("bluefox9") == .strong)
        #expect(PasscodeStrength("bluefoxy") == .okay, "8 letters with no digit")
    }
}

struct TokenStoreTests {
    @Test func savesReplacesAndDeletesOnlyItsOwnItems() {
        let store = TokenStore(service: "com.soham109.handover.tests.\(UUID().uuidString)")
        defer { store.deleteAll() }
        let hub = HubURL(parsing: "192.168.1.20:8000")!
        let other = HubURL(parsing: "10.0.0.9")!
        #expect(store.token(for: hub) == nil)
        #expect(store.save("first", for: hub))
        #expect(store.token(for: hub) == "first")
        #expect(store.save("second", for: hub))
        #expect(store.token(for: hub) == "second")
        #expect(store.token(for: other) == nil)
        store.delete(for: hub)
        #expect(store.token(for: hub) == nil)
    }
}

struct OrgModelTests {
    private func org(role: OrgRole?, admins: Int, owner: String = "x") -> OrgDetail {
        var members = (0..<admins).map { OrgMember(userId: "a\($0)", name: "Admin \($0)", role: .admin) }
        members.append(OrgMember(userId: "me", name: "Me", role: role ?? .learner))
        if role == nil { members.removeLast() }
        return OrgDetail(id: "o", name: "Shop", role: role, owner: OrgInvite.Person(id: owner, name: "Owner"),
                         members: members, courses: [], invites: nil)
    }

    @Test func decodesHubAnswers() throws {
        let json = """
        {"orgs":[{"id":"o1","name":"Bike Shop","slug":"bike-shop","created":"2026-11-01T10:00:00.000Z","members":3,"role":"org_admin"}],
         "invites":[{"id":"i1","kind":"user","role":"teacher","created":"2026-11-01T10:00:00.000Z","expires":"2026-12-01T10:00:00Z",
                     "created_by":"Sam","user":{"id":"u2","name":"Ana"},"org":{"id":"o2","name":"Class","slug":"class"}}]}
        """
        let mine = try JSONDecoder().decode(MyOrgs.self, from: Data(json.utf8))
        #expect(mine.orgs.first?.role == .admin)
        #expect(mine.invites.first?.org?.name == "Class")
        #expect(mine.invites.first?.expiryDate != nil)
    }

    @Test func membersSeeNoAdminActions() {
        let can = OrgPermissions(org: org(role: .learner, admins: 1), me: HubUser(id: "me", name: "Me", role: .learner))
        #expect(!can.canTeach && !can.canInvite && !can.canManageMembers && !can.canDelete)
        #expect(can.canLeave)
    }

    @Test func lastAdminCannotLeaveOrBeEdited() {
        let detail = org(role: .admin, admins: 0)
        let me = HubUser(id: "me", name: "Me", role: .learner)
        let can = OrgPermissions(org: detail, me: me)
        #expect(can.canInvite && can.canTeach)
        #expect(!can.canLeave, "the only admin")
        #expect(!can.canEdit(detail.members[0], in: detail, me: me), "not yourself")
    }

    @Test func hubOwnerManagesWithoutMembership() {
        let detail = org(role: nil, admins: 2)
        let owner = HubUser(id: "boss", name: "Boss", role: .owner)
        let can = OrgPermissions(org: detail, me: owner)
        #expect(can.canInvite && can.canDelete && !can.canLeave)
        #expect(can.canEdit(detail.members[0], in: detail, me: owner))
    }
}

struct FramePipelineTests {
    @Test func downscalesTo960LongSideKeepingAspect() {
        #expect(FrameSizing.target(for: CGSize(width: 1920, height: 1080)) == CGSize(width: 960, height: 540))
        #expect(FrameSizing.target(for: CGSize(width: 1080, height: 1920)) == CGSize(width: 540, height: 960))
        #expect(FrameSizing.target(for: CGSize(width: 4032, height: 3024)) == CGSize(width: 960, height: 720))
    }

    @Test func neverUpscalesAndKeepsEvenSizes() {
        #expect(FrameSizing.target(for: CGSize(width: 640, height: 480)) == CGSize(width: 640, height: 480))
        let odd = FrameSizing.target(for: CGSize(width: 1281, height: 721))
        #expect(Int(odd.width) % 2 == 0 && Int(odd.height) % 2 == 0)
        #expect(FrameSizing.target(for: .zero) == .zero)
    }

    @Test func encoderMakesASmallJPEG() throws {
        let image = try #require(SyntheticFrames.noise(width: 1920, height: 1080))
        let encoder = FrameEncoder.shared
        let small = try #require(encoder.downscale(CIImageMaker.make(image)))
        #expect(small.width == 960 && small.height == 540)
        let jpeg = try #require(encoder.jpeg(small))
        #expect(HubMessage.isJPEG(jpeg))
        #expect(jpeg.count < CameraSocket.maxFrameBytes)
    }

    @Test func slotKeepsOnlyTheNewestFrame() async {
        let slot = LatestFrameSlot<Int>()
        slot.put(1)
        slot.put(2)
        slot.put(3)
        #expect(await slot.take() == 3)
        #expect(slot.replacedCount == 2)
        #expect(slot.poll() == nil)
        let waiting = Task { await slot.take() }
        try? await Task.sleep(for: .milliseconds(20))
        slot.put(9)
        #expect(await waiting.value == 9)
        slot.close()
        #expect(await slot.take() == nil)
    }

    @Test func fpsCountsOnlyRealSends() {
        var rate = SendRate(window: 5)
        for i in 0..<10 { rate.record(Double(i) * 0.5) }   // 2 per second for 5 s
        #expect(abs(rate.fps(now: 5, since: 0) - 2) < 0.01)
        #expect(rate.fps(now: 20, since: 0) == 0, "nothing sent lately")
        var fresh = SendRate()
        fresh.record(0.2)
        #expect(fresh.fps(now: 0.5, since: 0) == 1, "never divides by less than a second")
    }
}

struct CallCropTests {
    private func iou(_ a: CGRect, _ b: CGRect) -> Double {
        let i = a.intersection(b)
        guard !i.isNull else { return 0 }
        let inter = i.width * i.height
        return inter / (a.width * a.height + b.width * b.height - inter)
    }

    @Test func findsTheVideoInACallWindow() throws {
        // A 1280 x 800 call window: title bar, a sidebar of text, a flat control bar, and the video.
        let video = CGRect(x: 0.25, y: 0.08, width: 0.72, height: 0.74)
        let frame = try #require(SyntheticFrames.callWindow(width: 1280, height: 800, video: video))
        let found = CallCrop.detect(in: frame)
        #expect(iou(found, video) > 0.85, "found \(found)")
    }

    @Test func findsAVideoWithASelfViewInside() throws {
        let video = CGRect(x: 0.05, y: 0.10, width: 0.90, height: 0.70)
        let frame = try #require(SyntheticFrames.callWindow(width: 1000, height: 1000, video: video, selfView: true, sidebar: false))
        let found = CallCrop.detect(in: frame)
        #expect(iou(found, video) > 0.85, "found \(found)")
    }

    @Test func flatWindowFallsBackToTheWholeFrame() throws {
        let frame = try #require(SyntheticFrames.flat(width: 800, height: 600))
        #expect(CallCrop.detect(in: frame) == CallCrop.full)
    }

    @Test func pixelRectsAreEvenAndInside() {
        let r = CallCrop.pixels(CGRect(x: 0.1, y: 0.1, width: 0.95, height: 0.5), in: CGSize(width: 1001, height: 701))
        #expect(Int(r.minX) % 2 == 0 && Int(r.width) % 2 == 0)
        #expect(r.maxX <= 1001)
    }

    @Test func rememberedCropIsPerApp() {
        let suite = "handover.tests.crop.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let memory = CallCropMemory(defaults: defaults)
        memory.save(CGRect(x: 0.1, y: 0.2, width: 0.5, height: 0.6), for: "net.whatsapp.WhatsApp")
        #expect(memory.crop(for: "net.whatsapp.WhatsApp") == CGRect(x: 0.1, y: 0.2, width: 0.5, height: 0.6))
        #expect(memory.crop(for: "com.apple.FaceTime") == nil)
    }
}

// MARK: - Synthetic images (no screen is ever captured in tests)

import CoreImage

enum CIImageMaker {
    static func make(_ image: CGImage) -> CIImage { CIImage(cgImage: image) }
}

enum SyntheticFrames {
    private static func context(_ w: Int, _ h: Int) -> CGContext? {
        CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                  space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    }

    /// Deterministic textured noise, like camera video.
    private static func fillNoise(_ ctx: CGContext, _ rect: CGRect, seed: UInt64 = 7) {
        var state = seed
        func next() -> CGFloat {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return CGFloat((state >> 33) % 1000) / 1000
        }
        let step: CGFloat = 4
        var y = rect.minY
        while y < rect.maxY {
            var x = rect.minX
            while x < rect.maxX {
                let base = 0.25 + 0.5 * (x - rect.minX) / rect.width
                ctx.setFillColor(CGColor(srgbRed: base + next() * 0.3, green: 0.3 + next() * 0.4, blue: 0.4 + next() * 0.3, alpha: 1))
                ctx.fill(CGRect(x: x, y: y, width: step, height: step))
                x += step
            }
            y += step
        }
    }

    static func noise(width: Int, height: Int) -> CGImage? {
        guard let ctx = context(width, height) else { return nil }
        fillNoise(ctx, CGRect(x: 0, y: 0, width: width, height: height))
        return ctx.makeImage()
    }

    static func flat(width: Int, height: Int) -> CGImage? {
        guard let ctx = context(width, height) else { return nil }
        ctx.setFillColor(CGColor(srgbRed: 0.95, green: 0.95, blue: 0.96, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return ctx.makeImage()
    }

    /// `video` is normalized with a top-left origin.
    static func callWindow(width: Int, height: Int, video: CGRect, selfView: Bool = false, sidebar: Bool = true) -> CGImage? {
        guard let ctx = context(width, height) else { return nil }
        let W = CGFloat(width), H = CGFloat(height)
        // CoreGraphics draws bottom-up; flip so rects read top-left.
        ctx.translateBy(x: 0, y: H)
        ctx.scaleBy(x: 1, y: -1)
        ctx.setFillColor(CGColor(srgbRed: 0.12, green: 0.13, blue: 0.14, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
        // Title bar.
        ctx.setFillColor(CGColor(srgbRed: 0.2, green: 0.2, blue: 0.22, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: W, height: 28))
        if sidebar {
            // Lines of "text": thin light bars with gaps, busy but broken into pieces.
            ctx.setFillColor(CGColor(srgbRed: 0.85, green: 0.85, blue: 0.85, alpha: 1))
            var y: CGFloat = 60
            while y < H - 40 {
                ctx.fill(CGRect(x: 20, y: y, width: CGFloat(80 + Int(y) % 90), height: 3))
                y += 46
            }
        }
        let v = CGRect(x: video.minX * W, y: video.minY * H, width: video.width * W, height: video.height * H)
        fillNoise(ctx, v)
        if selfView {
            ctx.setFillColor(CGColor(srgbRed: 0.6, green: 0.5, blue: 0.4, alpha: 1))
            ctx.fill(CGRect(x: v.maxX - v.width * 0.25, y: v.maxY - v.height * 0.3, width: v.width * 0.2, height: v.height * 0.25))
        }
        // Control bar: three round buttons on flat color under the video.
        ctx.setFillColor(CGColor(srgbRed: 0.9, green: 0.2, blue: 0.2, alpha: 1))
        for i in 0..<3 {
            ctx.fillEllipse(in: CGRect(x: v.midX - 90 + CGFloat(i) * 70, y: min(H - 50, v.maxY + 30), width: 40, height: 40))
        }
        return ctx.makeImage()
    }
}
