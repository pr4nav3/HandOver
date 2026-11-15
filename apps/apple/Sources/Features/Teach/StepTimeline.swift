import AVKit
import SwiftUI

/// The step hues (DESIGN.md 3.18): marks, not text, so the number sits in a raised pill on top.
enum TeachStepHues {
    static let all: [Color] = [0x4F78A8, 0x5E8B62, 0xA87A3E, 0x7E62A0, 0xA85E57, 0x3F8A86, 0x8C7E2E, 0x6268A8]
        .map { Color(red: Double(($0 >> 16) & 0xFF) / 255, green: Double(($0 >> 8) & 0xFF) / 255,
                     blue: Double($0 & 0xFF) / 255) }

    static func color(_ index: Int, theme: any Theme) -> Color {
        theme.isMono ? theme.colors.ink2.opacity(index.isMultiple(of: 2) ? 0.35 : 0.22) : all[index % all.count]
    }
}

/// Where steps sit on a timeline: absolute seconds in the lesson's video.
struct TeachTimelineLayout: Equatable, Sendable {
    var spans: [ClosedRange<Double>]
    var start: Double
    var end: Double

    init(spans: [ClosedRange<Double>]) {
        self.spans = spans
        start = spans.first?.lowerBound ?? 0
        end = max(spans.last?.upperBound ?? 1, start + 0.1)
    }

    init(steps: [Step]) {
        var spans: [ClosedRange<Double>] = []
        for step in steps {
            let a = step.startSeconds ?? spans.last?.upperBound ?? 0
            let b = max(step.endSeconds ?? a, a)
            spans.append(a...b)
        }
        self.init(spans: spans)
    }

    var length: Double { end - start }

    func x(_ time: Double, width: CGFloat) -> CGFloat {
        CGFloat((time - start) / length) * width
    }

    func time(atX x: CGFloat, width: CGFloat) -> Double {
        guard width > 0 else { return start }
        return start + Double(min(max(0, x), width) / width) * length
    }
}

/// The colored step track (DESIGN.md 3.18): one segment per step with its number, the selected one outlined,
/// and an optional playhead. Tap a segment to select it.
struct StepTimelineTrack: View {
    var layout: TeachTimelineLayout
    var selected: Int?
    var playhead: Double?
    var height: CGFloat = 44
    var onSelect: (Int) -> Void = { _ in }
    @Environment(\.theme) private var theme

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: HORadius.small, style: .continuous).fill(theme.colors.well)
                ForEach(Array(layout.spans.enumerated()), id: \.offset) { index, span in
                    let x0 = layout.x(span.lowerBound, width: width)
                    let x1 = layout.x(span.upperBound, width: width)
                    let w = max(1, x1 - x0 - 1)
                    segment(index: index, width: w)
                        .frame(width: w, height: height)
                        .offset(x: x0 + 0.5)
                        .onTapGesture { onSelect(index) }
                        .accessibilityElement()
                        .accessibilityLabel("Step \(index + 1)")
                        .accessibilityValue("\(TimeCode.format(span.lowerBound)) to \(TimeCode.format(span.upperBound))")
                        .accessibilityAddTraits(selected == index ? [.isButton, .isSelected] : .isButton)
                        .accessibilityAction { onSelect(index) }
                }
                if let playhead, playhead >= layout.start, playhead <= layout.end {
                    let x = layout.x(playhead, width: width)
                    VStack(spacing: -2) {
                        Circle().fill(theme.colors.ink).frame(width: 10, height: 10)
                        Rectangle().fill(theme.colors.ink).frame(width: 2, height: height + 2)
                    }
                    .frame(width: 10)
                    .offset(x: x - 5, y: -8)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }
            }
        }
        .frame(height: height)
    }

    private func segment(index: Int, width: CGFloat) -> some View {
        let shape = RoundedRectangle(cornerRadius: HORadius.small, style: .continuous)
        return shape
            .fill(TeachStepHues.color(index, theme: theme))
            .overlay(alignment: .topLeading) {
                if width >= 24 {
                    Text("\(index + 1)")
                        .font(theme.fonts.badge.monospacedDigit())
                        .foregroundStyle(theme.colors.ink)
                        .padding(.horizontal, 5)
                        .frame(height: 16)
                        .background(theme.colors.raised, in: Capsule())
                        .padding(4)
                }
            }
            .overlay {
                if selected == index { shape.strokeBorder(theme.colors.ink, lineWidth: 2) }
            }
            .contentShape(shape)
    }
}

/// Start and end times under a track.
struct TeachTimelineScale: View {
    var layout: TeachTimelineLayout
    @Environment(\.theme) private var theme

    var body: some View {
        HStack {
            Text(TimeCode.format(layout.start))
            Spacer()
            Text(TimeCode.format(layout.end))
        }
        .font(theme.fonts.caption.monospacedDigit())
        .foregroundStyle(theme.colors.ink2)
    }
}

/// Plays one clip on the stage color.
struct TeachClipPlayer: View {
    var url: URL?
    var autoplay = true
    @State private var player: AVPlayer?
    @Environment(\.theme) private var theme

    var body: some View {
        ZStack {
            theme.colors.stage
            if let player {
                VideoPlayer(player: player)
            } else {
                Image(systemName: "play.rectangle").font(.largeTitle).foregroundStyle(.white.opacity(0.35))
                    .accessibilityHidden(true)
            }
        }
        .aspectRatio(16 / 9, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .task(id: url) {
            player?.pause()
            guard let url else {
                player = nil
                return
            }
            let next = AVPlayer(url: url)
            player = next
            if autoplay { next.play() }
        }
        .onDisappear { player?.pause() }
    }
}

/// The finished lesson as a timeline (Teach): colored steps, thumbnails under them, and the selected step's
/// clip above. Tapping a segment or a thumbnail plays that step.
struct LessonTimelineView: View {
    var lesson: Lesson
    var hub: HubURL?
    @State private var selected: Int?
    @Environment(\.theme) private var theme

    var body: some View {
        let layout = TeachTimelineLayout(steps: lesson.steps)
        VStack(alignment: .leading, spacing: HOSpace.m) {
            if let selected, let hub, lesson.steps.indices.contains(selected) {
                TeachClipPlayer(url: hub.fileURL(lesson: lesson.id, path: lesson.steps[selected].clip))
                Text("\(selected + 1). \(lesson.steps[selected].title)")
                    .font(theme.fonts.headline)
                    .foregroundStyle(theme.colors.ink)
            }
            StepTimelineTrack(layout: layout, selected: selected) { select($0) }
            TeachTimelineScale(layout: layout)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: HOSpace.s) {
                    ForEach(Array(lesson.steps.enumerated()), id: \.element.id) { index, step in
                        Button { select(index) } label: { thumbnail(index: index, step: step) }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Play step \(index + 1), \(step.title)")
                    }
                }
            }
            .scrollClipDisabled()
        }
        .onChange(of: selected) { Haptics.tap() }
    }

    private func select(_ index: Int) {
        selected = index
    }

    private func thumbnail(index: Int, step: Step) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.xs) {
            HubImage(hub.map { CourseMedia.frame(hub: $0, lessonId: lesson.id, step: step) })
                .frame(width: 112, height: 63)
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: HORadius.small, style: .continuous)
                        .strokeBorder(selected == index ? theme.colors.ink : .clear, lineWidth: 2)
                }
                .overlay(alignment: .bottomLeading) {
                    Rectangle().fill(TeachStepHues.color(index, theme: theme)).frame(height: 3)
                        .clipShape(RoundedRectangle(cornerRadius: 1.5))
                        .padding(.horizontal, 6).padding(.bottom, 4)
                }
            Text("\(index + 1). \(step.title)")
                .font(theme.fonts.caption)
                .foregroundStyle(theme.colors.ink2)
                .lineLimit(1)
                .frame(width: 112, alignment: .leading)
        }
    }
}
