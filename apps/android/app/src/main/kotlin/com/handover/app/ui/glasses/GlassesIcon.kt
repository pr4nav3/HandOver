package com.handover.app.ui.glasses

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/** An eyeglasses symbol (the Material set has none): two rounded lenses, a bridge, two short temples. */
val EyeglassesIcon: ImageVector by lazy {
    ImageVector.Builder("Eyeglasses", 24.dp, 24.dp, 24f, 24f).apply {
        path(stroke = SolidColor(Color.Black), strokeLineWidth = 1.8f, strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round) {
            // Left lens
            moveTo(3.5f, 10.5f); lineTo(10f, 10.5f)
            curveTo(10f, 13.5f, 9.2f, 16f, 6.8f, 16f)
            curveTo(4.4f, 16f, 3.5f, 13.6f, 3.5f, 10.5f)
            close()
            // Right lens
            moveTo(14f, 10.5f); lineTo(20.5f, 10.5f)
            curveTo(20.5f, 13.6f, 19.6f, 16f, 17.2f, 16f)
            curveTo(14.8f, 16f, 14f, 13.5f, 14f, 10.5f)
            close()
            // Bridge
            moveTo(10f, 11.2f); curveTo(11f, 10.4f, 13f, 10.4f, 14f, 11.2f)
            // Temples
            moveTo(3.5f, 10.5f); lineTo(2f, 8f)
            moveTo(20.5f, 10.5f); lineTo(22f, 8f)
        }
    }.build()
}
