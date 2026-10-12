import Foundation
import Vision
import ImageIO

// Files are supplied explicitly by our local import endpoint. No screen capture.
do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "OCR", code: 1) }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(url: url, options: [:]).perform([request])
    let rows: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let best = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": best.string, "confidence": best.confidence,
                "box": [b.minX, 1 - b.maxY, b.width, b.height]]
    }
    let data = try JSONSerialization.data(withJSONObject: rows)
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data("本地文字识别失败（\((error as NSError).domain):\((error as NSError).code)），请使用清晰的 PNG 或 JPEG 截图。\n".utf8))
    exit(1)
}
