import AppKit
import UniffiBindings

class GridItem: NSCollectionViewItem {
    // MARK: - UI Components
    private var containerBox: NSBox!
    private var numberField: NSTextField!
    private var itemTextField: NSTextField!

    override func loadView() {
        view = NSView()
        setupUI()
    }

    private func setupUI() {
        // Create the gray background box
        containerBox = NSBox()
        containerBox.boxType = .custom
        containerBox.isTransparent = false
        containerBox.fillColor = NSColor.controlBackgroundColor
        containerBox.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(containerBox)

        // Create the number field (larger font)
        numberField = NSTextField()
        numberField.isEditable = false
        numberField.isBordered = false
        numberField.backgroundColor = NSColor.clear
        numberField.font = NSFont.systemFont(ofSize: 24, weight: .bold)
        numberField.alignment = .center
        numberField.translatesAutoresizingMaskIntoConstraints = false
        containerBox.addSubview(numberField)

        // Create the text field (smaller font, truncates with ellipsis)
        itemTextField = NSTextField()
        itemTextField.isEditable = false
        itemTextField.isBordered = false
        itemTextField.backgroundColor = NSColor.clear
        itemTextField.font = NSFont.systemFont(ofSize: 12, weight: .regular)
        itemTextField.alignment = .center
        itemTextField.lineBreakMode = .byTruncatingTail
        itemTextField.translatesAutoresizingMaskIntoConstraints = false
        containerBox.addSubview(itemTextField)

        setupConstraints()
    }

    private func setupConstraints() {
        NSLayoutConstraint.activate([
            // Container box fills the entire view
            containerBox.topAnchor.constraint(equalTo: view.topAnchor),
            containerBox.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            containerBox.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            containerBox.bottomAnchor.constraint(equalTo: view.bottomAnchor),

            // Number field positioned in upper portion
            numberField.topAnchor.constraint(equalTo: containerBox.topAnchor, constant: 20),
            numberField.leadingAnchor.constraint(equalTo: containerBox.leadingAnchor, constant: 8),
            numberField.trailingAnchor.constraint(
                equalTo: containerBox.trailingAnchor, constant: -8),

            // Text field positioned in lower portion
            itemTextField.topAnchor.constraint(equalTo: numberField.bottomAnchor, constant: 8),
            itemTextField.leadingAnchor.constraint(
                equalTo: containerBox.leadingAnchor, constant: 8),
            itemTextField.trailingAnchor.constraint(
                equalTo: containerBox.trailingAnchor, constant: -8),
            itemTextField.bottomAnchor.constraint(
                lessThanOrEqualTo: containerBox.bottomAnchor, constant: -8),
        ])
    }

    // MARK: - Configuration
    func configure(with item: Item) {
        numberField.stringValue = String(item.id)
        itemTextField.stringValue = item.text
    }
}
