import Foundation
import CoreGraphics

guard let event = CGEvent(source: nil) else {
    FileHandle.standardError.write("Could not read mouse location\n".data(using: .utf8)!)
    exit(1)
}

let location = event.location

print("{\"x\":\(Int(location.x)),\"y\":\(Int(location.y))}")
