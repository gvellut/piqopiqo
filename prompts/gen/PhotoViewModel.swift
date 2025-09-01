import Foundation

// A view model for a single photo in your grid
@MainActor // Ensure UI updates happen on the main thread
class PhotoViewModel: ObservableObject {
    let originalPath: String
    @Published var thumbnailImage: NSImage?
    @Published var isLoading = false

    private let coreEngine: CoreEngine // The Rust object

    init(path: String, engine: CoreEngine) {
        self.originalPath = path
        self.coreEngine = engine
        self.thumbnailImage = NSImage(named: "placeholder") // Start with a placeholder
    }

    func loadThumbnail() {
        guard !isLoading else { return }
        isLoading = true

        // This is where the magic happens!
        // We call the Rust function as if it were native Swift async code.
        Task {
            do {
                let result = try await coreEngine.generateThumbnail(imagePath: self.originalPath)
                
                // Result is back, load the image from the path Rust gave us
                // and update the UI. The @Published property will refresh the view.
                self.thumbnailImage = NSImage(contentsOfFile: result.thumbnailPath)
                self.isLoading = false
            } catch {
                print("Error generating thumbnail: \(error)")
                self.thumbnailImage = NSImage(named: "error_icon") // Show an error state
                self.isLoading = false
            }
        }
    }
}