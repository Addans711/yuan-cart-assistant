import Foundation
import CoreGraphics
import ImageIO

guard CommandLine.arguments.count >= 2 else {
    FileHandle.standardError.write("Usage: find_add_button <screenshot-path>\n".data(using: .utf8)!)
    exit(2)
}

let screenshotURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let imageSource = CGImageSourceCreateWithURL(screenshotURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    FileHandle.standardError.write("Could not open screenshot image\n".data(using: .utf8)!)
    exit(1)
}

var displayCount: UInt32 = 0
CGGetActiveDisplayList(0, nil, &displayCount)
var displays = [CGDirectDisplayID](repeating: 0, count: Int(displayCount))
CGGetActiveDisplayList(displayCount, &displays, &displayCount)
let display = displays.first ?? CGMainDisplayID()
let bounds = CGDisplayBounds(display)

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

@inline(__always)
func isGreen(_ px: Int, _ py: Int) -> Bool {
    let offset = py * bytesPerRow + px * bytesPerPixel
    let r = Int(pixels[offset])
    let g = Int(pixels[offset + 1])
    let b = Int(pixels[offset + 2])
    return g >= 95 && g > r + 35 && g > b + 15
}

var visited = [Bool](repeating: false, count: width * height)
let minY = max(0, Int(Double(height) * 0.12))
let maxY = min(height - 1, Int(Double(height) * 0.88))
let minX = max(0, Int(Double(width) * 0.35))

struct Candidate {
    let cx: Double
    let cy: Double
    let area: Int
    let minX: Int
    let minY: Int
    let maxX: Int
    let maxY: Int
    let density: Double
    let score: Double
}

var candidates: [Candidate] = []
let directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

for y in minY...maxY {
    for x in minX..<width {
        let index = y * width + x
        if visited[index] || !isGreen(x, y) {
            visited[index] = true
            continue
        }

        var queue = [(x, y)]
        var cursor = 0
        visited[index] = true
        var area = 0
        var sumX = 0
        var sumY = 0
        var boxMinX = x
        var boxMaxX = x
        var boxMinY = y
        var boxMaxY = y

        while cursor < queue.count {
            let (qx, qy) = queue[cursor]
            cursor += 1
            area += 1
            sumX += qx
            sumY += qy
            boxMinX = min(boxMinX, qx)
            boxMaxX = max(boxMaxX, qx)
            boxMinY = min(boxMinY, qy)
            boxMaxY = max(boxMaxY, qy)

            for (dx, dy) in directions {
                let nx = qx + dx
                let ny = qy + dy
                if nx < minX || nx >= width || ny < minY || ny > maxY {
                    continue
                }
                let nIndex = ny * width + nx
                if visited[nIndex] {
                    continue
                }
                visited[nIndex] = true
                if isGreen(nx, ny) {
                    queue.append((nx, ny))
                }
            }
        }

        let boxW = boxMaxX - boxMinX + 1
        let boxH = boxMaxY - boxMinY + 1
        let density = Double(area) / Double(max(1, boxW * boxH))
        let aspect = Double(boxW) / Double(max(1, boxH))

        if area >= 450 &&
            boxW >= 28 && boxW <= 150 &&
            boxH >= 28 && boxH <= 150 &&
            aspect >= 0.55 && aspect <= 1.8 &&
            density >= 0.32 {
            let cx = Double(sumX) / Double(area)
            let cy = Double(sumY) / Double(area)
            let score = Double(area) + cx * 0.1 - abs(Double(boxW - boxH)) * 4.0 - cy * 0.01
            candidates.append(Candidate(
                cx: cx,
                cy: cy,
                area: area,
                minX: boxMinX,
                minY: boxMinY,
                maxX: boxMaxX,
                maxY: boxMaxY,
                density: density,
                score: score
            ))
        }
    }
}

guard let best = candidates.sorted(by: { $0.score > $1.score }).first else {
    print("{\"found\":false}")
    exit(0)
}

let scaleX = Double(width) / Double(bounds.width)
let scaleY = Double(height) / Double(bounds.height)
let screenX = bounds.origin.x + best.cx / scaleX
let screenY = bounds.origin.y + best.cy / scaleY

print("{\"found\":true,\"x\":\(Int(screenX.rounded())),\"y\":\(Int(screenY.rounded())),\"area\":\(best.area),\"density\":\(String(format: "%.4f", best.density)),\"box\":[\(best.minX),\(best.minY),\(best.maxX),\(best.maxY)]}")
