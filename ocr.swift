import Foundation
import Vision
import AppKit
import ImageIO

struct TextLine: Encodable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

guard CommandLine.arguments.count >= 2 else {
    fail("Usage: ocr <image-path>")
}

let imagePath = CommandLine.arguments[1]
let imageURL = URL(fileURLWithPath: imagePath)
guard let imageSource = CGImageSourceCreateWithURL(imageURL as CFURL, nil) else {
    fail("Could not open image: \(imagePath)")
}

guard let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    fail("Could not decode image: \(imagePath)")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.minimumTextHeight = 0.008

let supportedLanguages = (try? request.supportedRecognitionLanguages()) ?? []
let preferredLanguages = ["zh-Hans", "zh-Hant", "en-US"].filter { supportedLanguages.contains($0) }
if !preferredLanguages.isEmpty {
    request.recognitionLanguages = preferredLanguages
}

let handler = VNImageRequestHandler(cgImage: cgImage, orientation: .up, options: [:])

do {
    try handler.perform([request])
} catch {
    fail("OCR failed: \(error.localizedDescription)")
}

let observations = request.results ?? []
let lines: [TextLine] = observations.compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else {
        return nil
    }
    let box = observation.boundingBox
    return TextLine(
        text: candidate.string,
        confidence: candidate.confidence,
        x: Double(box.origin.x),
        y: Double(box.origin.y),
        width: Double(box.size.width),
        height: Double(box.size.height)
    )
}

let sortedLines = lines.sorted {
    let rowDelta = abs($0.y - $1.y)
    if rowDelta > 0.018 {
        return $0.y > $1.y
    }
    return $0.x < $1.x
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

do {
    let data = try encoder.encode(sortedLines)
    FileHandle.standardOutput.write(data)
} catch {
    fail("Could not encode OCR result: \(error.localizedDescription)")
}
