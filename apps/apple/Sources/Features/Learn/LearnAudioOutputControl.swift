import SwiftUI
#if os(iOS)
import AVKit
import UIKit
#endif

/// Shows the current spoken-guidance destination and, on iPhone/iPad, exposes the system output picker so
/// Meta glasses or another Bluetooth route can be selected without leaving the lesson.
struct LearnAudioOutputControl: View {
    var guide: SpokenGuide = .shared
    var compact = false

    var body: some View {
        HStack(spacing: 2) {
            if compact {
                Button {
                    Haptics.tap()
                    guide.isEnabled.toggle()
                } label: {
                    Image(systemName: guide.bluetoothRoute?.isGlasses == true ? "eyeglasses" :
                            guide.isEnabled ? "speaker.wave.2" : "speaker.slash")
                }
                .buttonStyle(HOIconButtonStyle())
                .accessibilityLabel(guide.isEnabled ? "Spoken guidance on" : "Spoken guidance off")
            } else {
                SpokenGuideIndicator(guide: guide)
            }
            #if os(iOS)
            SystemAudioRoutePicker()
                .frame(width: HOSize.touch, height: HOSize.touch)
                .accessibilityLabel("Choose audio output")
                .accessibilityHint("Choose Meta glasses, headphones, or this device")
            #endif
        }
        .accessibilityElement(children: .contain)
    }
}

#if os(iOS)
private struct SystemAudioRoutePicker: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let picker = AVRoutePickerView()
        picker.prioritizesVideoDevices = false
        picker.tintColor = .secondaryLabel
        picker.activeTintColor = .label
        return picker
    }

    func updateUIView(_ view: AVRoutePickerView, context: Context) {}
}
#endif
