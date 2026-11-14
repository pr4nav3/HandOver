package com.handover.app.ui.pairing

import com.handover.app.core.HubUrl
import com.handover.app.ui.settings.KeyValue
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** A hub this device connected to before (SCREENS.md 3.4). */
@Serializable
data class RecentHub(
    /** [HubUrl.display], the key. */
    val address: String,
    val name: String? = null,
    val lastConnected: Long = 0,
) {
    val title: String get() = name?.takeIf { it.isNotBlank() } ?: HubUrl.parse(address)?.host ?: address
}

/** Up to five hubs, newest first. Tap connects; Remove forgets the address only. */
class RecentHubs(private val kv: KeyValue) {
    private val _hubs = MutableStateFlow(load())
    val hubs: StateFlow<List<RecentHub>> = _hubs.asStateFlow()

    /** Records a successful connection. A known hub moves to the top and keeps its name unless a new one came. */
    fun remember(target: PairingTarget, now: Long = System.currentTimeMillis()) = set(add(_hubs.value, target, now))

    fun remove(address: String) = set(_hubs.value.filterNot { it.address == address })

    fun nameOf(address: String?): String? = _hubs.value.firstOrNull { it.address == address }?.name

    private fun set(list: List<RecentHub>) {
        _hubs.value = list
        kv.putString(KEY, json.encodeToString(ListSerializer(RecentHub.serializer()), list))
    }

    private fun load(): List<RecentHub> =
        runCatching { json.decodeFromString(ListSerializer(RecentHub.serializer()), kv.string(KEY) ?: "[]") }.getOrDefault(emptyList())

    companion object {
        const val LIMIT = 5
        private const val KEY = "recent_hubs"
        private val json = Json { ignoreUnknownKeys = true }

        fun add(list: List<RecentHub>, target: PairingTarget, now: Long): List<RecentHub> {
            val address = target.hub.display
            val old = list.firstOrNull { it.address == address }
            val entry = RecentHub(address, target.name ?: old?.name, now)
            return (listOf(entry) + list.filterNot { it.address == address }).take(LIMIT)
        }
    }
}
