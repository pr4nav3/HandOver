package com.handover.app.ui.pairing

import com.handover.app.core.HubUrl
import com.handover.app.ui.settings.MemoryKeyValue
import org.junit.Assert.assertEquals
import org.junit.Test

class RecentHubsTest {
    private fun target(i: Int, name: String? = null) = PairingTarget(HubUrl("10.0.0.$i", 8000), name)

    @Test fun newestFirstDedupedAndCappedAtFive() {
        val store = RecentHubs(MemoryKeyValue())
        (1..6).forEach { store.remember(target(it), now = it.toLong()) }
        store.remember(target(3), now = 100)
        val addresses = store.hubs.value.map { it.address }
        assertEquals(listOf("10.0.0.3:8000", "10.0.0.6:8000", "10.0.0.5:8000", "10.0.0.4:8000", "10.0.0.2:8000"), addresses)
        assertEquals(100L, store.hubs.value.first().lastConnected)
    }

    @Test fun keepsNameWhenReconnectedByAddress() {
        val store = RecentHubs(MemoryKeyValue())
        store.remember(target(1, "Shop"), now = 1)
        store.remember(target(1), now = 2)
        assertEquals("Shop", store.hubs.value.single().title)
        assertEquals("Shop", store.nameOf("10.0.0.1:8000"))
    }

    @Test fun persistsAndRemoves() {
        val kv = MemoryKeyValue()
        RecentHubs(kv).apply { remember(target(1, "A"), 1); remember(target(2), 2) }
        val reopened = RecentHubs(kv)
        assertEquals(2, reopened.hubs.value.size)
        reopened.remove("10.0.0.1:8000")
        assertEquals(listOf("10.0.0.2"), RecentHubs(kv).hubs.value.map { it.title })
    }

    @Test fun corruptStoreStartsEmpty() {
        val kv = MemoryKeyValue().apply { putString("recent_hubs", "{not json") }
        assertEquals(emptyList<RecentHub>(), RecentHubs(kv).hubs.value)
    }
}
