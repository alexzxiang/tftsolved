// Train the champion recogniser from labelled unit crops (data/raw/labels/units/<Champion>/*.png, built by
// tools/label_units.py), Apple CreateML transfer learning, on-device. Optionally test on held-out folders.
// Measured 2026-11-19 on two labelled games: within a game ~100%, but trained on one game and tested on the
// other only 49% (20-30% with the bar/items cropped off). Parked until Set 19 art or many more games exist.
//
//   swiftc -O tools/train_units.swift -o /tmp/train_units
//   /tmp/train_units --labels data/raw/labels/units --out data/models/units.mlmodel [--exclude TEXT] [--only TEXT]
//       --exclude/--only: leave out / keep only crops whose file name contains TEXT (e.g. one game, to test
//       on another); with --test DIR the trained model is scored on DIR (same folder layout).
import CreateML
import Foundation

func arg(_ n: String) -> String? { let a = CommandLine.arguments; guard let i = a.firstIndex(of: n), i + 1 < a.count else { return nil }; return a[i + 1] }

let labels = arg("--labels") ?? "data/raw/labels/units"
let out = arg("--out") ?? "data/models/units.mlmodel"
let fm = FileManager.default

/// Copy the labelled crops (filtered) into a temporary folder tree CreateML can read.
func stage(_ dir: String, keep: (String) -> Bool) throws -> URL {
    let work = URL(fileURLWithPath: NSTemporaryDirectory() + "tft_units_\(UUID().uuidString)")
    for c in try fm.contentsOfDirectory(atPath: dir) {
        let files = ((try? fm.contentsOfDirectory(atPath: "\(dir)/\(c)")) ?? []).filter { $0.hasSuffix(".png") && keep($0) }
        guard !files.isEmpty else { continue }
        let d = work.appendingPathComponent(c)
        try fm.createDirectory(at: d, withIntermediateDirectories: true)
        for f in files { try fm.copyItem(atPath: "\(dir)/\(c)/\(f)", toPath: d.appendingPathComponent(f).path) }
    }
    return work
}

let exclude = arg("--exclude"), only = arg("--only")
let train = try stage(labels) { f in (exclude.map { !f.contains($0) } ?? true) && (only.map { f.contains($0) } ?? true) }
let classes = try fm.contentsOfDirectory(atPath: train.path).filter { !$0.hasPrefix(".") }
print("training on \(classes.count) champions")
let params = MLImageClassifier.ModelParameters(validation: .split(strategy: .automatic), maxIterations: 60,
                                               augmentation: [.crop, .exposure, .blur])
let model = try MLImageClassifier(trainingData: .labeledDirectories(at: train), parameters: params)
try fm.createDirectory(atPath: (out as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
try model.write(to: URL(fileURLWithPath: out))
print("train accuracy \(1 - model.trainingMetrics.classificationError), validation \(1 - model.validationMetrics.classificationError) -> \(out)")
if let test = arg("--test") {
    let held = try stage(test) { f in only.map { !f.contains($0) } ?? (exclude.map { f.contains($0) } ?? true) }
    let known = Set(classes)
    for c in try fm.contentsOfDirectory(atPath: held.path) where !known.contains(c) {   // can't be right on unseen champions
        try fm.removeItem(at: held.appendingPathComponent(c))
    }
    let m = try model.evaluation(on: .labeledDirectories(at: held))
    print("held-out accuracy \(1 - m.classificationError) on champions it was trained on")
    try? fm.removeItem(at: held)
}
try? fm.removeItem(at: train)
