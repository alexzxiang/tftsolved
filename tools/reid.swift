// How recognisable are champion models from labelled crops? Leave-one-out nearest neighbour on Apple Vision
// feature prints over data/raw/labels/units/<Champion>/*.png, never matching a crop with one taken within
// 20 s of it in the same video (same pose, same spot: too easy).
//
//   swiftc -O tools/reid.swift -o /tmp/reid && /tmp/reid data/raw/labels/units
import CoreGraphics
import Foundation
import ImageIO
import Vision

func load(_ p: String) -> CGImage? { guard let s = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil) else { return nil }; return CGImageSourceCreateImageAtIndex(s, 0, nil) }
func fp(_ img: CGImage) -> VNFeaturePrintObservation? {
    let r = VNGenerateImageFeaturePrintRequest()
    try? VNImageRequestHandler(cgImage: img).perform([r])
    return r.results?.first as? VNFeaturePrintObservation
}

struct Crop { let label: String, video: String, t: Int, print: VNFeaturePrintObservation }

let dir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "data/raw/labels/units"
let fm = FileManager.default
var crops: [Crop] = []
for c in ((try? fm.contentsOfDirectory(atPath: dir)) ?? []).sorted() {
    for f in ((try? fm.contentsOfDirectory(atPath: dir + "/" + c)) ?? []) where f.hasSuffix(".png") {
        let parts = f.split(separator: "_")                  // <tag>_<tag>_<res>_<t>_<src>_<x>.png
        guard parts.count >= 4, let img = load("\(dir)/\(c)/\(f)"), let p = fp(img) else { continue }
        let t = Int(parts[parts.count - 3]) ?? 0
        crops.append(Crop(label: c, video: parts.prefix(parts.count - 3).joined(separator: "_"), t: t, print: p))
    }
}
var right = 0, total = 0, perClass: [String: (Int, Int)] = [:]
for (i, a) in crops.enumerated() {
    var best: (Float, String)? = nil
    for (j, b) in crops.enumerated() where j != i && !(a.video == b.video && abs(a.t - b.t) <= 20) {
        var d: Float = 0
        try? a.print.computeDistance(&d, to: b.print)
        if best == nil || d < best!.0 { best = (d, b.label) }
    }
    guard let b = best else { continue }
    total += 1
    let ok = b.1 == a.label
    right += ok ? 1 : 0
    perClass[a.label, default: (0, 0)] = (perClass[a.label]!.0 + (ok ? 1 : 0), perClass[a.label]!.1 + 1)
}
print("\(crops.count) crops, \(Set(crops.map { $0.label }).count) champions; leave-one-out nearest neighbour: \(right)/\(total)")
for (c, v) in perClass.sorted(by: { $0.value.1 > $1.value.1 }) { print("  \(c): \(v.0)/\(v.1)") }
