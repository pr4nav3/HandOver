import SwiftUI

/// HandOver's monogram: an H whose crossbar becomes a forward handoff arrow. One continuous-weight,
/// monochrome construction keeps it legible in the sidebar, at favicon size, and in high-contrast themes.
struct HandOverMarkShape: Shape {
    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height) / 64
        let x = (rect.width - 64 * scale) / 2
        let y = (rect.height - 64 * scale) / 2
        func point(_ px: CGFloat, _ py: CGFloat) -> CGPoint {
            CGPoint(x: x + px * scale, y: y + py * scale)
        }

        var path = Path()
        path.move(to: point(12, 8)); path.addLine(to: point(12, 56))
        path.move(to: point(52, 8)); path.addLine(to: point(52, 56))
        path.move(to: point(12, 32)); path.addLine(to: point(52, 32))
        path.move(to: point(40, 20)); path.addLine(to: point(52, 32)); path.addLine(to: point(40, 44))
        return path
    }
}

struct HandOverMark: View {
    var size: CGFloat = 24

    var body: some View {
        HandOverMarkShape()
            .stroke(style: StrokeStyle(lineWidth: size / 8, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

struct HandOverBrandLockup: View {
    var markSize: CGFloat = 22
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.xs) {
            HandOverMark(size: markSize)
            Text("HandOver").font(theme.fonts.headline)
        }
        .foregroundStyle(theme.colors.ink)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("HandOver")
    }
}

#Preview("Brand mark") {
    HStack(spacing: 24) {
        HandOverMark(size: 16)
        HandOverMark(size: 32)
        HandOverBrandLockup()
    }
    .padding()
    .handOverTheme()
}
