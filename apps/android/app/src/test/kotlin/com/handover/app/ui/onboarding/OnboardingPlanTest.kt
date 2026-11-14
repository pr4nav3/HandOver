package com.handover.app.ui.onboarding

import com.handover.app.ui.account.AccountSupport
import com.handover.app.ui.account.AvatarHue
import com.handover.app.ui.settings.MemoryKeyValue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import com.handover.app.ui.onboarding.OnboardingStep as S

class OnboardingPlanTest {
    private val offline = HubFacts(connected = false, accounts = AccountSupport.Unknown, setupNeeded = false, signedIn = false, orgCount = null)
    private val noAccounts = offline.copy(connected = true, accounts = AccountSupport.None)
    private val firstOwner = offline.copy(connected = true, accounts = AccountSupport.Available, setupNeeded = true, orgCount = 0)
    private val existing = offline.copy(connected = true, accounts = AccountSupport.Available, orgCount = 0)

    @Test fun freshInstallStartsWithWelcomeThenConnect() {
        val p = OnboardingProgress()
        assertEquals(S.Welcome, OnboardingPlan.current(p, offline))
        assertEquals(S.Connect, OnboardingPlan.current(p.copy(welcomeSeen = true), offline))
    }

    @Test fun hubWithoutAccountsGoesStraightToRoleAndTheme() {
        val p = OnboardingProgress(welcomeSeen = true)
        assertEquals(listOf(S.Connect, S.Role, S.Theme), OnboardingPlan.steps(p, noAccounts))
        assertEquals(S.Role, OnboardingPlan.current(p, noAccounts))
        assertEquals("Step 2 of 3", OnboardingPlan.label(S.Role, p, noAccounts))
    }

    @Test fun firstOwnerSetsUpThenProfileJoinRoleTheme() {
        val p = OnboardingProgress(welcomeSeen = true)
        assertEquals(listOf(S.Connect, S.OwnerSetup, S.Profile, S.Join, S.Role, S.Theme), OnboardingPlan.steps(p, firstOwner))
        assertEquals(S.OwnerSetup, OnboardingPlan.current(p, firstOwner))
        // After setup the hub reports a signed-in user and no setup needed; the count does not jump.
        val after = firstOwner.copy(setupNeeded = false, signedIn = true, newAccount = true)
        assertEquals(S.Profile, OnboardingPlan.current(p, after))
        assertEquals("Step 3 of 6", OnboardingPlan.label(S.Profile, p, after))
    }

    @Test fun existingAccountsNeedSignInAndNoProfile() {
        val p = OnboardingProgress(welcomeSeen = true)
        assertEquals(listOf(S.Connect, S.SignIn, S.Join, S.Role, S.Theme), OnboardingPlan.steps(p, existing))
        val signedIn = existing.copy(signedIn = true)
        assertEquals(S.Join, OnboardingPlan.current(p, signedIn))
        assertEquals(S.Role, OnboardingPlan.current(p, signedIn.copy(orgCount = 2)))
        assertEquals("orgs hidden on hubs without them", S.Role, OnboardingPlan.current(p, signedIn.copy(orgCount = null)))
    }

    @Test fun skippingOptionalStepsNeverBlocksAndResumeIsTheFirstUnfinished() {
        val signedIn = existing.copy(signedIn = true)
        var p = OnboardingProgress(welcomeSeen = true, joinDone = true)
        assertEquals(S.Role, OnboardingPlan.current(p, signedIn))
        p = p.copy(roleDone = true)
        assertEquals(S.Theme, OnboardingPlan.current(p, signedIn))
        // The hub drops away mid-flow: back to the required Connect step, with optional progress kept.
        assertEquals(S.Connect, OnboardingPlan.current(p, offline))
        assertNull(OnboardingPlan.current(p.copy(finished = true), signedIn))
    }

    @Test fun remindersListOnlySkippedItemsThatStillApply() {
        val signedIn = existing.copy(signedIn = true)
        val p = OnboardingProgress(welcomeSeen = true, finished = true, joinDone = false, themeDone = false)
        assertEquals(listOf("Join an organization", "Pick a look"), OnboardingPlan.reminders(p, signedIn))
        assertTrue(OnboardingPlan.reminders(p.copy(reminderHidden = true), signedIn).isEmpty())
        assertEquals(listOf("Pick a look"), OnboardingPlan.reminders(p, signedIn.copy(orgCount = null)))
    }

    @Test fun progressSurvivesARestart() {
        val kv = MemoryKeyValue()
        OnboardingStore(kv).update { it.copy(welcomeSeen = true, role = HomeFirst.Teach, roleDone = true, avatarHue = AvatarHue.Rust) }
        val back = OnboardingStore(kv).progress.value
        assertTrue(back.welcomeSeen)
        assertEquals(HomeFirst.Teach, back.role)
        assertEquals(AvatarHue.Rust, back.avatarHue)
    }
}
