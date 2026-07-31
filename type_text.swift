import Foundation
import CoreGraphics

let text = Array(CommandLine.arguments.dropFirst()).joined(separator: " ")
guard !text.isEmpty else {
    exit(0)
}

let source = CGEventSource(stateID: .combinedSessionState)

for scalar in text.unicodeScalars {
    var value = UniChar(scalar.value)
    guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else {
        FileHandle.standardError.write("Could not create text event\n".data(using: .utf8)!)
        exit(1)
    }
    down.keyboardSetUnicodeString(stringLength: 1, unicodeString: &value)
    up.keyboardSetUnicodeString(stringLength: 1, unicodeString: &value)
    down.post(tap: .cghidEventTap)
    usleep(20_000)
    up.post(tap: .cghidEventTap)
    usleep(20_000)
}
