import SwiftUI

@main
struct PodcastSyncApp: App {
    @StateObject private var backend = BackendProcess()

    var body: some Scene {
        MenuBarExtra("PodcastSync", systemImage: backend.statusIcon) {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Circle()
                        .fill(backend.statusColor)
                        .frame(width: 8, height: 8)
                    Text(backend.statusText)
                        .font(.headline)
                }

                Divider()

                Button("Open Web UI") {
                    if let url = URL(string: "http://127.0.0.1:\(backend.port)") {
                        NSWorkspace.shared.open(url)
                    }
                }
                .disabled(!backend.isRunning)
                .keyboardShortcut("o")

                Button("Sync All Now") {
                    backend.triggerSyncAll()
                }
                .disabled(!backend.isRunning)
                .keyboardShortcut("s")

                Divider()

                if backend.isRunning {
                    Button("Stop Server") {
                        backend.stop()
                    }
                } else {
                    Button("Start Server") {
                        backend.start()
                    }
                }

                Divider()

                Button("Quit PodcastSync") {
                    backend.stop()
                    // Brief delay to let the process terminate
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        NSApp.terminate(nil)
                    }
                }
                .keyboardShortcut("q")
            }
            .padding(4)
        }
    }
}
