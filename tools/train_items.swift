// Train the item-icon classifier used by `tftcap units`: synthetic in-game-looking samples (each icon framed,
// shrunk to 15-40 px, blurred, JPEG-compressed, on real board backgrounds) plus an "empty" class of real
// board crops, then Apple's CreateML transfer learning. On-device, no extra dependencies.
//
//   swiftc -O tools/train_items.swift -o /tmp/train_items
//   /tmp/train_items --templates data/raw/cdragon/items --backgrounds DIR_OF_FRAMES --out data/models/items.mlmodel
//       [--per 30] [--extra data/raw/labels/items]   (real tooltip crops, one folder per item: more art per class)
//       [--empties data/raw/labels/empty_slots]      (real, reviewed empty item slots)
import CoreGraphics
import CreateML
import Foundation
import ImageIO
import UniformTypeIdentifiers

func arg(_ n: String) -> String? { let a = CommandLine.arguments; guard let i = a.firstIndex(of: n), i + 1 < a.count else { return nil }; return a[i + 1] }
func load(_ p: String) -> CGImage? { guard let s = CGImageSourceCreateWithURL(URL(fileURLWithPath: p) as CFURL, nil) else { return nil }; return CGImageSourceCreateImageAtIndex(s, 0, nil) }

var seed: UInt64 = 19
func rnd() -> Double { seed = seed &* 6364136223846793005 &+ 1442695040888963407; return Double(seed >> 11) / Double(1 << 53) }
func rint(_ lo: Int, _ hi: Int) -> Int { lo + Int(rnd() * Double(hi - lo + 1)) }

func context(_ s: Int) -> CGContext {
    CGContext(data: nil, width: s, height: s, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
}

/// JPEG round trip at a random quality: video compression smears small icons the same way
func jpeg(_ img: CGImage) -> CGImage {
    let data = NSMutableData()
    let d = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, img, [kCGImageDestinationLossyCompressionQuality: 0.35 + 0.5 * rnd()] as CFDictionary)
    CGImageDestinationFinalize(d)
    let s = CGImageSourceCreateWithData(data, nil)!
    return CGImageSourceCreateImageAtIndex(s, 0, nil)!
}

func savePNG(_ img: CGImage, _ path: String) {
    let d = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(d, img, nil); CGImageDestinationFinalize(d)
}

/// a random board-area patch of a background frame, rendered at s x s
func patch(_ bgs: [CGImage], _ s: Int, _ native: Int) -> CGImage {
    let bg = bgs[rint(0, bgs.count - 1)]
    let w = Double(bg.width), h = Double(bg.height)
    let side = Double(native) * w / 1280
    let r = CGRect(x: w * (0.2 + 0.55 * rnd()), y: h * (0.15 + 0.55 * rnd()), width: side, height: side)
    let ctx = context(s)
    ctx.interpolationQuality = .high
    if let c = bg.cropping(to: r) { ctx.draw(c, in: CGRect(x: 0, y: 0, width: s, height: s)) }
    return ctx.makeImage()!
}

/// one synthetic in-game sample: icon inside a dark frame, at a random on-screen size, then upscaled the
/// way a crop is before classification
func sample(_ icon: CGImage, _ bgs: [CGImage]) -> CGImage {
    // a third as the item bench draws them (HUD's left edge): bigger, in a gold frame, sometimes with a
    // yellow use-count badge top left; the rest as on a unit: small, dark frame
    let bench = rnd() < 0.33
    let s = bench ? rint(34, 50) : rint(15, 40)                // unit slots: 720p VOD ~17 px, Mac ~40 px
    let ctx = context(s)
    ctx.interpolationQuality = .high
    ctx.draw(patch(bgs, s, s), in: CGRect(x: 0, y: 0, width: s, height: s))
    let f = max(1, s / 16)
    ctx.setFillColor(bench ? CGColor(red: 0.70, green: 0.56, blue: 0.30, alpha: 1)
                           : CGColor(red: 0.06, green: 0.06, blue: 0.08, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: s, height: s))
    let m = Int(Double(icon.width) * 0.08)
    let core = icon.cropping(to: CGRect(x: m, y: m, width: icon.width - 2 * m, height: icon.height - 2 * m)) ?? icon
    let dx = Double(rint(-1, 1)), dy = Double(rint(-1, 1))     // crops are off by a pixel
    ctx.draw(core, in: CGRect(x: Double(f) + dx, y: Double(f) + dy, width: Double(s - 2 * f), height: Double(s - 2 * f)))
    if bench && rnd() < 0.4 {                                  // count badge: yellow box, dark digit
        let w = Double(s) * 0.32, top = Double(s) - Double(f)
        ctx.setFillColor(CGColor(red: 0.95, green: 0.78, blue: 0.2, alpha: 1))
        ctx.fill(CGRect(x: Double(f), y: top - w, width: w, height: w))
        ctx.setFillColor(CGColor(red: 0.15, green: 0.1, blue: 0.05, alpha: 1))
        ctx.fill(CGRect(x: Double(f) + w * 0.35, y: top - w * 0.8, width: w * 0.3, height: w * 0.6))
    }
    let b = (bench && rnd() < 0.2 ? 0.45 : 0.85) + 0.3 * rnd()  // brightness drift (the bench dims while dragging)
    ctx.setFillColor(CGColor(red: b > 1 ? 1 : 0, green: b > 1 ? 1 : 0, blue: b > 1 ? 1 : 0, alpha: abs(b - 1) * 0.6))
    ctx.fill(CGRect(x: 0, y: 0, width: s, height: s))
    return jpeg(ctx.makeImage()!)
}

let tdir = arg("--templates") ?? "data/raw/cdragon/items"
let bdir = arg("--backgrounds")!, out = arg("--out") ?? "data/models/items.mlmodel"
let per = Int(arg("--per") ?? "30") ?? 30
let fm = FileManager.default
let bgs = ((try? fm.contentsOfDirectory(atPath: bdir)) ?? []).sorted().compactMap { load(bdir + "/" + $0) }
guard !bgs.isEmpty else { fatalError("no background frames in \(bdir)") }
let idx = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: tdir + "/index.json"))) as! [[String: Any]]
// art per class: CommunityDragon icons, plus real tooltip crops (--extra, one folder per item) for items
// CommunityDragon lacks (Set 19 emblems) and for in-game rendering of the rest
var art: [String: [CGImage]] = [:]
for e in idx { if let icon = load(tdir + "/" + (e["file"] as! String)) { art[(e["name"] as! String), default: []].append(icon) } }
if let extra = arg("--extra") {
    for c in (try? fm.contentsOfDirectory(atPath: extra)) ?? [] {
        for f in (try? fm.contentsOfDirectory(atPath: extra + "/" + c)) ?? [] where f.hasSuffix(".png") {
            if let img = load("\(extra)/\(c)/\(f)") { art[c, default: []].append(img) }
        }
    }
}
let work = NSTemporaryDirectory() + "tft_items_\(getpid())"
try? fm.removeItem(atPath: work)
for (name, icons) in art {
    let d = work + "/" + name.replacingOccurrences(of: "/", with: "-")
    try fm.createDirectory(atPath: d, withIntermediateDirectories: true)
    for k in 0..<per { savePNG(sample(icons[k % icons.count], bgs), "\(d)/\(k).png") }
}
// "empty": real item slots verified to hold nothing (data/raw/labels/empty_slots: stage-1 units, reviewed), in
// compression and brightness variants. Random board patches are NOT used: boards are full of item icons.
try fm.createDirectory(atPath: work + "/empty", withIntermediateDirectories: true)
let edir = arg("--empties") ?? "data/raw/labels/empty_slots"
let empties = ((try? fm.contentsOfDirectory(atPath: edir)) ?? []).sorted().compactMap { load(edir + "/" + $0) }
guard !empties.isEmpty else { fatalError("no verified empty slots in \(edir)") }
for k in 0..<(per * 6) {
    let e = empties[k % empties.count], s = rint(15, 40)
    let ctx = context(s)
    ctx.interpolationQuality = .high
    ctx.draw(e, in: CGRect(x: 0, y: 0, width: s, height: s))
    let b = 0.85 + 0.3 * rnd()
    ctx.setFillColor(CGColor(red: b > 1 ? 1 : 0, green: b > 1 ? 1 : 0, blue: b > 1 ? 1 : 0, alpha: abs(b - 1) * 0.6))
    ctx.fill(CGRect(x: 0, y: 0, width: s, height: s))
    savePNG(jpeg(ctx.makeImage()!), "\(work)/empty/\(k).png")
}
print("training on \(art.count + 1) classes from \(work)")
let params = MLImageClassifier.ModelParameters(validation: .split(strategy: .automatic), maxIterations: 40)
let model = try MLImageClassifier(trainingData: .labeledDirectories(at: URL(fileURLWithPath: work)), parameters: params)
try fm.createDirectory(atPath: (out as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
try model.write(to: URL(fileURLWithPath: out))
print("train accuracy \(1 - model.trainingMetrics.classificationError), validation \(1 - model.validationMetrics.classificationError) -> \(out)")
try? fm.removeItem(atPath: work)
