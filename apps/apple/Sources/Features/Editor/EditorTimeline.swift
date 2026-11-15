import SwiftUI
#if os(macOS)
import AppKit
#endif

/// The editor's timeline (DESIGN.md 3.18, SCREENS.md 14.4): the colored steps, a playhead, and a 20 point grip on
/// every boundary. Dragging a grip snaps to caption cue edges within 0.4 s (selection haptic on each snap; hold
/// Option on Mac to place freely at 0.1 s), shows the time while dragging, and saves on release. Tapping the
/// track selects the step there and moves the playhead (the split point).
struct EditorTimeline: View {
    var store: EditorStore
    @Binding var playhead: Double?
    @Environment(\.theme) private var theme
    @State private var drag: (index: Int, time: Double, snapped: Bool)?
    @FocusState private var focusedBoundary: Int?

    var body: some View {
        let layout = store.layout
        VStack(alignment: .leading, spacing: HOSpace.s) {
            GeometryReader { geo in
                let width = geo.size.width
                ZStack(alignment: .topLeading) {
                    StepTimelineTrack(layout: previewLayout(layout), selected: store.selection, playhead: playhead)
                        .allowsHitTesting(false)
                    Color.clear
                        .contentShape(Rectangle())
                        .gesture(SpatialTapGesture().onEnded { value in
                            let time = layout.time(atX: value.location.x, width: width)
                            playhead = time
                            if let index = layout.spans.firstIndex(where: { $0.contains(time) }) {
                                store.selection = index
                            }
                        })
                    ForEach(0..<max(0, layout.spans.count - 1), id: \.self) { index in
                        grip(index: index, layout: layout, width: width)
                    }
                    if let drag {
                        Text(TimeCode.format(drag.time))
                            .font(theme.fonts.badge.monospacedDigit())
                            .foregroundStyle(theme.colors.ink)
                            .padding(.horizontal, HOSpace.s)
                            .padding(.vertical, 3)
                            .background(theme.colors.raised, in: Capsule())
                            .overlay(Capsule().strokeBorder(theme.colors.lineStrong, lineWidth: HOLine.width))
                            .hoFloatingShadow()
                            .fixedSize()
                            .offset(x: layout.x(drag.time, width: width) - 30, y: -30)
                            .allowsHitTesting(false)
                    }
                }
            }
            .frame(height: 44)
            .opacity(store.isBusy ? 0.6 : 1)
            .disabled(store.isBusy || !store.permissions.canEdit)
            TeachTimelineScale(layout: layout)
        }
        .padding(.top, HOSpace.l)
        .onChange(of: store.snapCount) { Haptics.tap() }
    }

    /// While dragging, the two neighbors resize live.
    private func previewLayout(_ layout: TeachTimelineLayout) -> TeachTimelineLayout {
        guard let drag, layout.spans.indices.contains(drag.index + 1) else { return layout }
        var spans = layout.spans
        spans[drag.index] = spans[drag.index].lowerBound...drag.time
        spans[drag.index + 1] = drag.time...spans[drag.index + 1].upperBound
        return TeachTimelineLayout(spans: spans)
    }

    private func grip(index: Int, layout: TeachTimelineLayout, width: CGFloat) -> some View {
        let time = drag?.index == index ? drag!.time : layout.spans[index].upperBound
        let x = layout.x(time, width: width)
        let active = drag?.index == index || focusedBoundary == index
        return RoundedRectangle(cornerRadius: 2)
            .fill(active ? theme.colors.ink : theme.colors.lineStrong)
            .frame(width: 4, height: 24)
            .frame(width: 20, height: 44)
            .contentShape(Rectangle())
            .offset(x: x - 10)
            .gesture(DragGesture(minimumDistance: 2, coordinateSpace: .local)
                .onChanged { value in
                    let proposed = layout.time(atX: x + value.translation.width, width: width)
                    guard let result = store.placeBoundary(after: index, at: proposed, free: Self.freePlacement) else { return }
                    if result.snapped && (drag?.time != result.time) { store.noteSnap() }
                    drag = (index, result.time, result.snapped)
                }
                .onEnded { _ in
                    guard let final = drag else { return }
                    drag = nil
                    Task { await store.moveBoundary(after: index, to: final.time) }
                })
            #if os(macOS)
            .onHover { inside in if inside { NSCursor.resizeLeftRight.push() } else { NSCursor.pop() } }
            #endif
            .focusable()
            .focused($focusedBoundary, equals: index)
            .onKeyPress(.leftArrow) { nudge(index, by: -0.1); return .handled }
            .onKeyPress(.rightArrow) { nudge(index, by: 0.1); return .handled }
            .accessibilityElement()
            .accessibilityLabel("Boundary between step \(index + 1) and step \(index + 2)")
            .accessibilityValue(TimeCode.format(time))
            .accessibilityAdjustableAction { direction in
                nudge(index, by: direction == .increment ? 0.1 : -0.1)
            }
    }

    private func nudge(_ index: Int, by delta: Double) {
        guard let current = store.lesson.steps[index].endSeconds,
              let result = store.placeBoundary(after: index, at: current + delta, free: true) else { return }
        Task { await store.moveBoundary(after: index, to: result.time) }
    }

    private static var freePlacement: Bool {
        #if os(macOS)
        NSEvent.modifierFlags.contains(.option)
        #else
        false
        #endif
    }
}
