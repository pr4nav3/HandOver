import ImageIO
import SwiftUI

/// The real reference frames of the bundled sample lesson ("Fold a fortune teller", synthetic renders):
/// eight steps of 3 s each, the same spans as `lessons/synthetic-fortune-teller-v1/lesson.json`.
enum SampleLesson {
    static let title = "Fold a fortune teller"
    static let label = "Sample lesson, rendered"
    static let steps = 8
    static let stepSeconds = 3.0
    static let stepTitles = [
        "Lay the square sheet flat", "Fold corner to corner into triangle", "Crease both diagonals, then unfold flat",
        "Fold all four corners to center", "Flip the paper over", "Fold four corners to center again",
        "Crease in half both ways, unfold", "Flip, then push into four pockets",
    ]
    /// Step 4's `common_mistake` line from lesson.json, shown as the caption in the theme preview.
    static let stepFourLine = "Bring every corner to the exact center."

    @MainActor private static var cache: [Int: CGImage] = [:]

    /// Frame `n` (1-based), or nil if the art is missing from the bundle. `prewarm` usually has it decoded already;
    /// otherwise it is decoded here once, fully, so drawing it later never decodes again.
    @MainActor
    static func frame(_ n: Int) -> CGImage? {
        if let hit = cache[n] { return hit }
        guard let image = decode(n) else { return nil }
        cache[n] = image
        return image
    }

    /// Decodes every frame on a background thread, so the welcome pages never decode a picture while drawing.
    @MainActor
    static func prewarm() async {
        let missing = (1...steps).filter { cache[$0] == nil }
        guard !missing.isEmpty else { return }
        let decoded = await Task.detached(priority: .userInitiated) {
            missing.compactMap { n in decode(n).map { Decoded(n: n, image: $0) } }
        }.value
        for frame in decoded where cache[frame.n] == nil { cache[frame.n] = frame.image }
    }

    /// The art is 960 by 540, the size it is drawn at most, so it is decoded at its own size.
    nonisolated private static func decode(_ n: Int) -> CGImage? {
        let name = String(format: "sample-step-%02d", n)
        guard let url = Bundle.main.url(forResource: name, withExtension: "jpg"),
              let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary)
    }

    private struct Decoded: @unchecked Sendable {
        let n: Int
        let image: CGImage
    }
}

/// A sample frame filling its frame, on `stage`.
struct SampleFrame: View {
    var step: Int
    var radius: CGFloat
    @Environment(\.theme) private var theme

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        // The stage sets the size; the frame fills it as an overlay so it never pushes the frame wider.
        theme.colors.stage
            .overlay {
                if let image = SampleLesson.frame(step) {
                    Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fill)
                }
            }
            .clipShape(shape)
        .overlay(shape.strokeBorder(Color.white.opacity(0.08), lineWidth: HOLine.width))
    }
}

/// The illustration stage over the welcome pages. One scene at a time; moving between neighbors morphs the
/// shared pieces with matched geometry (the page 1 panel into tile 1, tile 3 into the right pane).
struct WelcomeStage: View {
    var page: Int
    /// Draw every scene in its end state at once (Reduce Motion, screenshots).
    var settled: Bool
    var scale: CGFloat = 1
    @Namespace private var space

    var body: some View {
        ZStack {
            switch page {
            case 0: RecordScene(space: space, settled: settled, scale: scale)
            case 1: StepsScene(space: space, settled: settled, scale: scale)
            case 2: FollowScene(space: space, settled: settled, scale: scale)
            default: ScoreScene(settled: settled, scale: scale)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.label(page))
        .accessibilityAddTraits(.isImage)
    }

    static func label(_ page: Int) -> String {
        switch page {
        case 0: "A sample lesson playing, with a recording indicator"
        case 1: "The lesson split into 8 steps on a timeline"
        case 2: "Your camera beside the expert's clip. The status changes to verified."
        default: "A score ring and a time bar for each step"
        }
    }
}

// MARK: - Page 1: an expert records once

private struct RecordScene: View {
    let space: Namespace.ID
    let settled: Bool
    let scale: CGFloat
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var frame = 1
    @State private var shown = false

    var body: some View {
        VStack(spacing: HOSpace.m * scale) {
            SampleFrame(step: frame, radius: HORadius.card)
                .matchedGeometryEffect(id: "tile1", in: space)
                .frame(width: 300 * scale, height: 168.75 * scale)
                .overlay(alignment: .topLeading) {
                    HStack(spacing: 6) {
                        Circle().fill(theme.colors.record).frame(width: 8, height: 8)
                        Text("Recording").font(theme.fonts.badge).foregroundStyle(.white)
                    }
                    .padding(.horizontal, 10)
                    .frame(minHeight: 26)
                    .background(.black.opacity(0.55), in: Capsule())
                    .padding(HOSpace.s)
                }
                .contentTransition(.opacity)
            Text(SampleLesson.label)
                .font(theme.fonts.caption)
                .foregroundStyle(theme.colors.ink2)
            HStack(spacing: HOSpace.s) {
                Image(systemName: "waveform")
                    .font(.system(size: 22 * scale, weight: .medium))
                    .foregroundStyle(theme.colors.accentInk)
                    .symbolEffect(.variableColor.iterative, isActive: !settled && !reduceMotion)
                Text(SampleLesson.stepTitles[frame - 1])
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .lineLimit(1)
                    .contentTransition(.opacity)
            }
            .padding(.horizontal, HOSpace.l)
            .frame(minHeight: 36)
            .hoCard(radius: 18)
        }
        .opacity(shown || settled ? 1 : 0)
        .onAppear { withAnimation(.easeOut(duration: 0.3)) { shown = true } }
        .task {
            // The frames of steps 1 to 3 in turn, like the clip playing (stills: no video decoding here).
            guard !settled, !reduceMotion else { return }
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1.4))
                withAnimation(HOMotion.clip) { frame = frame % 3 + 1 }
            }
        }
    }
}

// MARK: - Page 2: steps

private struct StepsScene: View {
    let space: Namespace.ID
    let settled: Bool
    let scale: CGFloat
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var filled = 0

    var body: some View {
        VStack(spacing: HOSpace.l * scale) {
            Grid(horizontalSpacing: HOSpace.s * scale, verticalSpacing: HOSpace.s * scale) {
                ForEach(0..<2, id: \.self) { row in
                    GridRow {
                        ForEach(1...4, id: \.self) { col in
                            tile(row * 4 + col)
                        }
                    }
                }
            }
            timeline
        }
        .onAppear {
            guard !settled, !reduceMotion else { return }
            for i in 1...SampleLesson.steps {
                withAnimation(.easeOut(duration: 0.35).delay(0.25 + Double(i - 1) * 0.12)) { filled = i }
            }
        }
    }

    private func tile(_ n: Int) -> some View {
        SampleFrame(step: n, radius: HORadius.small)
            .matchedGeometryEffect(id: "tile\(n)", in: space)
            .frame(width: 72 * scale, height: 40.5 * scale)
            .overlay(alignment: .bottomLeading) {
                Text("\(n)")
                    .font(.system(size: 11 * scale, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(.white)
                    .frame(minWidth: 16 * scale, minHeight: 16 * scale)
                    .background(.black.opacity(0.6), in: Capsule())
                    .padding(3)
            }
    }

    private var timeline: some View {
        let done = settled || reduceMotion ? SampleLesson.steps : filled
        return VStack(alignment: .leading, spacing: HOSpace.xs) {
            HStack(spacing: 3) {
                ForEach(1...SampleLesson.steps, id: \.self) { i in
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(i <= done ? theme.colors.accent : theme.colors.well)
                        .frame(height: 8 * scale)
                }
            }
            HStack {
                Text("0:00")
                Spacer()
                Text("0:24")
            }
            .font(theme.fonts.caption.monospacedDigit())
            .foregroundStyle(theme.colors.ink2)
        }
        .frame(width: 312 * scale)
    }
}

// MARK: - Page 3: the camera follows along

private struct FollowScene: View {
    let space: Namespace.ID
    let settled: Bool
    let scale: CGFloat
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var verified = false

    var body: some View {
        VStack(spacing: HOSpace.l * scale) {
            HStack(spacing: HOSpace.m * scale) {
                ZStack {
                    RoundedRectangle(cornerRadius: HORadius.card, style: .continuous).fill(theme.colors.stage)
                    CornerBrackets(radius: 12 * scale, reach: 0.24)
                        .stroke(.white.opacity(0.7), style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                        .padding(18 * scale)
                    Image(systemName: "camera.viewfinder")
                        .font(.system(size: 34 * scale, weight: .light))
                        .foregroundStyle(.white.opacity(0.7))
                }
                .frame(width: 148 * scale, height: 112 * scale)
                .overlay(alignment: .bottomLeading) { paneLabel("You") }
                SampleFrame(step: 3, radius: HORadius.card)
                    .matchedGeometryEffect(id: "tile3", in: space)
                    .frame(width: 148 * scale, height: 112 * scale)
                    .overlay(alignment: .bottomLeading) { paneLabel("Expert") }
            }
            StatusBadge(status: verified || settled ? .verified : .watching)
                .animation(reduceMotion ? nil : HOMotion.snappy, value: verified)
        }
        .task {
            guard !settled else { return }
            try? await Task.sleep(for: .seconds(1.2))
            verified = true
        }
    }

    private func paneLabel(_ text: String) -> some View {
        Text(text)
            .font(theme.fonts.badge)
            .foregroundStyle(.white)
            .padding(.horizontal, 8)
            .frame(minHeight: 22)
            .background(.black.opacity(0.55), in: Capsule())
            .padding(HOSpace.s)
    }
}

// MARK: - Page 4: a score and a tip, with no numbers (there is no run yet)

private struct ScoreScene: View {
    let settled: Bool
    let scale: CGFloat
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var ring: CGFloat = 0
    @State private var bars = 0

    private let you: [CGFloat] = [0.62, 0.84, 0.48]
    private let expert: [CGFloat] = [0.70, 0.66, 0.55]

    var body: some View {
        let end = settled || reduceMotion
        VStack(spacing: HOSpace.l * scale) {
            HStack(spacing: HOSpace.xl * scale) {
                ZStack {
                    Circle().stroke(theme.colors.well, lineWidth: 10 * scale)
                    Circle()
                        .trim(from: 0, to: end ? 0.7 : ring)
                        .stroke(theme.colors.good, style: StrokeStyle(lineWidth: 10 * scale, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Text("Your score")
                        .font(theme.fonts.callout)
                        .foregroundStyle(theme.colors.ink2)
                        .multilineTextAlignment(.center)
                }
                .frame(width: 112 * scale, height: 112 * scale)
                VStack(alignment: .leading, spacing: HOSpace.m * scale) {
                    ForEach(0..<3, id: \.self) { i in
                        VStack(alignment: .leading, spacing: 2) {
                            bar(expert[i], color: theme.colors.ink3, shown: end || bars > i)
                            bar(you[i], color: you[i] < expert[i] ? theme.colors.good : theme.colors.accent, shown: end || bars > i)
                        }
                    }
                }
                .frame(width: 150 * scale)
            }
            HStack(spacing: HOSpace.s) {
                Image(systemName: "lightbulb")
                    .foregroundStyle(theme.colors.caution)
                Text("One tip, from your own run.")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink)
            }
            .padding(.horizontal, HOSpace.l)
            .frame(minHeight: 44)
            .hoCard(radius: HORadius.control)
        }
        .onAppear {
            guard !end else { return }
            withAnimation(.easeOut(duration: 0.6)) { ring = 0.7 }
            for i in 1...3 {
                withAnimation(.easeOut(duration: 0.25).delay(0.2 + Double(i - 1) * 0.08)) { bars = i }
            }
        }
    }

    private func bar(_ value: CGFloat, color: Color, shown: Bool) -> some View {
        GeometryReader { geo in
            RoundedRectangle(cornerRadius: 3, style: .continuous)
                .fill(color)
                .frame(width: shown ? geo.size.width * value : 0)
        }
        .frame(height: 6 * scale)
    }
}
