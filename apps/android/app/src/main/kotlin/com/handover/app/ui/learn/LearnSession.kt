package com.handover.app.ui.learn

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.handover.app.core.AdvanceReason
import com.handover.app.core.AppViewModel
import com.handover.app.core.HubMessage
import com.handover.app.core.MistakeKind
import com.handover.app.ui.components.Format
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.StepResultCopy
import com.handover.app.ui.components.StepResultMoment
import com.handover.app.ui.done.Completion
import com.handover.app.ui.done.RunData
import com.handover.app.ui.done.RunRecorder
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** A one-shot moment the screen turns into sound or touch. */
sealed interface LearnEffect {
    data object Chime : LearnEffect
    data class Haptic(val event: HOHaptic) : LearnEffect
    /** A line for spoken guidance; the screen applies the setting and verbosity. */
    data class Speak(val text: String, val kind: SpeechKind) : LearnEffect
}

/**
 * Learn's own state across tabs and rotations: the run record (for Done), the verified flash,
 * the step result moment, and practice runs. Activity scoped, attached once to [AppViewModel],
 * so it keeps recording even when the Learn tab is not on screen.
 */
class LearnSession(private val now: () -> Long = System::currentTimeMillis) : ViewModel() {
    private val recorder = RunRecorder(now)
    private var attached: AppViewModel? = null
    private var flashJob: Job? = null

    private val _run = MutableStateFlow(RunData())
    val run: StateFlow<RunData> = _run.asStateFlow()

    private val _flash = MutableStateFlow(false)
    /** The client's 1.8 s Verified hold after a camera advance (web/src/Learn.tsx). */
    val verifiedFlash: StateFlow<Boolean> = _flash.asStateFlow()

    private val _moment = MutableStateFlow<StepResultMoment?>(null)
    val moment: StateFlow<StepResultMoment?> = _moment.asStateFlow()

    private val _practice = MutableStateFlow<Int?>(null)
    /** The step being practiced from Done, or null. */
    val practice: StateFlow<Int?> = _practice.asStateFlow()

    private val _showDone = MutableStateFlow(false)
    /** Done stays up after a practice step, until Start Over or another practice. */
    val showDone: StateFlow<Boolean> = _showDone.asStateFlow()

    private val _toast = MutableStateFlow<String?>(null)
    val toast: StateFlow<String?> = _toast.asStateFlow()

    private val _effects = MutableSharedFlow<LearnEffect>(extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val effects: SharedFlow<LearnEffect> = _effects.asSharedFlow()

    /** Step results on (Settings, Learn, Step Results). */
    var stepResults = true

    fun attach(vm: AppViewModel) {
        if (attached === vm) return
        attached = vm
        viewModelScope.launch {
            vm.state.collect { s ->
                recorder.onState(s.session.takeIf { s.connected })
                if (s.session?.done == true) _practice.value = null
                publish()
            }
        }
        viewModelScope.launch {
            vm.events.collect { m ->
                when (m) {
                    is HubMessage.Advanced -> onAdvance(m)
                    is HubMessage.MistakeRaised -> {
                        recorder.onMistake(m.mistake)
                        _effects.tryEmit(LearnEffect.Speak(com.handover.app.ui.components.MistakeCopy.message(m.mistake), SpeechKind.Mistake))
                        if (m.mistake.kind == MistakeKind.Behind || m.mistake.kind == MistakeKind.Ahead) _effects.tryEmit(LearnEffect.Haptic(HOHaptic.Warning))
                        publish()
                    }
                    else -> Unit
                }
            }
        }
    }

    private fun onAdvance(m: HubMessage.Advanced) {
        val a = m.advance
        val camera = a.reason == AdvanceReason.Camera
        val forward = recorder.onAdvance(a)
        if (camera) {
            _effects.tryEmit(LearnEffect.Chime)
            _effects.tryEmit(LearnEffect.Haptic(HOHaptic.Success))
            flashJob?.cancel()
            _flash.value = true
            flashJob = viewModelScope.launch { delay(1_800); _flash.value = false }
        } else {
            _effects.tryEmit(LearnEffect.Haptic(HOHaptic.StepChange))
        }
        val expert = attached?.state?.value?.lesson?.steps?.getOrNull(a.from)?.let { com.handover.app.ui.done.RunScore.expertSeconds(it.start, it.end) }
        if (forward != null && stepResults) {
            val moment = StepResultCopy.moment(forward.seconds, expert, forward.byCamera, forward.mistakesFixed)
            _moment.value = moment
            _effects.tryEmit(LearnEffect.Speak(moment.text, SpeechKind.Result))
        }
        val total = attached?.state?.value?.session?.total ?: 0
        if (total > 0 && a.to >= total && a.from < total) _effects.tryEmit(LearnEffect.Speak("Lesson complete", SpeechKind.Complete))
        val practiced = _practice.value
        if (practiced != null && a.from == practiced && a.to > a.from) {
            val step = recorder.data.steps.getOrNull(practiced)
            val how = when (step?.completion) {
                Completion.Camera -> "checked by camera"
                Completion.Hand -> "marked done"
                Completion.Skipped -> "skipped"
                null -> "done"
            }
            val time = step?.takeIf { it.ms >= 1_000 && !it.interrupted }?.let { Format.secs(it.ms / 1000.0) } ?: "no time"
            _toast.value = "Step ${practiced + 1}: $time, $how."
            _practice.value = null
            _showDone.value = true
        }
        publish()
    }

    fun clearMoment() { _moment.value = null }
    fun clearToast() { _toast.value = null }

    /** Practice one step from Done: its old record is cleared and Learn returns to Done when it is finished. */
    fun practice(step: Int) {
        val vm = attached ?: return
        recorder.resetStep(step)
        recorder.willGoto(step)
        _practice.value = step
        _showDone.value = false
        vm.goto(step)
        publish()
    }

    fun startOver() {
        val vm = attached ?: return
        _practice.value = null
        _showDone.value = false
        recorder.restart()
        vm.goto(0)
        publish()
    }

    /** This device sends goto: a forward jump marks the step left as skipped. */
    fun goto(step: Int) {
        val vm = attached ?: return
        recorder.willGoto(step)
        vm.goto(step)
    }

    private fun publish() { _run.value = recorder.data }
}
