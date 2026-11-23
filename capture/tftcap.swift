// tftcap: read-only screen capture + OCR for the TFT window, using Apple frameworks only.
//
//   swiftc -O -parse-as-library capture/tftcap.swift capture/units.swift -o capture/tftcap
//   capture/tftcap windows                 list on-screen windows (app, title, size)
//   capture/tftcap shot out.png [app]      capture one window; default: first app matching TFT/League
//   capture/tftcap read [save.jpg] [--window TEXT]
//                                          capture the TFT window (or the first window whose app name or title
//                                          contains TEXT, e.g. a browser playing a VOD) and print its OCR;
//                                          exit 2 if no such window
//   capture/tftcap ocr in.png [--area x0,y0,x1,y1]
//                                          recognised text, one JSON object per line:
//                                          {"text","conf","x","y","w","h"}, fractions of the image, origin top-left
//   capture/tftcap vod video.mp4 [--every 2] [--area x0,y0,x1,y1] [--jpeg-dir DIR --jpeg-every 60] [--units --model M]
//                                          sample a video file; one line per frame: {"t": seconds, "rows": [...]}
//                                          (+ "units": health bars and items, see units.swift)
//   capture/tftcap units frame.png [--items DIR] [--dump DIR]
//                                          your units' health bars and the items under them (see units.swift)
//   capture/tftcap fprint a.png b.png ...  image fingerprints for grouping look-alike crops
//
// Saving: .jpg/.jpeg paths are written as JPEG (quality 0.6, at most 1280 px wide) to save space; .png as is.
// --area crops a fixed part of the frame first (fractions), for stream layouts where the game is boxed in.
//
// Capture needs Screen Recording permission for the app running it (System Settings > Privacy & Security).
// Nothing here touches the game process: it reads pixels the screen already shows.
import AVFoundation
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers
import Vision

let defaultApps = ["teamfight", "tft", "league of legends"]

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

func load(_ path: String) -> CGImage {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("cannot read image \(path)") }
    return img
}

func save(_ img: CGImage, _ path: String) {
    let jpeg = path.lowercased().hasSuffix(".jpg") || path.lowercased().hasSuffix(".jpeg")
    var out = img
    if jpeg && img.width > 1280 {                       // small JPEGs: enough to re-read the HUD later
        let h = img.height * 1280 / img.width
        if let ctx = CGContext(data: nil, width: 1280, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                               space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) {
            ctx.interpolationQuality = .high
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: 1280, height: h))
            out = ctx.makeImage() ?? img
        }
    }
    let type = (jpeg ? UTType.jpeg : UTType.png).identifier as CFString
    guard let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, type, 1, nil) else { fail("cannot write \(path)") }
    CGImageDestinationAddImage(dest, out, jpeg ? [kCGImageDestinationLossyCompressionQuality: 0.6] as CFDictionary : nil)
    if !CGImageDestinationFinalize(dest) { fail("cannot write \(path)") }
}

/// Crop to a fixed area given as fractions "x0,y0,x1,y1" (top-left origin).
func cropArea(_ img: CGImage, _ spec: String?) -> CGImage {
    guard let spec = spec else { return img }
    let f = spec.split(separator: ",").compactMap { Double($0) }
    guard f.count == 4, f[2] > f[0], f[3] > f[1] else { fail("--area wants x0,y0,x1,y1 as fractions") }
    let w = Double(img.width), h = Double(img.height)
    return img.cropping(to: CGRect(x: f[0] * w, y: f[1] * h, width: (f[2] - f[0]) * w, height: (f[3] - f[1]) * h)) ?? img
}

func option(_ name: String) -> String? {
    let a = CommandLine.arguments
    guard let i = a.firstIndex(of: name), i + 1 < a.count else { return nil }
    return a[i + 1]
}

/// Drop black letterbox bars (video frames, VODs) so HUD positions are fractions of the game area.
func cropBorders(_ img: CGImage) -> CGImage {
    let w = img.width, h = img.height
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue),
          let _ = Optional(ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))),
          let px = ctx.data?.assumingMemoryBound(to: UInt8.self) else { return img }
    func bright(_ x: Int, _ y: Int) -> Int { let i = (y * w + x) * 4; return Int(px[i]) + Int(px[i + 1]) + Int(px[i + 2]) }
    func darkRow(_ y: Int) -> Bool { stride(from: 0, to: w, by: 8).allSatisfy { bright($0, y) < 60 } }
    func darkCol(_ x: Int) -> Bool { stride(from: 0, to: h, by: 8).allSatisfy { bright(x, $0) < 60 } }
    var top = 0, bottom = h - 1, left = 0, right = w - 1
    while top < h / 3 && darkRow(top) { top += 1 }
    while bottom > 2 * h / 3 && darkRow(bottom) { bottom -= 1 }
    while left < w / 3 && darkCol(left) { left += 1 }
    while right > 2 * w / 3 && darkCol(right) { right -= 1 }
    if top + (h - 1 - bottom) + left + (w - 1 - right) < 8 { return img }   // no bars
    return img.cropping(to: CGRect(x: left, y: top, width: right - left + 1, height: bottom - top + 1)) ?? img
}

func recognise(_ img: CGImage) throws -> [[String: Any]] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false        // HUD text is numbers and names, not prose
    try VNImageRequestHandler(cgImage: img).perform([req])
    return (req.results ?? []).compactMap { obs in
        guard let c = obs.topCandidates(1).first else { return nil }
        let b = obs.boundingBox                 // normalised, origin bottom-left
        return ["text": c.string, "conf": Double(c.confidence),
                "x": Double(b.minX), "y": Double(1 - b.maxY), "w": Double(b.width), "h": Double(b.height)]
    }
}

/// Small HUD numbers read again from an enlarged crop: a lone thin digit ("1" gold) is often missed at
/// frame scale. Fractions of a full-screen game; harmless extra rows when the game is boxed in a stream.
let ZOOM_REGIONS: [(Double, Double, Double, Double)] = [(0.46, 0.75, 0.61, 0.88),     // gold, with room for UI scale
                                                        (0.035, 0.20, 0.075, 0.78),    // trait counts (single digits)
                                                        (0.935, 0.15, 0.975, 0.80)]    // other players' HP (late game: 0-21)
let ZOOM = 3

func zoomRows(_ img: CGImage) throws -> [[String: Any]] {
    var out: [[String: Any]] = []
    let W = Double(img.width), H = Double(img.height)
    for (x0, y0, x1, y1) in ZOOM_REGIONS {
        guard let crop = img.cropping(to: CGRect(x: x0 * W, y: y0 * H, width: (x1 - x0) * W, height: (y1 - y0) * H)) else { continue }
        let w = crop.width * ZOOM, h = crop.height * ZOOM
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
        ctx.interpolationQuality = .high
        ctx.draw(crop, in: CGRect(x: 0, y: 0, width: w, height: h))
        guard let big = ctx.makeImage() else { continue }
        for var r in try recognise(big) {                 // back to frame fractions
            r["x"] = x0 + (r["x"] as! Double) * (x1 - x0); r["w"] = (r["w"] as! Double) * (x1 - x0)
            r["y"] = y0 + (r["y"] as! Double) * (y1 - y0); r["h"] = (r["h"] as! Double) * (y1 - y0)
            r["zoom"] = true
            out.append(r)
        }
    }
    return out
}

func ocrRows(_ raw: CGImage) throws -> [[String: Any]] {
    let img = cropBorders(cropArea(raw, option("--area")))
    return try recognise(img) + (try zoomRows(img))
}

func json(_ o: Any) throws -> String {
    String(data: try JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]), encoding: .utf8)!
}

func ocr(_ raw: CGImage) throws {
    for row in try ocrRows(raw) { print(try json(row)) }
}

/// Sample a video every `every` seconds: OCR each frame, optionally keep a small JPEG now and then.
func vod(_ path: String) async throws {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    let gen = AVAssetImageGenerator(asset: asset)
    gen.appliesPreferredTrackTransform = true
    gen.requestedTimeToleranceBefore = CMTime(seconds: 0.5, preferredTimescale: 600)
    gen.requestedTimeToleranceAfter = CMTime(seconds: 0.5, preferredTimescale: 600)
    let duration = try await asset.load(.duration).seconds
    guard duration.isFinite, duration > 0 else { fail("cannot read video \(path)") }
    let every = Double(option("--every") ?? "2") ?? 2
    let jpegDir = option("--jpeg-dir"), jpegEvery = Double(option("--jpeg-every") ?? "60") ?? 60
    var t = 0.0, lastJpeg = -Double.infinity
    while t < duration {
        if let (img, _) = try? await gen.image(at: CMTime(seconds: t, preferredTimescale: 600)) {
            if let dir = jpegDir, t - lastJpeg >= jpegEvery {
                save(img, "\(dir)/\(Int(t)).jpg")
                lastJpeg = t
            }
            let skipText = CommandLine.arguments.contains("--no-ocr")      // units only (re-reading items)
            var line: [String: Any] = ["t": t, "rows": skipText ? [] : try ocrRows(img)]
            if CommandLine.arguments.contains("--units") {
                let game = cropBorders(cropArea(img, option("--area")))
                line["units"] = unitRows(game)
                line["held"] = heldItems(game)
            }
            print(try json(line))
            fflush(stdout)
        }
        t += every
    }
}

func windows() async throws -> [SCWindow] {
    do {
        return try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true).windows
    } catch {
        fail("no window list: grant Screen Recording permission to this terminal app, then retry (\(error.localizedDescription))")
    }
}

/// Capture the first sizeable window of an app matching `wanted`. Exits 2 when there is none (game closed).
func grab(_ wanted: [String]) async throws -> (CGImage, String) {
    guard let win = try await windows().first(where: { w in
        let app = (w.owningApplication?.applicationName ?? "").lowercased()
        let title = (w.title ?? "").lowercased()          // e.g. a browser tab titled "... - YouTube"
        return w.frame.width > 400 && wanted.contains(where: { app.contains($0) || title.contains($0) })
    }) else {
        FileHandle.standardError.write("no window from an app matching \(wanted); see `tftcap windows`\n".data(using: .utf8)!)
        exit(2)
    }
    let filter = SCContentFilter(desktopIndependentWindow: win)
    let cfg = SCStreamConfiguration()
    cfg.width = Int(win.frame.width * CGFloat(filter.pointPixelScale))
    cfg.height = Int(win.frame.height * CGFloat(filter.pointPixelScale))
    cfg.showsCursor = false
    let img = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
    return (img, win.owningApplication?.applicationName ?? "?")
}

@main
struct TFTCap {
    static func main() async throws {
        _ = CGMainDisplayID()             // opens the window-server connection a CLI needs before capturing
        let args = CommandLine.arguments
        switch args.count > 1 ? args[1] : "" {
        case "windows":
            for w in try await windows() where w.frame.width > 200 {
                print("\(w.owningApplication?.applicationName ?? "?")\t\(w.title ?? "")\t\(Int(w.frame.width))x\(Int(w.frame.height))")
            }
        case "shot" where args.count >= 3:
            let (img, app) = try await grab(args.count >= 4 ? [args[3].lowercased()] : defaultApps)
            save(img, args[2])
            print("\(app) \(img.width)x\(img.height) -> \(args[2])")
        case "read":
            let (img, _) = try await grab(option("--window").map { [$0.lowercased()] } ?? defaultApps)
            if args.count >= 3 && !args[2].hasPrefix("--") { save(img, args[2]) }
            try ocr(img)
        case "ocr" where args.count >= 3:
            try ocr(load(args[2]))
        case "vod" where args.count >= 3:
            try await vod(args[2])
        case "units" where args.count >= 3:
            try units(args[2])
        case "held" where args.count >= 3:
            try held(args[2])
        case "fprint" where args.count >= 3:
            try fprints(Array(args.dropFirst(2)))
        default:
            fail("usage: tftcap windows | shot out.png [app] | read [save.jpg] | ocr in.png [--area ...] | vod video [--every s] [--area ...] [--jpeg-dir d]")
        }
    }
}
