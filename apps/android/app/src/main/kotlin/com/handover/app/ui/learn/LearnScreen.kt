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
import com.handover.app.ui.components.Badge
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

@Composable
fun LearnScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
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

    // This phone as the camera: its own preview plus frames on core's camera socket.
    var usePhone by rememberSaveable { mutableStateOf(false) }
    var camera by remember { mutableStateOf<CameraSocket?>(null) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) usePhone = true }
    DisposableEffect(usePhone) {
        if (usePhone) camera = vm.startCamera()
        onDispose {
            if (usePhone) {
                vm.stopCamera()
                camera = null
            }
        }
    }
    fun wantPhone(on: Boolean) {
        if (!on) { usePhone = false; return }
        if (context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) usePhone = true
        else permission.launch(Manifest.permission.CAMERA)
    }

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
            DoneScreen(model, state.connected, session::practice, session::startOver, session::practice)
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
    )
    val step = state.currentStep
    val clipSource = step?.clip?.let { path -> vm.lessonFile(path)?.let { ClipSource(it, step.captions?.let(vm::lessonFile)) } }
    val nextSource = s?.nextClip?.let { path ->
        val nextStep = lesson?.steps?.getOrNull((s.step) + 1)
        vm.lessonFile(path)?.let { ClipSource(it, nextStep?.captions?.let(vm::lessonFile)) }
    }
    val liveState = LearnModel.liveState(state.connected, s, hadCamera, usePhone)
    val liveSource = LiveSource.of(s?.camera, usePhone)
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
        override fun useThisPhone(on: Boolean) = wantPhone(on)
        override fun momentGone() = session.clearMoment()
        override fun spokenGuidance(on: Boolean) { speechChoice = on; speechPrefs.spokenGuidance = on }
        override fun verbosity(v: Verbosity) { verbosity = v; speechPrefs.verbosity = v }
    }

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
                image, liveState, liveSource, m, compact = compact,
                preview = if (usePhone) { pm -> PhoneCameraPreview({ jpeg -> camera?.sendFrame(jpeg) }, pm) } else null,
                waitingAction = { HOButton("Use This Phone", { wantPhone(true) }, kind = ButtonKind.Glass, size = ButtonSize.Small) },
            )
        },
        modifier = modifier,
    )
}
