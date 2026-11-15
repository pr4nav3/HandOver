import Foundation

/// Cues from a WebVTT file (captions/NN.vtt). AVPlayer does not render a sidecar VTT, so Learn parses it and
/// draws the caption bar itself, in sync with the clip's time.
struct CaptionCues: Equatable, Sendable {
    struct Cue: Equatable, Sendable {
        var start: Double
        var end: Double
        var text: String
    }

    var cues: [Cue]

    /// Parses a WebVTT document. Unreadable cues are skipped; a file without the WEBVTT header still reads, the
    /// way browsers are lenient with what the teach pipeline writes.
    init(parsing text: String) {
        let normalized = text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
        let blocks = normalized.components(separatedBy: "\n\n")
        var cues: [Cue] = []
        for block in blocks {
            var lines = block.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
            guard let timingIndex = lines.firstIndex(where: { $0.contains("-->") }) else { continue }
            if lines.first?.hasPrefix("NOTE") == true || lines.first?.hasPrefix("STYLE") == true { continue }
            let timing = lines[timingIndex]
            lines = Array(lines[(timingIndex + 1)...])
            let parts = timing.components(separatedBy: "-->")
            guard parts.count == 2,
                  let start = Self.time(parts[0]),
                  let end = Self.time(parts[1].trimmingCharacters(in: .whitespaces).components(separatedBy: " ")[0]),
                  end > start else { continue }
            let body = lines.map(Self.stripTags).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !body.isEmpty else { continue }
            cues.append(Cue(start: start, end: end, text: Self.unescape(body)))
        }
        self.cues = cues.sorted { $0.start < $1.start }
    }

    init(cues: [Cue]) { self.cues = cues }

    /// The text showing at `seconds`, or nil between cues. Overlapping cues join with a line break.
    func text(at seconds: Double) -> String? {
        let showing = cues.filter { $0.start <= seconds && seconds < $0.end }
        guard !showing.isEmpty else { return nil }
        return showing.map(\.text).joined(separator: "\n")
    }

    /// "hh:mm:ss.ttt" or "mm:ss.ttt" (a comma also works for the fraction).
    static func time(_ raw: String) -> Double? {
        let t = raw.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
        let parts = t.split(separator: ":").map(String.init)
        guard (2...3).contains(parts.count) else { return nil }
        var total = 0.0
        for (i, part) in parts.enumerated() {
            guard let v = Double(part), v >= 0 else { return nil }
            if i < parts.count - 1, v != v.rounded() { return nil }
            total = total * 60 + v
        }
        return total
    }

    /// Removes `<v Name>`, `<b>`, `<00:01.000>` and other tags, keeping the words.
    static func stripTags(_ line: String) -> String {
        var out = ""
        var inTag = false
        for ch in line {
            if ch == "<" { inTag = true; continue }
            if ch == ">" && inTag { inTag = false; continue }
            if !inTag { out.append(ch) }
        }
        return out
    }

    static func unescape(_ s: String) -> String {
        s.replacingOccurrences(of: "&lt;", with: "<").replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&nbsp;", with: " ").replacingOccurrences(of: "&lrm;", with: "")
            .replacingOccurrences(of: "&rlm;", with: "").replacingOccurrences(of: "&amp;", with: "&")
    }
}
