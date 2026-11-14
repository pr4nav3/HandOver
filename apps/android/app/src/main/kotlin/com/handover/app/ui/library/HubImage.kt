package com.handover.app.ui.library

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Request

/**
 * Lesson pictures (covers, reference frames) from the hub. No image library: one OkHttp GET, decoded at a
 * bounded size, kept in a small memory cache. Tries each URL in order, so a missing `produced/cover.jpg`
 * falls back to `frames/01.jpg`; with none, the black `stage` fill stays, which is what an empty video
 * pane looks like everywhere in HandOver.
 */
object HubImages {
    private val cache = object : LruCache<String, Bitmap>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private val missing = java.util.Collections.synchronizedSet(mutableSetOf<String>())

    suspend fun load(urls: List<String>, maxSide: Int = 960): ImageBitmap? {
        for (url in urls) {
            cache.get(url)?.let { return it.asImageBitmap() }
            if (url in missing) continue
            val bitmap = try {
                fetch(url, maxSide)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                null
            }
            if (bitmap != null) {
                cache.put(url, bitmap)
                return bitmap.asImageBitmap()
            }
            missing += url
        }
        return null
    }

    /** Forget misses, so pull to refresh finds a cover the hub made since. */
    fun forgetMisses() = missing.clear()

    private suspend fun fetch(url: String, maxSide: Int): Bitmap? = withContext(Dispatchers.IO) {
        CourseApi.sharedHttp.newCall(Request.Builder().url(url).build()).execute().use { response ->
            if (!response.isSuccessful) return@use null
            val bytes = response.body?.bytes() ?: return@use null
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            var sample = 1
            while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
        }
    }
}

/** Previews and screenshot tests hand pictures in here instead of fetching (key: the URL without its query). */
val LocalPreviewImages = compositionLocalOf<(String) -> ImageBitmap?> { { null } }

/** A hub picture on the black stage fill, cropped to fill. */
@Composable
fun HubImage(urls: List<String>, modifier: Modifier = Modifier, contentDescription: String? = null, contentScale: ContentScale = ContentScale.Crop) {
    val preview = LocalPreviewImages.current
    val fixed = urls.firstNotNullOfOrNull { preview(it.substringBefore('?')) }
    val loaded by produceState<ImageBitmap?>(fixed, urls) { if (fixed == null && urls.isNotEmpty()) value = HubImages.load(urls) }
    Box(modifier.background(Color.Black)) {
        loaded?.let { Image(it, contentDescription, Modifier.fillMaxSize(), contentScale = contentScale) }
    }
}
