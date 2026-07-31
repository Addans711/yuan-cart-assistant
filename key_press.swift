import Foundation
import CoreGraphics

let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 1 else {
    FileHandle.standardError.write("Usage: key_press <cmd-a|cmd-v|return>\n".data(using: .utf8)!)
    exit(2)
}

let source = CGEventSource(stateID: .combinedSessionState)

func postKey(_ keyCode: CGKeyCode, flags: CGEventFlags = []) -> Bool {
    guard let down = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: false) else {
        return false
    }
    down.flags = flags
    up.flags = flags
    down.post(tap: .cghidEventTap)
    usleep(80_000)
    up.post(tap: .cghidEventTap)
    return true
}

let ok: Bool
switch args[0] {
case "cmd-a":
    ok = postKey(0, flags: .maskCommand)
case "cmd-v":
    ok = postKey(9, flags: .maskCommand)
case "return":
    ok = postKey(36)
default:
    FileHandle.standardError.write("Unsupported key command\n".data(using: .utf8)!)
    exit(2)
}

if !ok {
    FileHandle.standardError.write("Could not create key event\n".data(using: .utf8)!)
    exit(1)
}
