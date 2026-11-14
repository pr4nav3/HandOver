package com.handover.app.ui.onboarding

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bluetooth
import androidx.compose.material.icons.outlined.GraphicEq
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.settings.SymbolTile
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper

/** The pre-prompts of SCREENS.md 25.8 that exist on Android. */
enum class PermissionAsk(val permission: String, val icon: ImageVector, val title: String, val line: String) {
    Camera(
        Manifest.permission.CAMERA, Icons.Outlined.PhotoCamera, "Use the camera",
        "The camera scans the hub's code and shows your work while you learn. Frames go to your hub only and are not saved.",
    ),
    Microphone(
        Manifest.permission.RECORD_AUDIO, Icons.Outlined.Mic, "Record your voice",
        "Talk through each step while you record. HandOver uses your words to find where steps start and end.",
    ),
    Bluetooth(
        Manifest.permission.BLUETOOTH_CONNECT, Icons.Outlined.Bluetooth, "Reach your glasses",
        "HandOver connects to Ray-Ban Meta glasses through Bluetooth and the Meta AI app.",
    ),
    Speech(
        Manifest.permission.RECORD_AUDIO, Icons.Outlined.GraphicEq, "Hear \"next\" and \"back\"",
        "Speech is recognized on this device to move between steps.",
    ),
}

fun Context.has(permission: String): Boolean = ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

private tailrec fun Context.activity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.activity()
    else -> null
}

/**
 * Shows [content] when [ask] is granted. Otherwise shows the pre-prompt card first; Continue spends
 * the system prompt, Not Now calls [onDecline] without spending it. After a hard denial the card
 * offers Open Settings instead (SCREENS.md 25.8).
 */
@Composable
fun PermissionGate(ask: PermissionAsk, onDecline: () -> Unit, content: @Composable () -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(context.has(ask.permission)) }
    var deniedOnce by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        granted = ok
        deniedOnce = !ok
    }
    if (granted) {
        content()
        return
    }
    // Denied with "don't ask again": the system will not show its prompt, so send the person to Settings.
    val blocked = deniedOnce && context.activity()?.let { !ActivityCompat.shouldShowRequestPermissionRationale(it, ask.permission) } == true
    PermissionCard(
        ask, blocked,
        onContinue = {
            if (blocked) context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)))
            else launcher.launch(ask.permission)
        },
        onNotNow = onDecline,
    )
}

/** The card itself: symbol tile 56, title, line, Continue and Not Now. */
@Composable
fun PermissionCard(ask: PermissionAsk, blocked: Boolean, onContinue: () -> Unit, onNotNow: () -> Unit) {
    val c = HandOver.colors
    Box(Modifier.fillMaxSize().paper().statusBarsPadding().navigationBarsPadding()) {
        Column(
            Modifier.fillMaxSize().padding(horizontal = HOSpace.l).padding(bottom = HOSpace.l),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.weight(1f))
            SymbolTile(ask.icon, size = 56.dp, tone = com.handover.app.ui.components.Tone.Accent)
            Spacer(Modifier.height(HOSpace.xl))
            Text(ask.title, style = HandOver.type.title, color = c.ink, textAlign = TextAlign.Center)
            Spacer(Modifier.height(HOSpace.s))
            Text(
                if (blocked) ask.line + " It is off in Settings." else ask.line,
                style = HandOver.type.body, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 340.dp),
            )
            Spacer(Modifier.weight(1.2f))
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                PrimaryButton(if (blocked) "Open Settings" else "Continue", onContinue, fullWidth = true)
                QuietButton("Not Now", onNotNow, size = ButtonSize.Regular)
            }
        }
    }
}
