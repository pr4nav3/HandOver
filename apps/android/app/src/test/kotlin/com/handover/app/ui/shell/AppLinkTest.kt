package com.handover.app.ui.shell

import com.handover.app.core.Capabilities
import com.handover.app.core.HubUrl
import com.handover.app.core.HubUser
import com.handover.app.core.Org
import com.handover.app.ui.account.AccountState
import com.handover.app.ui.account.AccountSupport
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppLinkTest {
    @Test fun hubLinksConnectWithTheirName() {
        val link = AppLink.route("handover://connect?host=192.168.1.20&port=8001&name=Workshop") as AppLink.Connect
        assertEquals(HubUrl("192.168.1.20", 8001), link.target.hub)
        assertEquals("Workshop", link.target.name)
        assertEquals(HubUrl("192.168.1.20", 8000), (AppLink.route("handover://192.168.1.20:8000") as AppLink.Connect).target.hub)
        assertEquals(HubUrl("mac.local", 8000), (AppLink.route("handover://mac.local") as AppLink.Connect).target.hub)
    }

    @Test fun joinLinksOpenJoinNeverConnect() {
        val local = AppLink.route("handover://join?code=k7Qm2x_PaZ9wE4r-") as AppLink.Join
        assertEquals("k7Qm2x_PaZ9wE4r-", local.code)
        assertNull(local.target)
        val remote = AppLink.route("handover://join?code=k7Qm2x_PaZ9wE4r-&host=192.168.1.30&port=8001&name=Shop") as AppLink.Join
        assertEquals(HubUrl("192.168.1.30", 8001), remote.target?.hub)
        assertEquals("Shop", remote.target?.name)
    }

    @Test fun metaAiReturnGoesToTheGlassesNotToConnect() {
        assertEquals(AppLink.Glasses, AppLink.route("handover://"))
        assertEquals(AppLink.Glasses, AppLink.route("handover://?metaWearablesAction=register&status=ok"))
        assertEquals(AppLink.Glasses, AppLink.route("handover://mwdat/registration?result=1"))
        assertEquals(AppLink.Glasses, AppLink.route("handover://connect"))
        assertNull(AppLink.route("https://192.168.1.20:8000"))
    }

    @Test fun tabsFollowWhatThePersonMayDo() {
        val open = AccountState(support = AccountSupport.None)
        assertEquals(listOf(Destination.Home, Destination.Learn, Destination.Teach, Destination.Settings), ShellTabs.visible(open))
        val learner = AccountState(support = AccountSupport.Available, user = HubUser("u2", "Lee", "learner"), capabilities = Capabilities.derive(HubUser("u2", "Lee", "learner")), orgs = emptyList())
        assertFalse(ShellTabs.canTeach(learner))
        assertTrue(Destination.Organizations in ShellTabs.visible(learner))
        assertTrue(ShellTabs.canTeach(learner.copy(orgs = listOf(Org("o1", "Shop", role = "teacher")))))
        assertTrue(ShellTabs.canTeach(learner.copy(user = HubUser("u1", "Sam", "owner"))))
        assertTrue("signed out on an open hub can make a legacy lesson", ShellTabs.canTeach(AccountState(support = AccountSupport.Available)))
        assertFalse(ShellTabs.canTeach(AccountState(support = AccountSupport.Available, authRequired = true)))
        assertTrue("a join link shows Organizations", Destination.Organizations in ShellTabs.visible(open, forceOrgs = true))
    }
}
