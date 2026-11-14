package com.handover.app.ui.settings

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit

/**
 * A tiny key value store. Settings, recent hubs and account tokens are kept through it, so their
 * logic runs in a plain JVM test with [MemoryKeyValue] and on the phone with [SharedKeyValue].
 */
interface KeyValue {
    fun string(key: String): String?
    fun putString(key: String, value: String?)
    fun bool(key: String, default: Boolean): Boolean
    fun putBool(key: String, value: Boolean)
}

class SharedKeyValue(private val prefs: SharedPreferences) : KeyValue {
    constructor(context: Context, file: String) : this(context.applicationContext.getSharedPreferences(file, Context.MODE_PRIVATE))

    override fun string(key: String): String? = prefs.getString(key, null)
    override fun putString(key: String, value: String?) = prefs.edit { if (value == null) remove(key) else putString(key, value) }
    override fun bool(key: String, default: Boolean): Boolean = prefs.getBoolean(key, default)
    override fun putBool(key: String, value: Boolean) = prefs.edit { putBoolean(key, value) }
}

class MemoryKeyValue : KeyValue {
    private val values = mutableMapOf<String, Any>()
    override fun string(key: String): String? = values[key] as? String
    override fun putString(key: String, value: String?) { if (value == null) values.remove(key) else values[key] = value }
    override fun bool(key: String, default: Boolean): Boolean = values[key] as? Boolean ?: default
    override fun putBool(key: String, value: Boolean) { values[key] = value }
}
