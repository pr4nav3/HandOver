package com.handover.app.ui.components

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CenterFocusWeak
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Science
import androidx.compose.material.icons.outlined.TouchApp
import androidx.compose.material.icons.outlined.Verified
import androidx.compose.material.icons.outlined.VideocamOff
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.unit.dp
import com.handover.app.core.HubState
import com.handover.app.core.OfflineReason
import com.handover.app.core.StepStatus
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HandOver
import kotlinx.coroutines.delay

/** The badge states of DESIGN.md 3.1, in precedence order (first wins). */
enum class BadgeState(val label: String, val tone: Tone, val icon: ImageVector, val spoken: String) {
    Done("Done", Tone.Good, Icons.Outlined.Verified, "Status: lesson done"),
    Verified("Verified", Tone.Good, Icons.Outlined.CheckCircle, "Status: verified"),
    Manual("Tap Next when done", Tone.Neutral, Icons.Outlined.TouchApp, "Status: manual step. Tap Next when done"),
    ChecksOff("Checks off, use Next", Tone.Caution, Icons.Outlined.WarningAmber, "Status: checks off. Use Next"),
    Simulated("Simulated checks", Tone.Caution, Icons.Outlined.Science, "Status: simulated checks, not real"),
    NoCamera("No camera", Tone.Idle, Icons.Outlined.VideocamOff, "Status: no camera connected"),
    Checking("Checking", Tone.Accent, Icons.Outlined.CenterFocusWeak, "Status: checking"),
    Watching("Watching", Tone.Idle, Icons.Outlined.Visibility, "Status: watching for this step"),
}

object Badge {
    /**
     * The badge for a hub state. Precedence (DESIGN.md 3.1, CONTRACT 5 plus client rules): done,
     * verified (also during the client's 1.8 s flash after a camera advance), manual, checks off,
     * simulated, no camera, checking, watching. [manualStep] is the step's `check_type == manual`.
     * Simulated shows only when the hub says `check_mode == "mock"`; it is never guessed.
     */
    fun state(s: HubState?, manualStep: Boolean, verifiedFlash: Boolean = false): BadgeState {
        if (s == null || s.lessonId == null) return BadgeState.Watching
        return when {
            s.status == StepStatus.Done -> BadgeState.Done
            s.status == StepStatus.Verified || verifiedFlash -> BadgeState.Verified
            s.status == StepStatus.Manual || manualStep -> BadgeState.Manual
            s.checkOffline -> BadgeState.ChecksOff
            s.checkMode == "mock" -> BadgeState.Simulated
            !s.cameraConnected -> BadgeState.NoCamera
            s.status == StepStatus.Checking -> BadgeState.Checking
            else -> BadgeState.Watching
        }
    }

    /** The meta line under the badge (SCREENS.md 7.8), or null. */
    fun meta(badge: BadgeState, s: HubState?): String? = when (badge) {
        BadgeState.Watching, BadgeState.Checking -> s?.lastCheck?.takeIf { s.cameraConnected && it.latencyMs > 0 }?.let { "Last check ${Format.latency(it.latencyMs)}" }
        BadgeState.ChecksOff -> offlineMeta(s?.checkOfflineReason)
        BadgeState.Simulated -> "Test mode. Steps pass on a timer."
        BadgeState.NoCamera -> "Connect a camera to check steps."
        else -> null
    }

    /** The check reason line: only when the last answer was no at confidence 0.7 or more (CONTRACT 7). */
    fun reason(badge: BadgeState, s: HubState?): String? {
        if (badge != BadgeState.Watching && badge != BadgeState.Checking) return null
        val lc = s?.lastCheck ?: return null
        return lc.reasonToShow?.takeIf { lc.done == com.handover.app.core.Answer.No }
    }

    /**
     * Copy per `check_offline_reason` (SCREENS.md 7.8 and 18). Matched by wire name so a reason core adds
     * later (the hub's `budget`) gets its copy without this file changing, and unknown ones the generic line.
     */
    fun offlineMeta(reason: OfflineReason?): String = when (wire(reason)) {
        "no_key" -> "No check key on the hub."
        "rate_limited" -> "Too many checks. Trying again soon."
        "errors" -> "Checks failed. Trying again soon."
        "budget" -> "Check spending limit reached."
        else -> "Checks are off. Use Next to move on."
    }

    /** The reason as the hub spells it ("no_key"), from the serializer, so release shrinking cannot rename it. */
    private fun wire(reason: OfflineReason?): String? = reason?.let { OfflineReason.serializer().descriptor.getElementName(it.ordinal) }

    /** Short words for the "Checks off: <reason>" pill. */
    fun offlinePill(reason: OfflineReason?): String = when (wire(reason)) {
        "no_key" -> "Checks off: no key"
        "rate_limited" -> "Checks off: rate limited"
        "errors" -> "Checks off: errors"
        "budget" -> "Checks off: spending limit"
        else -> "Checks off"
    }
}

/**
 * The status badge: a capsule with a still dot and the label, on its tone's wash. At large font
 * scales the symbol replaces the dot. [onVideo] draws it as a glass capsule with white text.
 * Checking, once shown, holds at least 0.6 s so it never flickers.
 */
@Composable
fun StatusBadge(state: BadgeState, modifier: Modifier = Modifier, onVideo: Boolean = false) {
    var shown by remember { mutableStateOf(state) }
    var shownAt by remember { mutableLongStateOf(0L) }
    LaunchedEffect(state) {
        if (shown == BadgeState.Checking && state != BadgeState.Checking) {
            val wait = 600 - (System.currentTimeMillis() - shownAt)
            if (wait > 0) delay(wait)
        }
        shown = state
        shownAt = System.currentTimeMillis()
    }
    val reduce = HandOver.reduceMotion
    AnimatedContent(
        targetState = shown,
        transitionSpec = { fadeIn(HOMotion.snappy(reduce)) togetherWith fadeOut(HOMotion.snappy(reduce)) },
        label = "badge",
        modifier = modifier.clearAndSetSemantics {
            contentDescription = shown.spoken
            liveRegion = LiveRegionMode.Polite
        },
    ) { s -> BadgeBody(s, onVideo) }
}

@Composable
private fun BadgeBody(s: BadgeState, onVideo: Boolean) {
    val large = LocalDensity.current.fontScale >= 1.5f
    val text = if (onVideo) Color.White else toneText(s.tone)
    val dot = toneColor(s.tone)
    val base = Modifier.heightIn(min = HOSize.badge)
    Row(
        (if (onVideo) base.glass() else base.background(toneWash(s.tone), CircleShape)).padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (large) Icon(s.icon, null, tint = if (onVideo) dot else text, modifier = Modifier.size(14.dp))
        else StatusDot(dot, size = HOSize.dot)
        Spacer(Modifier.width(6.dp))
        Text(s.label, style = HandOver.type.badge, color = text, maxLines = 1)
    }
}

/** The badge with its meta line and, when allowed, the check reason under it. */
@Composable
fun StatusBlock(state: BadgeState, meta: String?, reason: String?, modifier: Modifier = Modifier) {
    Column(modifier) {
        StatusBadge(state)
        if (meta != null) Text(meta, style = HandOver.type.footnote, color = HandOver.colors.ink2, maxLines = 2, modifier = Modifier.padding(top = 4.dp, start = 2.dp))
        if (reason != null) Text(reason, style = HandOver.type.footnote, color = HandOver.colors.ink2, maxLines = 2, modifier = Modifier.padding(top = 2.dp, start = 2.dp))
    }
}
