// Units on the board from pixels: health bars (your units are green in planning), the item icons under
// each bar matched against icon templates, and crops for re-identifying champions across frames.
// Compiled into tftcap together with tftcap.swift.
//
//   capture/tftcap units frame.png [--model data/models/items.mlmodel | --items DIR] [--dump DIR]
//       one JSON line per unit: {"x","y","w","h"} of its health bar (fractions, origin top-left), "stars"
//       from the badge at the bar's left end (when read),
//       "items": per filled slot [name, confidence, runner-up, confidence] with --model (trained classifier,
//       tools/train_items.swift), else template distances with --items; --dump writes crops for inspection
import CoreGraphics
import CoreML
import Foundation
import ImageIO
import Vision

struct Pixels {
    let w: Int, h: Int
    let data: [UInt8]                       // RGBA
    init(_ img: CGImage) {
        w = img.width; h = img.height
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        data = buf
    }
    @inline(__always) func rgb(_ x: Int, _ y: Int) -> (Int, Int, Int) {
        let i = (y * w + x) * 4
        return (Int(data[i]), Int(data[i + 1]), Int(data[i + 2]))
    }
}

struct Bar { var x0: Int, x1: Int, y0: Int, y1: Int }

/// Your units' health bars: 2-6 px tall runs of saturated green, gaps of 1-2 px allowed (segment ticks).
func healthBars(_ p: Pixels) -> [Bar] {
    func green(_ x: Int, _ y: Int) -> Bool { let (r, g, b) = p.rgb(x, y); return g > 130 && g - max(r, b) > 60 }
    let minLen = max(8, p.w / 100)
    var runs: [(y: Int, x0: Int, x1: Int)] = []
    for y in 0..<p.h {
        var x = 0
        while x < p.w {
            guard green(x, y) else { x += 1; continue }
            var end = x, gap = 0, k = x + 1
            while k < p.w && gap <= 2 { if green(k, y) { end = k; gap = 0 } else { gap += 1 }; k += 1 }
            if end - x + 1 >= minLen { runs.append((y, x, end)) }
            x = end + 1
        }
    }
    var bars: [Bar] = []
    for r in runs {                                       // stack runs on consecutive rows that overlap in x
        if let i = bars.lastIndex(where: { $0.y1 >= r.y - 1 && $0.x0 <= r.x1 && r.x0 <= $0.x1 }) {
            bars[i].y1 = r.y; bars[i].x0 = min(bars[i].x0, r.x0); bars[i].x1 = max(bars[i].x1, r.x1)
        } else {
            bars.append(Bar(x0: r.x0, x1: r.x1, y0: r.y, y1: r.y))
        }
    }
    let maxH = max(4, p.h / 120)
    // units stand on the board and bench: green bars elsewhere are HUD (the round timer at the top)
    return bars.filter { $0.y1 - $0.y0 + 1 >= 2 && $0.y1 - $0.y0 + 1 <= maxH && $0.y0 > p.h / 10 && $0.y0 < p.h * 8 / 10 }
}

/// Star level from the badge at the bar's left end: bronze chevron 1, silver diamond 2, gold double chevron 3.
/// Counts badge-coloured pixels in a small window left of the bar (scaled to the bar width): silver = bright
/// and bluish; warm pixels are gold when the badge is big (18+ at 1080p) and yellow (median G/R 0.86+),
/// else bronze. Measured on real badges: bronze 6-25 px with median G/R 0.73-0.89 (small early, browner
/// late), gold 23-31 px at 0.91-0.95, so neither size nor colour alone separates them. nil when too few.
func starLevel(_ p: Pixels, _ b: Bar, _ ref: Int) -> Int? {
    let r = Double(ref)
    var silver = 0
    var warm: [Double] = []
    let x0 = max(0, b.x0 - Int(0.18 * r)), y0 = max(0, b.y0 - Int(0.04 * r)), y1 = min(p.h - 1, b.y1 + Int(0.07 * r))
    guard x0 < b.x0 - 1 else { return nil }
    for y in y0...y1 {
        for x in x0..<(b.x0 - 1) {
            let (red, g, bl) = p.rgb(x, y)
            if min(red, g, bl) >= 120 && bl >= red && bl - red <= 70 && abs(g - bl) < 40 {
                silver += 1
            } else if red > 150 && red > g && g > bl && red - bl >= 50 {
                warm.append(Double(g) / Double(red))
            }
        }
    }
    let scale = r * r / (63 * 63)                                           // 1 at 1080p (bars ~63 px wide)
    let minPixels = max(3, Int(4 * scale))
    if silver >= warm.count { return silver >= minPixels ? 2 : nil }
    guard warm.count >= minPixels else { return nil }
    let median = warm.sorted()[warm.count / 2]
    return warm.count >= max(8, Int(18 * scale)) && median >= 0.86 ? 3 : 1
}

/// Small RGB thumbnail (s x s), area-averaged: templates and crops are compared at the same blur.
func thumb(_ img: CGImage, _ s: Int) -> [Float] {
    var buf = [UInt8](repeating: 0, count: s * s * 4)
    let ctx = CGContext(data: &buf, width: s, height: s, bitsPerComponent: 8, bytesPerRow: s * 4,
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.interpolationQuality = .high
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: s, height: s))
    var out = [Float](); out.reserveCapacity(s * s * 3)
    for i in 0..<(s * s) { for c in 0..<3 { out.append(Float(buf[i * 4 + c]) / 255) } }
    return out
}

/// Distance after removing each image's mean brightness per channel (lighting and video gamma differ).
func dist(_ a: [Float], _ b: [Float]) -> Float {
    var ma: [Float] = [0, 0, 0], mb: [Float] = [0, 0, 0]
    let n = Float(a.count / 3)
    for i in 0..<a.count { ma[i % 3] += a[i] / n; mb[i % 3] += b[i] / n }
    var d: Float = 0
    for i in 0..<a.count { let e = (a[i] - ma[i % 3]) - (b[i] - mb[i % 3]); d += e * e }
    return (d / Float(a.count)).squareRoot()
}

let THUMB = 12
let ITEM_MIN_CONF: Float = 0.6                   // below this a slot reads as empty (and so do the slots after it)

struct Templates {
    var names: [String] = [], thumbs: [[Float]] = []
    init(_ dir: String?) {
        guard let dir = dir else { return }
        var label: [String: String] = [:]                 // file -> display name, from index.json if present
        if let d = FileManager.default.contents(atPath: dir + "/index.json"),
           let idx = try? JSONSerialization.jsonObject(with: d) as? [[String: Any]] {
            for e in idx { if let f = e["file"] as? String, let n = e["name"] as? String { label[f] = n } }
        }
        for f in ((try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []).sorted() where f.hasSuffix(".png") {
            guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: dir + "/" + f) as CFURL, nil),
                  let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { continue }
            // drop the outer 8%: in game the icon sits inside a thin frame
            let m = Int(Double(img.width) * 0.08)
            let core = img.cropping(to: CGRect(x: m, y: m, width: img.width - 2 * m, height: img.height - 2 * m)) ?? img
            names.append(label[f] ?? String(f.dropLast(4)))
            thumbs.append(thumb(core, THUMB))
        }
    }
    /// best and runner-up template for a crop, trying 1 px shifts and a 1 px size change
    func match(_ img: CGImage, _ r: CGRect) -> (String, Float, String, Float)? {
        guard !names.isEmpty else { return nil }
        var best: [(Float, Int)] = []
        for ds in [-1.0, 0.0, 1.0] { for dx in [-1.0, 0.0, 1.0] { for dy in [-1.0, 0.0, 1.0] {
            let c = CGRect(x: r.minX + dx, y: r.minY + dy, width: r.width + ds, height: r.height + ds)
            guard let crop = img.cropping(to: c) else { continue }
            let t = thumb(crop, THUMB)
            for (i, tt) in thumbs.enumerated() { best.append((dist(t, tt), i)) }
        } } }
        var seen = Set<Int>(), top: [(Float, Int)] = []
        for b in best.sorted(by: { $0.0 < $1.0 }) where !seen.contains(b.1) { seen.insert(b.1); top.append(b); if top.count == 2 { break } }
        guard top.count == 2 else { return nil }
        return (names[top[0].1], top[0].0, names[top[1].1], top[1].0)
    }
}

/// The trained item classifier (tools/train_items.swift): label + confidence for a crop, "empty" for no item.
struct ItemModel {
    let model: VNCoreMLModel?
    init(_ path: String?) {
        guard let path = path, let compiled = try? MLModel.compileModel(at: URL(fileURLWithPath: path)),
              let m = try? MLModel(contentsOf: compiled) else { model = nil; return }
        model = try? VNCoreMLModel(for: m)
    }
    func classify(_ img: CGImage) -> [(String, Float)] {
        guard let model = model else { return [] }
        let req = VNCoreMLRequest(model: model)
        req.imageCropAndScaleOption = .scaleFill
        try? VNImageRequestHandler(cgImage: img).perform([req])
        return ((req.results as? [VNClassificationObservation]) ?? []).prefix(2).map { ($0.identifier, $0.confidence) }
    }
}

/// The champion model stands under its bar (items overlay its head): the box used to recognise it.
func unitBox(_ b: Bar, _ ref: Int) -> CGRect {
    CGRect(x: Double(b.x0) - 0.55 * Double(ref), y: Double(b.y1) + 0.55 * Double(ref), width: 2.1 * Double(ref), height: 2.4 * Double(ref))
}

/// Item slot rectangles under a bar, sized from the typical full bar width in the frame.
func itemSlots(_ b: Bar, _ ref: Int) -> [CGRect] {
    let s = Double(ref) * 0.405, left = Double(b.x0) - Double(ref) * 0.19, top = Double(b.y1) + Double(ref) * 0.143
    return (0..<3).map { CGRect(x: left + Double($0) * s, y: top, width: s, height: s) }
}

let sharedItemModel = ItemModel(option("--model"))

/// Top two labels for a crop, averaged over the crop nudged by a pixel: one shifted crop's misread doesn't decide.
func vote(_ img: CGImage, _ r: CGRect, _ clf: ItemModel) -> [(String, Float)] {
    var votes: [String: Float] = [:]
    var n = 0
    for (dx, dy) in [(0.0, 0.0), (-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)] {
        guard let c = img.cropping(to: r.offsetBy(dx: dx, dy: dy)) else { continue }
        for (label, conf) in clf.classify(c) { votes[label, default: 0] += conf }
        n += 1
    }
    return votes.sorted { $0.value > $1.value }.prefix(2).map { ($0.key, $0.value / Float(max(n, 1))) }
}

/// The item bench: 10 square slots down the left edge of the HUD, beside the trait panel. Measured on a
/// 1080p game (first slot at y 261, 54 px apart, 45 px wide at x 10); kept in units of frame height, as the
/// HUD scales with height. Empty slots are black inside.
let HELD_SLOTS = 10, HELD_X = 0.0093, HELD_Y0 = 0.2417, HELD_DY = 0.05, HELD_SIDE = 0.0417

func heldSlot(_ k: Int, _ h: Int) -> CGRect {
    let H = Double(h)
    return CGRect(x: HELD_X * H, y: (HELD_Y0 + Double(k) * HELD_DY) * H, width: HELD_SIDE * H, height: HELD_SIDE * H)
}

/// Items held on the bench: [slot, label, conf, label2, conf2] per filled slot (confident reads only).
func heldItems(_ img: CGImage, dump: String? = nil) -> [[Any]] {
    let p = Pixels(img)
    let clf = sharedItemModel
    var out: [[Any]] = []
    for k in 0..<HELD_SLOTS {
        let r = heldSlot(k, p.h)
        let inner = r.insetBy(dx: r.width * 0.3, dy: r.height * 0.3)        // the icon's middle, inside its frame
        var sum = 0, n = 0
        for y in Int(inner.minY)..<Int(inner.maxY) { for x in Int(inner.minX)..<Int(inner.maxX) where x < p.w && y < p.h {
            let (r, g, b) = p.rgb(x, y); sum += r + g + b; n += 1 } }
        if n == 0 || sum / (3 * n) < 22 { continue }                        // black: an empty slot
        if let d = dump, let c = img.cropping(to: r) { save(c, "\(d)/held\(k).png") }
        guard clf.model != nil else { continue }
        let top = vote(img, r, clf)
        guard let best = top.first, best.0 != "empty", best.1 >= ITEM_MIN_CONF else { continue }
        out.append([k] + top.flatMap { [$0.0, Double($0.1)] as [Any] })
    }
    return out
}

func held(_ path: String) throws {
    for h in heldItems(cropBorders(load(path)), dump: option("--dump")) { print(try json(["slot": h[0], "item": h[1], "conf": h[2]])) }
}

/// Units in one (border-cropped) frame: bar box (fractions) and items per unit.
func unitRows(_ img: CGImage, dump: String? = nil) -> [[String: Any]] {
    let p = Pixels(img)
    let bars = healthBars(p)
    let widths = bars.map { $0.x1 - $0.x0 + 1 }.sorted()
    let ref = widths.isEmpty ? 0 : widths[widths.count * 3 / 4]       // full-HP width (some bars are damaged)
    let tpl = Templates(option("--items"))
    let clf = sharedItemModel
    var out: [[String: Any]] = []
    for b in bars where Double(b.x1 - b.x0 + 1) >= 0.6 * Double(ref) {   // not a panel's HP bar
        let n = out.count                                // crop names follow the output order
        var items: [[Any]] = []
        var open = true                                  // items fill slots left to right
        for (k, r) in itemSlots(b, ref).enumerated() {
            if let d = dump, let c = img.cropping(to: r) { save(c, "\(d)/u\(n)_slot\(k).png") }
            if clf.model != nil {
                let top = vote(img, r, clf)
                guard open, let best = top.first, best.0 != "empty", best.1 >= ITEM_MIN_CONF else { open = false; continue }
                items.append(top.flatMap { [$0.0, Double($0.1)] as [Any] })
            } else if let m = tpl.match(img, r) { items.append([m.0, Double(m.1), m.2, Double(m.3)]) }
        }
        if let d = dump, let c = img.cropping(to: unitBox(b, ref)) { save(c, "\(d)/u\(n)_unit.png") }
        var row: [String: Any] = ["x": Double(b.x0) / Double(p.w), "y": Double(b.y0) / Double(p.h),
                                  "w": Double(b.x1 - b.x0 + 1) / Double(p.w), "h": Double(b.y1 - b.y0 + 1) / Double(p.h),
                                  "items": items]
        if let s = starLevel(p, b, ref) { row["stars"] = s }
        out.append(row)
    }
    return out
}

func units(_ path: String) throws {
    for u in unitRows(cropBorders(load(path)), dump: option("--dump")) { print(try json(u)) }
}

/// Vision feature prints (image fingerprints) for grouping look-alike crops: one JSON line per image,
/// {"path", "v": [floats]}; Euclidean distance between vectors ~ visual difference.
func fprints(_ paths: [String]) throws {
    for path in paths {
        let req = VNGenerateImageFeaturePrintRequest()
        try VNImageRequestHandler(cgImage: load(path)).perform([req])
        guard let obs = req.results?.first as? VNFeaturePrintObservation else { continue }
        let v: [Float] = obs.data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        print(try json(["path": path, "v": v.map { (Double($0) * 1e4).rounded() / 1e4 }]))
    }
}
