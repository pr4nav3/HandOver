package com.handover.app.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Where sign-in tokens live, one per hub (keyed by [HubUrl.display]). An interface so JVM tests use memory. */
interface TokenStore {
    fun token(hub: String): String?
    fun save(hub: String, token: String?)
}

/** Tokens in memory only. For tests, and the fallback when the Keystore is not usable. */
class MemoryTokenStore : TokenStore {
    private val tokens = mutableMapOf<String, String>()
    @Synchronized override fun token(hub: String): String? = tokens[hub]
    @Synchronized override fun save(hub: String, token: String?) {
        if (token == null) tokens.remove(hub) else tokens[hub] = token
    }
}

/**
 * Tokens encrypted with an AES-256-GCM key that never leaves the Android Keystore, stored as
 * base64 (IV then ciphertext) in a private preferences file that backups skip (allowBackup is off).
 * If the Keystore fails on this device, tokens stay in memory for the session rather than ever
 * being written in plain text.
 */
class KeystoreTokenStore(context: Context) : TokenStore {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    private val fallback = MemoryTokenStore()

    @Synchronized override fun token(hub: String): String? {
        val stored = prefs.getString(KEY_PREFIX + hub, null) ?: return fallback.token(hub)
        return runCatching { decrypt(stored) }.getOrElse {
            // Unreadable (a restored file, or the key was reset): drop it so the person signs in again.
            prefs.edit { remove(KEY_PREFIX + hub) }
            null
        }
    }

    @Synchronized override fun save(hub: String, token: String?) {
        if (token == null) {
            prefs.edit { remove(KEY_PREFIX + hub) }
            fallback.save(hub, null)
            return
        }
        val sealed = runCatching { encrypt(token) }.getOrNull()
        if (sealed == null) {
            fallback.save(hub, token)
            return
        }
        prefs.edit { putString(KEY_PREFIX + hub, sealed) }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(sealed, Base64.NO_WRAP)
    }

    private fun decrypt(stored: String): String {
        val bytes = Base64.decode(stored, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_BYTES))
        return String(cipher.doFinal(bytes, IV_BYTES, bytes.size - IV_BYTES), Charsets.UTF_8)
    }

    private companion object {
        const val FILE = "handover_secure"
        const val KEY_PREFIX = "token:"
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "handover_tokens"
        const val TRANSFORM = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}

/**
 * The app's one account session: the token store every hub call reads its bearer token from
 * (AccountApi, CourseApi, the Done score and rating, and select_lesson on the viewer socket).
 */
object AccountSession {
    @Volatile var tokens: TokenStore = MemoryTokenStore()
        private set

    @Volatile private var installed = false

    /** Switches to Keystore-backed storage, once. Moves a token an older build kept in plain text. */
    fun install(context: Context) {
        if (installed) return
        synchronized(this) {
            if (installed) return
            val secure = KeystoreTokenStore(context)
            val legacy = context.applicationContext.getSharedPreferences("handover_account", Context.MODE_PRIVATE)
            legacy.all.forEach { (key, value) ->
                if (key.startsWith("token:") && value is String) secure.save(key.removePrefix("token:"), value)
            }
            legacy.edit { legacy.all.keys.filter { it.startsWith("token:") }.forEach { remove(it) } }
            tokens = secure
            installed = true
        }
    }

    /** For tests: a fresh store. */
    fun useForTests(store: TokenStore) {
        tokens = store
        installed = true
    }

    /** The bearer token for [hub], or null when signed out there. */
    fun token(hub: HubUrl?): String? = hub?.let { tokens.token(it.display) }?.takeIf { it.isNotBlank() }
}
