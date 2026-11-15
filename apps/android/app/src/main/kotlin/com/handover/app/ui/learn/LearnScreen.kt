package com.handover.app.ui.learn

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.core.CameraSocket
import com.handover.app.core.CheckType
import com.handover.app.core.HubState
import com.handover.app.core.MistakeKind
import com.handover.app.core.Nav
import android.graphics.BitmapFactory
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material.icons.outlined.VideocamOff
import com.handover.app.ui.camera.FrameSender
import com.handover.app.ui.components.Badge
import com.handover.app.ui.components.Banner
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.components.Tone
import com.handover.app.ui.glasses.EyeglassesIcon
import com.handover.app.ui.glasses.GlassesEvent
import com.handover.app.ui.glasses.GlassesLink
import com.handover.app.ui.glasses.GlassesPhase
import com.handover.app.ui.glasses.glassesCopy
import com.handover.app.ui.glasses.rememberGlassesLink
import com.handover.app.ui.start.CameraChoice
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.ClipPlayer
import com.handover.app.ui.components.ClipSource
import com.handover.app.ui.components.Corner
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.LiveSource
import com.handover.app.ui.components.LiveState
import com.handover.app.ui.components.LiveView
import com.handover.app.ui.components.PhoneCameraPreview
import com.handover.app.ui.components.Progress
import com.handover.app.ui.components.StepResultMoment
import com.handover.app.ui.components.Toast
import com.handover.app.ui.components.isPhoneSilent
import com.handover.app.ui.components.rememberClipDeck
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.done.DoneApi
import com.handover.app.ui.done.DoneScreen
import com.handover.app.ui.done.RatingPrompts
import com.handover.app.ui.done.RatingSheet
import com.handover.app.ui.done.RunScore
import com.handover.app.ui.done.ScoreFetch
import com.handover.app.ui.done.withHub
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** The pure mapping from app state to what Learn draws. Tested on the JVM. */
object LearnModel {
    fun ui(
        state: AppState,
        verifiedFlash: Boolean,
        moment: StepResultMoment?,
        prefs: LearnPrefs,
        usingThisPhone: Boolean,
        caption: String? = null,
    ): LearnUi {
        val s = state.session
        val lesson = state.lesson
        val hasLesson = s?.lessonId != null && lesson != null && lesson.steps.isNotEmpty()
        if (!hasLesson) return LearnUi(hasLesson = false, loading = s?.lessonId != null && state.connected, reconnecting = !state.connected)
        val step = lesson.steps.getOrNull(s.step)
        val manual = step?.checkType == CheckType.Manual
        val badge = Badge.state(s, manual, verifiedFlash)
        val mistake = s.mistake?.takeIf { it.step == s.step } ?: state.lastMistake?.takeIf { it.step == s.step || it.kind == MistakeKind.Ahead }
        val connected = state.connected
        return LearnUi(
            hasLesson = true,
            lessonTitle = lesson.title,
            stepIndex = s.step,
            total = s.total,
            stepTitle = step?.title.orEmpty(),
            segments = Progress.segments(s.total, s.position, mistake?.kind == MistakeKind.Behind),
            badge = badge,
            meta = Badge.meta(badge, s),
            reason = Badge.reason(badge, s),
            mistake = mistake,
            mockChecks = s.checkMode == "mock",
            checksOffPill = if (s.checkOffline) Badge.offlinePill(s.checkOfflineReason) else null,
            canBack = connected && Nav.back(s) != null,
            canNext = connected && Nav.next(s) != null,
            isLastStep = s.step == s.total - 1,
            reconnecting = !connected,
            moment = moment,
            swapped = prefs.swapped,
            corner = prefs.corner,
            captionsOn = prefs.captions,
            muted = prefs.muted,
            usingThisPhone = usingThisPhone,
            caption = caption,
        )
    }

    /** The live pane state: placeholder while reconnecting, the last frame dimmed when the camera is lost. */
    fun liveState(connected: Boolean, s: HubState?, hadCamera: Boolean, thisPhone: Boolean): LiveState = when {
        !connected -> LiveState.Reconnecting
        thisPhone -> LiveState.Live
        s?.cameraConnected == true -> LiveState.Live
        hadCamera -> LiveState.Lost
        else -> LiveState.Waiting
    }
}

/** Per device: which video is large, the tile's corner, captions and mute. */
class LearnPrefs(val swapped: Boolean = false, val corner: Corner = Corner.BottomRight, val captions: Boolean = true, val muted: Boolean = false) {
    fun copy(swapped: Boolean = this.swapped, corner: Corner = this.corner, captions: Boolean = this.captions, muted: Boolean = this.muted) = LearnPrefs(swapped, corner, captions, muted)

    fun save(context: Context) = context.getSharedPreferences("handover", Context.MODE_PRIVATE).edit {
        putBoolean("learn_swapped", swapped); putString("learn_corner", corner.name); putBoolean("learn_captions", captions)
    }

    companion object {
        fun load(context: Context, silent: Boolean): LearnPrefs {
            val p = context.getSharedPreferences("handover", Context.MODE_PRIVATE)
            return LearnPrefs(
                swapped = p.getBoolean("learn_swapped", false),
                corner = runCatching { Corner.valueOf(p.getString("learn_corner", null) ?: "") }.getOrDefault(Corner.BottomRight),
                captions = p.getBoolean("learn_captions", true),
                // Muted by default only when the phone is on silent (DESIGN.md 3.4); not remembered.
                muted = silent,
            )
        }
    }
}

/**
 * Learn. [camera] is how HandOver sees the hands: This phone streams the back camera while the clip
 * plays, Meta glasses stream through the Meta toolkit, Another device leaves the hub to that device.
 * [onEnd] runs after the End confirmation (and from Done's Back to Home).
 */
@Composable
fun LearnScreen(
    appState: AppState,
    vm: AppViewModel,
    modifier: Modifier = Modifier,
    camera: CameraChoice? = null,
    onEnd: () -> Unit = {},
    onPickLesson: () -> Unit = {},
    onChangeCamera: () -> Unit = {},
) {
    // A run ended on this phone reads as no lesson until a new one starts.
    val state = if (appState.lessonRunning) appState else appState.copy(session = null, lesson = null)
    val context = LocalContext.current
    val session: LearnSession = viewModel()
    LaunchedEffect(vm) { session.attach(vm) }
    val haptics = rememberHaptics()
    val speaker = rememberSpeaker()
    val speechPrefs = remember { SpeechPrefs(context) }
    var speechChoice by remember { mutableStateOf(speechPrefs.spokenGuidance) }
    var verbosity by remember { mutableStateOf(speechPrefs.verbosity) }
    val bluetooth = speaker?.bluetoothName
    val speak = SpeechPrefs.effective(speechChoice, bluetooth != null)
    val speakNow = androidx.compose.runtime.rememberUpdatedState(speak to verbosity)
    fun say(text: String, kind: SpeechKind) {
        val (on, v) = speakNow.value
        if (on && v.allows(kind)) speaker?.say(text, kind)
    }
    LaunchedEffect(session) {
        session.effects.collect { e ->
            when (e) {
                LearnEffect.Chime -> Chime.play()
                is LearnEffect.Haptic -> haptics.play(e.event)
                is LearnEffect.Speak -> say(if (e.kind == SpeechKind.Result && speakNow.value.second != Verbosity.Detailed) "Nice" else e.text, e.kind)
            }
        }
    }
    LaunchedEffect(speak) { if (!speak) speaker?.stop() }
    // The step title when a step starts.
    val titleStep = state.session?.takeIf { !it.done && it.lessonId != null }?.step
    val titleText = titleStep?.let { state.lesson?.steps?.getOrNull(it)?.title }
    LaunchedEffect(state.session?.lessonId, titleStep, titleText) {
        if (titleStep != null && !titleText.isNullOrBlank()) {
            say(if (verbosity == Verbosity.Detailed) "Step ${titleStep + 1}. $titleText" else titleText, SpeechKind.StepTitle)
        }
    }
    val view = LocalView.current
    DisposableEffect(view) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }

    val flash by session.verifiedFlash.collectAsStateWithLifecycle()
    val moment by session.moment.collectAsStateWithLifecycle()
    val run by session.run.collectAsStateWithLifecycle()
    val showDone by session.showDone.collectAsStateWithLifecycle()
    val toast by session.toast.collectAsStateWithLifecycle()
    val frame by vm.frame.collectAsStateWithLifecycle()
    var prefs by remember { mutableStateOf(LearnPrefs.load(context, isPhoneSilent(context))) }
    fun update(p: LearnPrefs) { prefs = p; p.save(context) }

    val hasLesson = state.session?.lessonId != null && state.lesson != null
    // Glasses that fail fall back to this phone for the rest of this lesson (the saved choice stays).
    var fellBack by remember(state.session?.lessonId) { mutableStateOf(false) }
    val mode = if (camera == CameraChoice.Glasses && fellBack) CameraChoice.ThisPhone else camera

    // This phone as the camera: its own preview at full rate plus frames on core's camera socket.
    var phoneAllowed by remember { mutableStateOf(context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    var phoneAsked by rememberSaveable { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> phoneAllowed = granted; phoneAsked = true }
    LaunchedEffect(mode, hasLesson) {
        if (mode == CameraChoice.ThisPhone && hasLesson && !phoneAllowed && !phoneAsked) permission.launch(Manifest.permission.CAMERA)
    }
    val usePhone = mode == CameraChoice.ThisPhone && hasLesson && phoneAllowed
    val useGlasses = mode == CameraChoice.Glasses && hasLesson
    var socket by remember { mutableStateOf<CameraSocket?>(null) }
    DisposableEffect(usePhone, useGlasses) {
        if (usePhone || useGlasses) socket = vm.startCamera()
        onDispose {
            if (usePhone || useGlasses) {
                vm.stopCamera()
                socket = null
            }
        }
    }
    // Frames go out about 15 a second; a busy socket drops the frame before it is encoded.
    val sender = remember { FrameSender(busy = { socket?.isBusy() ?: true }, send = { socket?.sendFrame(it) == true }) }
    var glassesFrame by remember { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    val glasses = if (useGlasses) rememberGlassesLink(offer = { _, jpeg ->
        var bytes: ByteArray? = null
        sender.offer { jpeg().also { bytes = it } }.also { sent ->
            bytes?.takeIf { sent }?.let { b -> glassesFrame = BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }
        }
    }) else null
    LaunchedEffect(glasses?.controller) {
        glasses?.controller?.events?.collect { e ->
            if (e is GlassesEvent.FallBack) { session.showToast(e.reason); fellBack = true }
        }
    }
    LaunchedEffect(socket, useGlasses, glasses?.state?.device?.name) {
        socket?.identify(
            name = if (useGlasses) "${glasses?.state?.device?.name ?: "Ray-Ban Meta"} glasses" else AppViewModel.defaultCameraName(),
            source = if (useGlasses) "glasses" else "phone",
        )
    }
    val glassesLive = glasses?.state?.phase == GlassesPhase.Streaming

    var hadCamera by remember(state.session?.lessonId) { mutableStateOf(false) }
    LaunchedEffect(state.session?.cameraConnected) { if (state.session?.cameraConnected == true) hadCamera = true }

    val deck = rememberClipDeck()
    val s = state.session
    val lesson = state.lesson

    // Done: when the hub says done, or after a practice step; frozen at the moment of finishing.
    if (lesson != null && s?.lessonId != null && (s.done || showDone)) {
        var model by remember(run.lessonId, run.finished, run.steps) { mutableStateOf(RunScore.model(lesson, run)) }
        // The hub's score for this run, feature-detected: only a hub that sends run_id in state has one, and a
        // hub without the score route keeps the local numbers. Keyed on the run so a new select fetches again.
        val runId = s.runId
        LaunchedEffect(model.steps, runId) {
            val hub = state.hub
            if (runId != null && hub != null) {
                when (val r = DoneApi.runScore(hub, runId)) {
                    is ScoreFetch.Found -> model = model.withHub(r.score)
                    else -> Unit
                }
            }
        }
        var askRating by remember(lesson.id) { mutableStateOf(false) }
        val prompts = remember { RatingPrompts(context) }
        LaunchedEffect(lesson.id) {
            if (!prompts.asked(lesson.id)) { delay(2_000); askRating = true; prompts.markAsked(lesson.id) }
        }
        var doneToast by remember { mutableStateOf<String?>(null) }
        val scope = androidx.compose.runtime.rememberCoroutineScope()
        Box(modifier.fillMaxSize()) {
            DoneScreen(model, state.connected, session::practice, session::startOver, session::practice, onFinish = onEnd)
            val t = toast ?: doneToast
            if (t != null) {
                LaunchedEffect(t) { delay(4_000); session.clearToast(); doneToast = null }
                Toast(t, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(16.dp))
            }
        }
        if (askRating) {
            RatingSheet(
                onSend = { stars, comment ->
                    askRating = false
                    val hub = state.hub ?: return@RatingSheet
                    scope.launch {
                        val error = DoneApi.rate(hub, lesson.id, stars, comment)
                        doneToast = error ?: "Thanks. Rating sent."
                        if (error == null) haptics.play(com.handover.app.ui.components.HOHaptic.Success)
                    }
                },
                onNotNow = { askRating = false },
            )
        }
        return
    }

    val ui = LearnModel.ui(state, flash, moment, prefs, usePhone, deck?.caption).copy(
        audioRoute = bluetooth, speaking = speaker?.speaking == true, spokenGuidance = speak, verbosity = verbosity,
        camera = camera, hasHub = appState.hub != null,
    )
    val step = state.currentStep
    val clipSource = step?.clip?.let { path -> vm.lessonFile(path)?.let { ClipSource(it, step.captions?.let(vm::lessonFile)) } }
    val nextSource = s?.nextClip?.let { path ->
        val nextStep = lesson?.steps?.getOrNull((s.step) + 1)
        vm.lessonFile(path)?.let { ClipSource(it, nextStep?.captions?.let(vm::lessonFile)) }
    }
    val liveState = LearnModel.liveState(state.connected, s, hadCamera, usePhone || glassesLive)
    val liveSource = if (glassesLive) LiveSource(glasses?.state?.device?.name ?: "Glasses", EyeglassesIcon) else LiveSource.of(s?.camera, usePhone)
    val image = remember(frame) { frame?.asImageBitmap() }

    val actions = object : LearnActions {
        override fun next() = vm.next()
        override fun back() = vm.back()
        override fun dismissMistake() = vm.dismissMistake()
        override fun showStep(index: Int) = session.goto(index)
        override fun swap() = update(prefs.copy(swapped = !prefs.swapped))
        override fun corner(c: Corner) = update(prefs.copy(corner = c))
        override fun toggleCaptions() = update(prefs.copy(captions = !prefs.captions))
        override fun toggleMute() { prefs = prefs.copy(muted = !prefs.muted) }
        override fun restart() = session.startOver()
        override fun useThisPhone(on: Boolean) = if (on) onChangeCamera() else Unit
        override fun end() = onEnd()
        override fun pickLesson() = onPickLesson()
        override fun changeCamera() = onChangeCamera()
        override fun momentGone() = session.clearMoment()
        override fun spokenGuidance(on: Boolean) { speechChoice = on; speechPrefs.spokenGuidance = on }
        override fun verbosity(v: Verbosity) { verbosity = v; speechPrefs.verbosity = v }
    }

    Box(modifier.fillMaxSize()) {
    LearnContent(
        ui, actions,
        clip = { m, compact, inPane ->
            ClipPlayer(
                deck, clipSource, nextSource, (s?.step ?: 0) + 1, m,
                muted = prefs.muted, ducked = speaker?.speaking == true, captionsOn = prefs.captions, captionsInPane = inPane, compact = compact,
                onToggleMute = actions::toggleMute, onToggleCaptions = actions::toggleCaptions,
            )
        },
        live = { m, compact ->
            LiveView(
                if (glassesLive) glassesFrame else image, liveState, liveSource, m, compact = compact,
                preview = if (usePhone) { pm -> PhoneCameraPreview({ encode -> sender.offer(encode) }, pm) } else null,
                waitingAction = { HOButton("Change Camera", onChangeCamera, kind = ButtonKind.Glass, size = ButtonSize.Small) },
            )
        },
        notice = cameraNotice(mode, hasLesson, phoneAllowed, glasses, onAllow = { permission.launch(Manifest.permission.CAMERA) }, onChangeCamera),
    )
    toast?.let { t ->
        LaunchedEffect(t) { delay(4_000); session.clearToast() }
        Toast(t, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(16.dp))
    }
    }
}

/** One line above the videos when the chosen camera needs something: a choice, the permission, or glasses setup. */
private fun cameraNotice(
    mode: CameraChoice?,
    hasLesson: Boolean,
    phoneAllowed: Boolean,
    glasses: GlassesLink?,
    onAllow: () -> Unit,
    onChangeCamera: () -> Unit,
): (@Composable () -> Unit)? = when {
    !hasLesson -> null
    mode == null -> {
        { Banner("Choose how HandOver sees your hands.", Icons.Outlined.Videocam, Tone.Accent) { QuietButton("Choose", onChangeCamera) } }
    }
    mode == CameraChoice.ThisPhone && !phoneAllowed -> {
        { Banner("Camera is off, so steps are not checked.", Icons.Outlined.VideocamOff, Tone.Caution) { QuietButton("Allow", onAllow) } }
    }
    mode == CameraChoice.Glasses && glasses != null && glasses.state.phase != GlassesPhase.Streaming -> {
        {
            val copy = glassesCopy(glasses.state)
            Banner(copy.line ?: copy.title, EyeglassesIcon, Tone.Caution) {
                if (copy.primary != null && !copy.busy) QuietButton(copy.primary, glasses.next) else QuietButton("Change", onChangeCamera)
            }
        }
    }
    else -> null
}
