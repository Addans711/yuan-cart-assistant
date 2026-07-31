import Foundation
import CoreGraphics
import ImageIO

guard CommandLine.arguments.count >= 4,
      let x = Double(CommandLine.arguments[1]),
      let y = Double(CommandLine.arguments[2]) else {
    FileHandle.standardError.write("Usage: button_state <x> <y> <screenshot-path> [radius]\n".data(using: .utf8)!)
    exit(2)
}

let screenshotPath = CommandLine.arguments[3]
let radius = Int(CommandLine.arguments.count >= 5 ? (Double(CommandLine.arguments[4]) ?? 26) : 26)
let point = CGPoint(x: x, y: y)

var displayCount: UInt32 = 0
CGGetActiveDisplayList(0, nil, &displayCount)
var displays = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
CGGetActiveDisplayList(displayCount, &displays, &displayCount)

guard let display = displays.first(where: { displayID in
    CGDisplayBounds(displayID).contains(point)
}) ?? displays.first else {
    FileHandle.standardError.write("Could not find active display\n".data(using: .utf8)!)
    exit(1)
}

let bounds = CGDisplayBounds(display)
let screenshotURL = URL(fileURLWithPath: screenshotPath)
guard let imageSource = CGImageSourceCreateWithURL(screenshotURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    FileHandle.standardError.write("Could not open screenshot image\n".data(using: .utf8)!)
    exit(1)
}

let width = image.width
let height = image.height
let bytesPerPixel = 4
let bytesPerRow = width * bytesPerPixel
var pixels = [UInt8](repeating: 0, count: Int(height * bytesPerRow))

guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
      let context = CGContext(
        data: &pixels,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
      ) else {
    FileHandle.standardError.write("Could not create bitmap context\n".data(using: .utf8)!)
    exit(1)
}

context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))

let scaleX = Double(width) / Double(bounds.width)
let scaleY = Double(height) / Double(bounds.height)
let centerX = Int((point.x - bounds.origin.x) * scaleX)
let centerY = Int((point.y - bounds.origin.y) * scaleY)
let scaledRadius = max(8, Int(Double(radius) * max(scaleX, scaleY)))

var total = 0
var green = 0
var white = 0

for py in max(0, centerY - scaledRadius)..<min(height, centerY + scaledRadius + 1) {
    for px in max(0, centerX - scaledRadius)..<min(width, centerX + scaledRadius + 1) {
        let dx = px - centerX
        let dy = py - centerY
        if dx * dx + dy * dy > scaledRadius * scaledRadius {
            continue
        }
        let offset = py * bytesPerRow + px * bytesPerPixel
        let r = Int(pixels[offset])
        let g = Int(pixels[offset + 1])
        let b = Int(pixels[offset + 2])
        total += 1
        if g >= 90 && g > r + 35 && g > b + 15 {
            green += 1
        }
        if r >= 220 && g >= 220 && b >= 220 {
            white += 1
        }
    }
}

let greenRatio = total > 0 ? Double(green) / Double(total) : 0
let whiteRatio = total > 0 ? Double(white) / Double(total) : 0
let addable = greenRatio >= 0.28 && whiteRatio <= 0.55

print("{\"green_ratio\":\(String(format: "%.4f", greenRatio)),\"white_ratio\":\(String(format: "%.4f", whiteRatio)),\"addable\":\(addable ? "true" : "false")}")
