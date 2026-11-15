package com.handover.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.captureRoboImage
import com.handover.app.R
import com.handover.app.core.HubUrl
import com.handover.app.ui.account.AccountModel
import com.handover.app.ui.account.AccountState
import com.handover.app.ui.account.AccountSupport
import com.handover.app.core.Capabilities
import com.handover.app.core.CourseItem
import com.handover.app.core.CourseProgress
import com.handover.app.core.HubUser
import com.handover.app.ui.account.InvitePage
import com.handover.app.ui.account.InvitePreview
import com.handover.app.ui.account.JoinOrgPage
import com.handover.app.core.Org
import com.handover.app.ui.account.OrgDetailPage
import com.handover.app.core.OrgInvite
import com.handover.app.core.OrgLesson
import com.handover.app.core.OrgMember
import com.handover.app.core.OrgPage
import com.handover.app.ui.account.OrgWelcomeCard
import com.handover.app.ui.account.OrgsListPage
import com.handover.app.ui.account.OwnerSetupPage
import com.handover.app.ui.account.ProfilePage
import com.handover.app.ui.account.SignInPage
import com.handover.app.core.MemoryTokenStore
import com.handover.app.ui.camera.CameraModeContent
import com.handover.app.ui.camera.CameraPhase
import com.handover.app.ui.camera.CameraUi
import com.handover.app.ui.camera.FrameSize
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.glasses.GlassesCard
import com.handover.app.ui.glasses.GlassesDevice
import com.handover.app.ui.glasses.GlassesPhase
import com.handover.app.ui.glasses.GlassesState
import com.handover.app.ui.onboarding.ConnectPage
import com.handover.app.ui.onboarding.HomeFirst
import com.handover.app.ui.onboarding.PermissionAsk
import com.handover.app.ui.onboarding.PermissionCard
import com.handover.app.ui.onboarding.ProfileStep
import com.handover.app.ui.onboarding.RoleStep
import com.handover.app.ui.onboarding.ThemeStep
import com.handover.app.ui.onboarding.WelcomePages
import com.handover.app.ui.pairing.ConnectState
import com.handover.app.ui.pairing.ConnectStatusScreen
import com.handover.app.ui.pairing.RecentHub
import com.handover.app.ui.pairing.ScannerScreen
import com.handover.app.ui.pairing.TypedAddressScreen
import com.handover.app.ui.settings.AppSettings
import com.handover.app.ui.settings.SettingsMain
import com.handover.app.ui.settings.SettingsUi
import com.handover.app.ui.settings.ThemePicker
import com.handover.app.ui.theme.Appearance
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOverSurface
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeSpec
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import okhttp3.OkHttpClient
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Pairing, Camera Mode (phone and glasses), Settings, the theme picker, account, organizations and
 * onboarding, drawn on the JVM at a 412 x 915 dp phone. Images land in apps/android/screenshots.
 * ./gradlew :app:testDebugUnitTest --tests '*SetupScreenshotTest*' -Proborazzi.test.record=true
 * Data is plain and labeled; no stats are shown that a real hub would not send.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w412dp-h915dp-xhdpi")
class SetupScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private val now = 1_800_000_000_000L
    private val hour = 3_600_000L

    private fun shot(name: String, dark: Boolean = false, theme: ThemeSpec = ThemeCatalog.system, advance: Long = 2_000, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            HandOverTheme(theme, dark, reduceMotion = false) {
                CompositionLocalProvider(LocalInspectionMode provides true) {
                    HandOverSurface { Box(Modifier.fillMaxSize()) { content() } }
                }
            }
        }
        compose.mainClock.advanceTimeBy(advance)
        compose.onRoot().captureRoboImage("../screenshots/$name.png")
    }

    // ------------------------------------------------------------ pairing

    @Test fun pairingScan() = shot("pairing-scan") {
        ScannerScreen(true, true, found = false, problem = null, shakes = 0, title = "Scan the hub's code",
            hint = "On the computer running HandOver, open http://localhost:8000 and click Show Code.", onPaste = {}, onTyped = {}, onClose = {})
    }

    @Test fun pairingScanFound() = shot("pairing-scan-found") {
        ScannerScreen(true, true, found = true, problem = null, shakes = 0, title = "Scan the hub's code",
            hint = "On the computer running HandOver, open http://localhost:8000 and click Show Code.", onPaste = {}, onTyped = {}, onClose = {})
    }

    @Test fun pairingScanBadCode() = shot("pairing-scan-bad-code") {
        ScannerScreen(true, true, found = false, problem = "That code is not a HandOver hub.", shakes = 0, title = "Scan the hub's code",
            hint = "On the computer running HandOver, open http://localhost:8000 and click Show Code.", onPaste = {}, onTyped = {}, onClose = {})
    }

    @Test fun pairingNoCamera() = shot("pairing-scan-no-camera") {
        ScannerScreen(false, false, found = false, problem = null, shakes = 0, title = "Scan the hub's code",
            hint = "On the computer running HandOver, open http://localhost:8000 and click Show Code.", onPaste = {}, onTyped = {}, onClose = {})
    }

    private val recent = listOf(
        RecentHub("192.168.1.20:8000", "Workshop hub", now - 2 * hour),
        RecentHub("10.0.0.7:8000", null, now - 3 * 24 * hour),
    )

    @Test fun pairingTyped() = shot("pairing-typed") {
        TypedAddressScreen("192.168.1.20:8000", {}, recent, {}, {}, {}, {}, now = now)
    }

    @Test fun pairingTypedEmptyDark() = shot("pairing-typed-dark", dark = true) {
        TypedAddressScreen("", {}, emptyList(), {}, {}, {}, {}, now = now)
    }

    @Test fun pairingConnecting() = shot("pairing-connecting") { ConnectStatusScreen(ConnectState.Connecting("Workshop hub"), {}, {}, {}) }
    @Test fun pairingConnected() = shot("pairing-connected") { ConnectStatusScreen(ConnectState.Connected("Workshop hub", 2), {}, {}, {}) }
    @Test fun pairingError() = shot("pairing-error") {
        ConnectStatusScreen(ConnectState.Unreachable("192.168.1.20", "Nothing is listening at that address and port."), {}, {}, {})
    }
    @Test fun pairingNotAHub() = shot("pairing-not-a-hub", dark = true) { ConnectStatusScreen(ConnectState.NotAHub("192.168.1.1"), {}, {}, {}) }

    // ------------------------------------------------------------ camera mode

    @Composable
    private fun Frame() = Image(painterResource(R.drawable.onboarding_frame_04), "Sample frame", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())

    private val sending = CameraUi(
        hubName = "Workshop hub", phase = CameraPhase.Sending, fps = 1.0, size = FrameSize(960, 540),
        stepTitle = "Step 4 of 8: Fold all four corners to center", badge = BadgeState.Watching, canBack = true, canNext = true,
    )

    @Test fun cameraMode() = shot("camera-mode") { CameraModeContent(sending) { Frame() } }

    @Test fun cameraModeVerified() = shot("camera-mode-verified") {
        CameraModeContent(sending.copy(badge = BadgeState.Verified, statsShown = false)) { Frame() }
    }

    @Test fun cameraStandby() = shot("camera-standby") {
        CameraModeContent(sending.copy(phase = CameraPhase.Standby, fps = 0.0, stepTitle = null, canBack = false, canNext = false)) { Frame() }
    }

    @Test fun cameraLocked() = shot("camera-locked") { CameraModeContent(sending.copy(locked = true)) { Frame() } }

    @Test fun cameraReplaced() = shot("camera-replaced") { CameraModeContent(sending.copy(phase = CameraPhase.Replaced)) { Frame() } }

    @Test fun cameraConnecting() = shot("camera-connecting") {
        CameraModeContent(sending.copy(phase = CameraPhase.Connecting, fps = 0.0, size = null, stepTitle = null, canBack = false, canNext = false)) {
            Box(Modifier.fillMaxSize().background(Color(0xFF111111)))
        }
    }

    // ------------------------------------------------------------ glasses

    private val glassesUi = sending.copy(source = "Glasses", glasses = true, size = FrameSize(360, 640))

    @Test fun glassesConnect() = shot("glasses-connect") {
        CameraModeContent(glassesUi.copy(phase = CameraPhase.Sending, fps = 0.0, size = null), glassesCard = {
            GlassesCard(GlassesState(GlassesPhase.NotRegistered), {}, {})
        }) { Box(Modifier.fillMaxSize().background(Color.Black)) }
    }

    @Test fun glassesWaiting() = shot("glasses-waiting-meta-ai") {
        CameraModeContent(glassesUi.copy(fps = 0.0, size = null), glassesCard = { GlassesCard(GlassesState(GlassesPhase.Registering), {}, {}) }) {
            Box(Modifier.fillMaxSize().background(Color.Black))
        }
    }

    @Test fun glassesPermission() = shot("glasses-camera-permission") {
        CameraModeContent(glassesUi.copy(fps = 0.0, size = null), glassesCard = {
            GlassesCard(GlassesState(GlassesPhase.NeedsCameraPermission, GlassesDevice("Ray-Ban Meta", battery = 82, charging = false, thermal = "Normal", connected = true)), {}, {})
        }) { Box(Modifier.fillMaxSize().background(Color.Black)) }
    }

    @Test fun glassesMetaAiMissing() = shot("glasses-meta-ai-needed") {
        CameraModeContent(glassesUi.copy(fps = 0.0, size = null), glassesCard = { GlassesCard(GlassesState(GlassesPhase.MetaAiMissing), {}, {}) }) {
            Box(Modifier.fillMaxSize().background(Color.Black))
        }
    }

    @Test fun glassesTooHot() = shot("glasses-too-hot") {
        CameraModeContent(glassesUi.copy(fps = 0.0), glassesCard = {
            GlassesCard(GlassesState(GlassesPhase.TooHot, GlassesDevice("Ray-Ban Meta", thermal = "Hot", connected = true)), {}, {})
        }) { Box(Modifier.fillMaxSize().background(Color.Black)) }
    }

    @Test fun glassesFallbackToast() = shot("glasses-fallback-toast") {
        CameraModeContent(sending.copy(toast = "No picture from the glasses. Using the phone camera.")) { Frame() }
    }

    // ------------------------------------------------------------ settings and theme picker

    private val settingsUi = SettingsUi(
        hubTitle = "Workshop hub", hubAddress = "192.168.1.20:8000", connected = true,
        recent = listOf(RecentHub("10.0.0.7:8000", null, now - 3 * 24 * hour)),
        themeName = "Default", settings = AppSettings(), accounts = true, accountLine = "Sam Rivera, Owner",
        version = "0.1.0", voiceAvailable = true,
    )

    @Composable
    private fun Settings(ui: SettingsUi) = SettingsMain(ui, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, now = now)

    @Test fun settings() = shot("settings") { Settings(settingsUi) }
    @Test fun settingsDark() = shot("settings-dark", dark = true) { Settings(settingsUi.copy(appearance = Appearance.Dark)) }

    @Test @Config(qualifiers = "w412dp-h2400dp-xhdpi")
    fun settingsFull() = shot("settings-full") { Settings(settingsUi.copy(settings = AppSettings(voiceNext = true))) }

    @Test @Config(qualifiers = "w412dp-h2200dp-xhdpi")
    fun themePicker() = shot("theme-picker") {
        Column(Modifier.statusBarsPadding().padding(HOSpace.l)) { ThemePicker(ThemeCatalog.system, Appearance.System, {}, {}) }
    }

    @Test @Config(qualifiers = "w412dp-h2200dp-xhdpi")
    fun themePickerChalkboard() = shot("theme-picker-chalkboard", theme = ThemeCatalog.chalkboard) {
        Column(Modifier.statusBarsPadding().padding(HOSpace.l)) { ThemePicker(ThemeCatalog.chalkboard, Appearance.System, {}, {}) }
    }

    // ------------------------------------------------------------ account

    private val sam = HubUser("u1", "Sam Rivera", "owner")
    private val signedIn = AccountState(
        support = AccountSupport.Available, user = sam, capabilities = Capabilities(canCreateOrg = true),
        courses = listOf(
            // The repo's sample lesson: finished once, part way through a second run.
            CourseItem("synthetic-fortune-teller-v1", "Fold a fortune teller", 8, CourseProgress(known = true, runs = 2, completed = 1, lastStepsDone = 3, lastFinished = false, total = 8)),
        ),
        orgs = emptyList(),
    )

    @Test fun accountSignIn() = shot("account-sign-in") { SignInPage("Workshop hub", AccountState(support = AccountSupport.Available), { _, _ -> }) }
    @Test fun accountSignInError() = shot("account-sign-in-error") {
        SignInPage("Workshop hub", AccountState(support = AccountSupport.Available, error = "That name and passcode do not match."), { _, _ -> })
    }
    @Test fun accountOwnerSetup() = shot("account-owner-setup") {
        OwnerSetupPage("Workshop hub", AccountState(support = AccountSupport.Available, setupNeeded = true), { _, _ -> }, stepLabel = "Step 2 of 6")
    }
    @Test fun accountProfile() = shot("account-profile") { ProfilePage("Workshop hub", signedIn, {}, {}) }
    @Test fun accountProfileEmpty() = shot("account-profile-empty", dark = true) {
        ProfilePage("Workshop hub", signedIn.copy(courses = emptyList(), user = sam.copy(role = "learner")), {}, null)
    }

    // ------------------------------------------------------------ organizations

    private val shop = Org("o1", "Bike Shop Crew", slug = "bike-shop-crew", role = "org_admin", members = 4, lessons = 2)

    @Test fun orgsEmpty() = shot("orgs-empty") { OrgsListPage(emptyList(), canCreate = true, {}, {}, {}, {}) }
    @Test fun orgsList() = shot("orgs-list") {
        OrgsListPage(listOf(shop, Org("o2", "Saturday Origami", role = "learner", members = 12, lessons = 5)), canCreate = true, {}, {}, {}, {})
    }

    @Test fun orgJoin() = shot("org-join") {
        val model = AccountModel(MemoryTokenStore(), OkHttpClient(), CoroutineScope(Dispatchers.Unconfined))
        JoinOrgPage(model, null, {}, {})
    }

    @Test fun orgWelcome() = shot("org-welcome") {
        Column(Modifier.statusBarsPadding()) {
            OrgWelcomeCard(InvitePreview(shop.copy(role = "learner"), "learner", joined = true), busy = false, error = null, {}, {}, {},
                lessons = listOf(OrgLesson("synthetic-fortune-teller-v1", "Fold a fortune teller", 8)))
        }
    }

    private val page = OrgPage(
        shop,
        members = listOf(OrgMember("u1", "Sam Rivera", "org_admin"), OrgMember("u2", "Ana Cruz", "teacher"), OrgMember("u3", "Lee Park", "learner")),
        lessons = listOf(OrgLesson("synthetic-fortune-teller-v1", "Fold a fortune teller", 8)),
        // As the hub lists them: no code (it keeps a hash). The fresh one below has its code, as in the create reply.
        invites = listOf(OrgInvite("a1b2c3d4e5f6", "code", "learner", expires = "2026-11-21T17:00:00Z", maxUses = null, uses = 3)),
    )
    private val freshCode = OrgInvite("f6e5d4c3b2a1", "code", "teacher", expires = "2026-11-21T17:00:00Z", maxUses = 10, uses = 0, code = "k7Qm2x_PaZ9wE4r-")

    @Test fun orgPage() = shot("org-page") { OrgDetailPage(page, sam, {}, { _, _ -> }, {}, {}, {}) }

    @Test @Config(qualifiers = "w412dp-h1500dp-xhdpi")
    fun orgInvite() = shot("org-invite") {
        InvitePage(shop, page.invites.orEmpty(), HubUrl("192.168.1.20", 8000), "Workshop hub", { _, _, _ -> }, {}, busy = false, error = null, onBack = {}, fresh = freshCode)
    }

    // ------------------------------------------------------------ onboarding

    @Test fun welcome1() = shot("onboarding-welcome-1") { WelcomePages({}, 0, settle = true) }
    @Test fun welcome2() = shot("onboarding-welcome-2") { WelcomePages({}, 1, settle = true) }
    @Test fun welcome3() = shot("onboarding-welcome-3") { WelcomePages({}, 2, settle = true) }
    @Test fun welcome4() = shot("onboarding-welcome-4", dark = true) { WelcomePages({}, 3, settle = true) }
    @Test fun onboardingConnect() = shot("onboarding-connect") { ConnectPage("Step 1 of 5", {}, {}) }
    @Test fun onboardingProfile() = shot("onboarding-profile") { ProfileStep("Sam Rivera", null, "Step 3 of 6", {}, {}) }
    @Test fun onboardingRole() = shot("onboarding-role") { RoleStep(HomeFirst.Learn, "Step 4 of 5", {}, {}) }
    @Test fun onboardingTheme() = shot("onboarding-theme") { ThemeStep("Step 5 of 5", {}) }
    @Test fun permissionCamera() = shot("permission-camera") { PermissionCard(PermissionAsk.Camera, blocked = false, {}, {}) }
    @Test fun permissionBlocked() = shot("permission-camera-blocked", dark = true) { PermissionCard(PermissionAsk.Camera, blocked = true, {}, {}) }
}
