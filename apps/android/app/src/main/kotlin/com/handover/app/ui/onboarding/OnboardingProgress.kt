package com.handover.app.ui.onboarding

import android.content.Context
import com.handover.app.ui.account.AccountSupport
import com.handover.app.ui.account.AvatarHue
import com.handover.app.ui.settings.KeyValue
import com.handover.app.ui.settings.SharedKeyValue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** The onboarding steps of SCREENS.md 25.1, in order. */
enum class OnboardingStep { Welcome, Connect, OwnerSetup, SignIn, Profile, Join, Role, Theme }

/** What Home shows first (SCREENS.md 25.7). Personalization only; never a permission. */
enum class HomeFirst(val id: String, val title: String) {
    Learn("learn", "I Want to Learn"), Teach("teach", "I Want to Teach"), Both("both", "Both");

    companion object {
        fun from(id: String?): HomeFirst? = entries.firstOrNull { it.id == id }
    }
}

/** What the person has done or skipped, saved after each step (SCREENS.md 25.11). */
data class OnboardingProgress(
    val welcomeSeen: Boolean = false,
    val profileDone: Boolean = false,
    val joinDone: Boolean = false,
    val role: HomeFirst? = null,
    val roleDone: Boolean = false,
    val themeDone: Boolean = false,
    val avatarHue: AvatarHue? = null,
    /** Finished or skipped through to Home. */
    val finished: Boolean = false,
    /** "Finish setting up" card hidden for good. */
    val reminderHidden: Boolean = false,
)

/** The hub facts the flow branches on. */
data class HubFacts(
    val connected: Boolean,
    val accounts: AccountSupport,
    val setupNeeded: Boolean,
    val signedIn: Boolean,
    /** Null when the hub has no organizations. */
    val orgCount: Int?,
    /** True right after this device created an account (owner setup), so the profile step applies. */
    val newAccount: Boolean = false,
)

object OnboardingPlan {
    /**
     * The steps this person will see, in order (25.1). Required steps (Connect, sign in or owner
     * setup) stay in; optional ones drop out once done or skipped. Waiting on an account check keeps
     * the account step as SignIn until the hub answers.
     */
    fun steps(p: OnboardingProgress, hub: HubFacts): List<OnboardingStep> = buildList {
        if (!p.welcomeSeen) add(OnboardingStep.Welcome)
        add(OnboardingStep.Connect)
        if (hub.connected && hub.accounts == AccountSupport.Available) {
            if (hub.setupNeeded) add(OnboardingStep.OwnerSetup) else if (!hub.signedIn || hub.newAccount) add(OnboardingStep.SignIn)
            if (hub.setupNeeded || hub.newAccount) add(OnboardingStep.Profile)
            if (hub.orgCount == 0) add(OnboardingStep.Join)
        }
        add(OnboardingStep.Role)
        add(OnboardingStep.Theme)
    }

    /** Where to resume: the first step not yet done (25.11). Null means go to Home. */
    fun current(p: OnboardingProgress, hub: HubFacts): OnboardingStep? {
        if (p.finished) return null
        return steps(p, hub).firstOrNull { !isDone(it, p, hub) }
    }

    fun isDone(step: OnboardingStep, p: OnboardingProgress, hub: HubFacts): Boolean = when (step) {
        OnboardingStep.Welcome -> p.welcomeSeen
        OnboardingStep.Connect -> hub.connected
        OnboardingStep.OwnerSetup -> !hub.setupNeeded
        OnboardingStep.SignIn -> hub.signedIn || hub.accounts == AccountSupport.None
        OnboardingStep.Profile -> p.profileDone
        OnboardingStep.Join -> p.joinDone || (hub.orgCount ?: 0) > 0
        OnboardingStep.Role -> p.roleDone
        OnboardingStep.Theme -> p.themeDone
    }

    /** "Step 2 of 5" for the steps after the welcome pages, or null on the welcome pages. */
    fun label(step: OnboardingStep, p: OnboardingProgress, hub: HubFacts): String? {
        if (step == OnboardingStep.Welcome) return null
        val after = steps(p.copy(welcomeSeen = true), hub)
        val i = after.indexOf(step)
        return if (i < 0) null else "Step ${i + 1} of ${after.size}"
    }

    /** The skipped optional items Home's "Finish setting up" card lists (25.11). */
    fun reminders(p: OnboardingProgress, hub: HubFacts): List<String> = buildList {
        if (p.reminderHidden || !p.finished) return@buildList
        if (hub.orgCount == 0 && !p.joinDone) add("Join an organization")
        if (!p.themeDone) add("Pick a look")
    }
}

/** Saves [OnboardingProgress] on the device. */
class OnboardingStore(private val kv: KeyValue) {
    private val _progress = MutableStateFlow(load())
    val progress: StateFlow<OnboardingProgress> = _progress.asStateFlow()

    fun update(change: (OnboardingProgress) -> OnboardingProgress) {
        val next = change(_progress.value)
        _progress.value = next
        kv.putBool("welcome", next.welcomeSeen)
        kv.putBool("profile", next.profileDone)
        kv.putBool("join", next.joinDone)
        kv.putString("role", next.role?.id)
        kv.putBool("role_done", next.roleDone)
        kv.putBool("theme", next.themeDone)
        kv.putString("hue", next.avatarHue?.name)
        kv.putBool("finished", next.finished)
        kv.putBool("reminder_hidden", next.reminderHidden)
    }

    private fun load() = OnboardingProgress(
        welcomeSeen = kv.bool("welcome", false),
        profileDone = kv.bool("profile", false),
        joinDone = kv.bool("join", false),
        role = HomeFirst.from(kv.string("role")),
        roleDone = kv.bool("role_done", false),
        themeDone = kv.bool("theme", false),
        avatarHue = AvatarHue.entries.firstOrNull { it.name == kv.string("hue") },
        finished = kv.bool("finished", false),
        reminderHidden = kv.bool("reminder_hidden", false),
    )

    companion object {
        @Volatile private var shared: OnboardingStore? = null

        fun get(context: Context): OnboardingStore =
            shared ?: synchronized(this) { shared ?: OnboardingStore(SharedKeyValue(context, "handover_onboarding")).also { shared = it } }
    }
}
