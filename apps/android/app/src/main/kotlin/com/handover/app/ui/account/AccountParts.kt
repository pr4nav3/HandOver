package com.handover.app.ui.account

import android.graphics.Bitmap
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HandOver

/** How easy a passcode is to guess (SCREENS.md 25.4). Describes guessability, never promises security. */
enum class Strength(val segments: Int, val line: String) {
    TooShort(0, "At least 4 characters."),
    Easy(1, "Easy to guess. Anyone nearby could try it."),
    Ok(2, "OK for a shared workshop hub."),
    Hard(3, "Hard to guess."),
}

object Passcode {
    const val MIN = 4
    const val MAX = 12

    fun strength(p: String): Strength = when {
        p.length < MIN -> Strength.TooShort
        p.length <= 5 || p.toSet().size == 1 || isRun(p) -> Strength.Easy
        p.length >= 8 && p.any(Char::isLetter) && p.any(Char::isDigit) -> Strength.Hard
        else -> Strength.Ok
    }

    /** 1234, 4321, abcd, dcba: each character one more (or one less) than the last. */
    fun isRun(p: String): Boolean {
        if (p.length < 3) return false
        val steps = p.lowercase().zipWithNext { a, b -> b - a }.toSet()
        return steps == setOf(1) || steps == setOf(-1)
    }
}

/** The 8 avatar hues of DESIGN.md 7.4, light and dark. */
enum class AvatarHue(val title: String, val light: Long, val dark: Long) {
    Blue("Blue", 0xFF3249B8, 0xFF8AA8FF), Teal("Teal", 0xFF0A6570, 0xFF5CCFD9), Violet("Violet", 0xFF6E3FB0, 0xFFC4A1FF),
    Berry("Berry", 0xFFA02C6A, 0xFFFF8CC6), Olive("Olive", 0xFF56620C, 0xFFC8D46A), Slate("Slate", 0xFF4D5868, 0xFFAEB8C6),
    Rust("Rust", 0xFF963C22, 0xFFF0A07E), Green("Green", 0xFF345C3D, 0xFF9CCB9F);

    companion object {
        /** The default hue from a stable hash of the name, so it stays the same across devices. */
        fun forName(name: String): AvatarHue {
            var h = 0
            name.trim().lowercase().forEach { h = 31 * h + it.code }
            return entries[Math.floorMod(h, entries.size)]
        }
    }
}

object Initials {
    /** First letter of the first two words, uppercase; one letter for one word; "?" for none. */
    fun of(name: String): String {
        val words = name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        return words.take(2).mapNotNull { w -> w.firstOrNull { it.isLetterOrDigit() }?.uppercaseChar() }.joinToString("").ifEmpty { "?" }
    }
}

/** A person avatar: a circle with initials on the hue's wash (DESIGN.md 7.4). Mono themes use `well` and `ink`. */
@Composable
fun PersonAvatar(name: String, size: Dp, modifier: Modifier = Modifier, hue: AvatarHue = AvatarHue.forName(name)) {
    val c = HandOver.colors
    val mono = HandOver.isMono
    val ink = if (mono) c.ink else Color(if (c.isDark) hue.dark else hue.light)
    val fill by animateColorAsState(if (mono) c.well else c.wash(ink).compositeOver(c.raised), HOMotion.snappy(HandOver.reduceMotion), label = "avatar")
    Box(modifier.size(size).background(fill, CircleShape).clearAndSetSemantics { }, contentAlignment = Alignment.Center) {
        Text(Initials.of(name), color = ink, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.40f).sp)
    }
}

/** An org avatar: a rounded square, accentSoft fill, letters in accentInk (DESIGN.md 3.24). */
@Composable
fun OrgAvatar(name: String, size: Dp, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val mono = HandOver.isMono
    Box(
        modifier.size(size).background(if (mono) c.well else c.accentSoft, RoundedCornerShape(size * 0.28f)).clearAndSetSemantics { },
        contentAlignment = Alignment.Center,
    ) {
        Text(Initials.of(name), color = if (mono) c.ink else c.accentInk, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.42f).sp)
    }
}

private fun Color.compositeOver(bg: Color): Color {
    val a = alpha
    return Color(red * a + bg.red * (1 - a), green * a + bg.green * (1 - a), blue * a + bg.blue * (1 - a), 1f)
}

/** Three segments and one line (DESIGN.md 7.5). Read by screen readers as part of the field. */
@Composable
fun StrengthMeter(strength: Strength, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val tone = when (strength.segments) { 1 -> c.caution; 2 -> c.accent; 3 -> c.good; else -> c.well }
    Column(modifier.semantics(mergeDescendants = true) { contentDescription = "Passcode strength: ${strength.line}" }, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            repeat(3) { i ->
                val fill by animateColorAsState(if (i < strength.segments) tone else c.well, androidx.compose.animation.core.tween(200), label = "seg$i")
                Box(Modifier.weight(1f).height(4.dp).background(fill, RoundedCornerShape(HORadius.small)))
            }
        }
        Text(strength.line, style = HandOver.type.footnote, color = c.ink2)
    }
}

/** A QR code, black on white with a 4 module quiet zone in every theme so any scanner reads it (DESIGN.md 3.25). */
@Composable
fun QrImage(text: String, size: Dp, modifier: Modifier = Modifier) {
    val bitmap = remember(text) { qrBitmap(text) }
    Box(modifier.size(size).background(Color.White, RoundedCornerShape(HORadius.small)).padding(2.dp)) {
        Image(bitmap.asImageBitmap(), "QR code", filterQuality = FilterQuality.None, modifier = Modifier.size(size - 4.dp))
    }
}

fun qrBitmap(text: String): Bitmap {
    val matrix = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0, mapOf(EncodeHintType.MARGIN to 4))
    val w = matrix.width
    val h = matrix.height
    val pixels = IntArray(w * h) { i -> if (matrix.get(i % w, i / w)) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
    return Bitmap.createBitmap(pixels, w, h, Bitmap.Config.ARGB_8888)
}
