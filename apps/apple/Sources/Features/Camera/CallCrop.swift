import CoreGraphics
import Foundation

/// Finds the remote video inside a call window: the largest connected region of busy (high-variance) pixels.
/// Call chrome (title bars, sidebars, button bars on flat color) is smooth; video is textured. Text in
/// sidebars is busy too, but it breaks into many small pieces, so the largest piece is the video.
///
/// Works on a small grayscale copy, so it is cheap enough to run on the first frames of a capture.
enum CallCrop {
    /// Cells across the long side of the analysis grid.
    static let gridLong = 48
    /// A cell is busy when its brightness standard deviation (0 to 255) is above this.
    static let busyThreshold: Double = 4
    /// Below this share of the frame the guess is not trusted and the whole window is used.
    static let minimumShare: Double = 0.08

    /// The video area as a rectangle normalized to 0...1 with the origin at the top left, or the whole frame
    /// when nothing stands out.
    static func detect(in image: CGImage) -> CGRect {
        guard let gray = grayscale(image, longSide: gridLong * 8) else { return full }
        let cell = max(1, max(gray.width, gray.height) / gridLong)
        let cols = gray.width / cell, rows = gray.height / cell
        guard cols >= 4, rows >= 4 else { return full }

        var busy = [Bool](repeating: false, count: cols * rows)
        for r in 0..<rows {
            for c in 0..<cols {
                busy[r * cols + c] = deviation(gray, x: c * cell, y: r * cell, side: cell) > busyThreshold
            }
        }
        guard let found = largestComponent(busy, cols: cols, rows: rows) else { return full }
        let box = trimmed(found, busy, cols: cols)
        let share = Double(box.count) / Double(cols * rows)
        guard share >= minimumShare else { return full }
        let rect = CGRect(x: Double(box.minX) / Double(cols), y: Double(box.minY) / Double(rows),
                          width: Double(box.maxX - box.minX + 1) / Double(cols),
                          height: Double(box.maxY - box.minY + 1) / Double(rows))
        return rect.intersection(full)
    }

    static let full = CGRect(x: 0, y: 0, width: 1, height: 1)

    /// `rect` (normalized, top-left origin) in pixels of an image `size`, rounded to even numbers.
    static func pixels(_ rect: CGRect, in size: CGSize) -> CGRect {
        func even(_ v: CGFloat) -> CGFloat { (v / 2).rounded(.down) * 2 }
        let r = rect.intersection(full)
        return CGRect(x: even(r.minX * size.width), y: even(r.minY * size.height),
                      width: max(2, even(r.width * size.width)), height: max(2, even(r.height * size.height)))
    }

    // MARK: - Pieces

    struct Gray {
        let width: Int
        let height: Int
        let bytes: [UInt8]
    }

    static func grayscale(_ image: CGImage, longSide: Int) -> Gray? {
        let scale = min(1, Double(longSide) / Double(max(image.width, image.height)))
        let w = max(1, Int(Double(image.width) * scale)), h = max(1, Int(Double(image.height) * scale))
        var bytes = [UInt8](repeating: 0, count: w * h)
        let ok = bytes.withUnsafeMutableBytes { buffer -> Bool in
            guard let ctx = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                                      space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)
            else { return false }
            ctx.interpolationQuality = .medium
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        // CGContext rows run top to bottom in memory, matching the top-left origin used here.
        return ok ? Gray(width: w, height: h, bytes: bytes) : nil
    }

    static func deviation(_ g: Gray, x: Int, y: Int, side: Int) -> Double {
        var sum = 0.0, sq = 0.0, n = 0.0
        for yy in y..<min(y + side, g.height) {
            let row = yy * g.width
            for xx in x..<min(x + side, g.width) {
                let v = Double(g.bytes[row + xx])
                sum += v
                sq += v * v
                n += 1
            }
        }
        guard n > 1 else { return 0 }
        let mean = sum / n
        return (max(0, sq / n - mean * mean)).squareRoot()
    }

    /// Peels off edge rows and columns of the box that are mostly calm: a button bar or a caption joined to
    /// the video by one busy cell is not part of the picture.
    static func trimmed(_ box: Box, _ m: [Bool], cols: Int, density: Double = 0.5) -> Box {
        var b = box
        func rowShare(_ r: Int) -> Double {
            Double((b.minX...b.maxX).filter { m[r * cols + $0] }.count) / Double(b.maxX - b.minX + 1)
        }
        func colShare(_ c: Int) -> Double {
            Double((b.minY...b.maxY).filter { m[$0 * cols + c] }.count) / Double(b.maxY - b.minY + 1)
        }
        var changed = true
        while changed, b.maxX > b.minX + 1, b.maxY > b.minY + 1 {
            changed = false
            if rowShare(b.minY) < density { b.minY += 1; changed = true }
            if rowShare(b.maxY) < density { b.maxY -= 1; changed = true }
            if colShare(b.minX) < density { b.minX += 1; changed = true }
            if colShare(b.maxX) < density { b.maxX -= 1; changed = true }
        }
        return b
    }

    struct Box {
        var minX: Int, minY: Int, maxX: Int, maxY: Int, count: Int
    }

    /// The bounding box of the biggest 8-connected group of busy cells (diagonal neighbors count, so a calm
    /// cell or two inside the video does not split it).
    static func largestComponent(_ m: [Bool], cols: Int, rows: Int) -> Box? {
        var seen = [Bool](repeating: false, count: m.count)
        var best: Box?
        var stack: [Int] = []
        for start in m.indices where m[start] && !seen[start] {
            var box = Box(minX: cols, minY: rows, maxX: 0, maxY: 0, count: 0)
            stack.append(start)
            seen[start] = true
            while let i = stack.popLast() {
                let c = i % cols, r = i / cols
                box.minX = min(box.minX, c); box.maxX = max(box.maxX, c)
                box.minY = min(box.minY, r); box.maxY = max(box.maxY, r)
                box.count += 1
                for (dc, dr) in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)] {
                    let nc = c + dc, nr = r + dr
                    guard nc >= 0, nr >= 0, nc < cols, nr < rows else { continue }
                    let j = nr * cols + nc
                    if m[j] && !seen[j] {
                        seen[j] = true
                        stack.append(j)
                    }
                }
            }
            if box.count > (best?.count ?? 0) { best = box }
        }
        return best
    }
}

/// The crop a person chose for an app's call window, remembered per app.
struct CallCropMemory: @unchecked Sendable {
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    func crop(for bundleID: String) -> CGRect? {
        guard let values = defaults.array(forKey: key(bundleID)) as? [Double], values.count == 4 else { return nil }
        let rect = CGRect(x: values[0], y: values[1], width: values[2], height: values[3])
        return rect.width > 0.05 && rect.height > 0.05 ? rect : nil
    }

    func save(_ rect: CGRect, for bundleID: String) {
        defaults.set([rect.minX, rect.minY, rect.width, rect.height], forKey: key(bundleID))
    }

    func forget(_ bundleID: String) { defaults.removeObject(forKey: key(bundleID)) }

    private func key(_ bundleID: String) -> String { "handover.windowCrop." + bundleID }
}
