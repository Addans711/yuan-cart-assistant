import Foundation
import CoreGraphics

guard CommandLine.arguments.count == 3,
      let x = Double(CommandLine.arguments[1]),
      let y = Double(CommandLine.arguments[2]) else {
    FileHandle.standardError.write("Usage: mouse_move <x> <y>\n".data(using: .utf8)!)
    exit(2)
}

let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .combinedSessionState)

guard let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) else {
    FileHandle.standardError.write("Could not create mouse move event\n".data(using: .utf8)!)
    exit(1)
}

move.post(tap: .cghidEventTap)
