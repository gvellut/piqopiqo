# PyQtAuto - Automation Skill for PySide6 Applications

This document describes how to use PyQtAuto to automate and test PySide6 applications. PyQtAuto works like Playwright for web browsers, but for Qt/PySide6 desktop applications.

## Quick Start

### 1. Add PyQtAuto as a Development Dependency

In your project's `pyproject.toml`, add pyqtauto as a local source dependency:

```toml
[project]
dependencies = [
    "pyside6>=6.5.0",
]

[tool.uv.sources]
pyqtauto = { path = "/Users/guilhem/Documents/projects/github/pyqtauto" }

[project.optional-dependencies]
dev = [
    "pyqtauto",
]
```

Then install the dev dependencies:

```bash
uv sync --extra dev
```

### 2. Enable the Server in Your Application

Add these two lines at the start of your PySide6 application:

```python
from pyqtauto.server import start_server

# Start server (checks PYQTAUTO_ENABLED env var)
start_server()

# Or force start for development
start_server(force=True)
```

Complete example:

```python
import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from pyqtauto.server import start_server

def main():
    app = QApplication(sys.argv)

    # Start automation server
    server = start_server(force=True)
    if server:
        print(f"PyQtAuto server on port {server.port}")

    window = QMainWindow()
    window.setObjectName("main_window")  # Important for selectors!
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

### 3. Write Automation Scripts

Create a Python script to automate your application:

```python
from pyqtauto import PyQtAutoClient

with PyQtAutoClient(port=9876) as client:
    # Wait for app to be ready
    client.wait_idle()

    # Click a button
    client.click("@name:submit_button")

    # Type text into an input
    client.type("@name:email_input", "test@example.com")

    # Take a screenshot
    client.screenshot_to_file("result.png")

    # Get widget text
    result = client.get_text("@name:status_label")
    print(f"Status: {result}")
```

#### Location of temprary files

Do not write automation scripts and save screenshots in the project folder (so does not pollute the workspace). Use a temp folder or pass the string as the script directly (instead of file).

## Widget Selectors

PyQtAuto uses selectors to find widgets. Always set `objectName` on your widgets:

```python
button = QPushButton("Click Me")
button.setObjectName("submit_btn")  # Now use "@name:submit_btn"
```

### Selector Types

| Selector | Example | Description |
|----------|---------|-------------|
| `@name:` | `@name:submit_btn` | Find by objectName (recommended) |
| `@class:` | `@class:QPushButton` | Find first widget of class |
| `@text:` | `@text:Submit` | Find by text content |
| Path | `main_window/form/button` | Hierarchical path |

## Common Actions

### Clicking

```python
client.click("@name:button")           # Left click
client.double_click("@name:item")      # Double click
client.right_click("@name:widget")     # Right click
```

### Typing

```python
client.type("@name:input", "Hello World")
client.type("@name:input", "text", clear_first=False)  # Append
```

### Keyboard

```python
client.key("@name:input", "Return")                    # Press Enter
client.key("@name:input", "A", modifiers=["ctrl"])     # Ctrl+A
client.key_sequence("@name:input", "Ctrl+S")           # Key sequence
```

### Setting Values (Smart Setter)

```python
client.set_value("@name:checkbox", True)      # Check/uncheck
client.set_value("@name:spinbox", 42)         # Set number
client.set_value("@name:combo", "Option 2")   # Select text
client.set_value("@name:combo", 1)            # Select index
client.set_value("@name:slider", 75)          # Set slider
```

### Reading Values

```python
text = client.get_text("@name:label")
value = client.get_property("@name:spinbox", "value")
props = client.list_properties("@name:widget")
```

### Verification

```python
client.exists("@name:widget")           # Returns True/False
client.is_visible("@name:widget")
client.is_enabled("@name:widget")

# Assert properties
assert client.assert_property("@name:label", "text", "==", "Success")
```

### Waiting

```python
client.wait("@name:button", "visible", timeout_ms=5000)
client.wait("@name:spinner", "not_visible")
client.wait("@name:checkbox", "property:checked=true")
client.wait_idle()
client.sleep(1000)  # Use sparingly
```

### Screenshots

```python
# Save to file
client.screenshot_to_file("screenshot.png")
client.screenshot_to_file("widget.png", target="@name:specific_widget")

# Get as bytes
image_bytes = client.screenshot_to_bytes()
```

### Widget Tree Exploration

```python
tree = client.get_tree()
print(tree)  # Full widget hierarchy

# Find multiple widgets
widgets = client.find("@class:QPushButton", max_results=10)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYQTAUTO_ENABLED` | - | Set to `1`, `true`, or `yes` to enable server |
| `PYQTAUTO_PORT` | `9876` | Server port |

## CLI Tool

PyQtAuto also provides a command-line tool:

```bash
# Get widget tree
pyqtauto tree

# Click a button
pyqtauto click "@name:submit_btn"

# Type text
pyqtauto type "@name:input" "Hello World"

# Take screenshot
pyqtauto screenshot output.png

# Interactive shell
pyqtauto shell
```

## Best Practices for Testable Applications

1. **Always set objectName**: Every widget you want to automate should have a unique `objectName`:
   ```python
   widget.setObjectName("unique_name")
   ```

2. **Use meaningful names**: Choose descriptive names like `login_button`, `email_input`, `status_label`.

3. **Wait for conditions**: Use `wait()` instead of `sleep()`:
   ```python
   # Good
   client.wait("@name:result", "visible")

   # Avoid
   client.sleep(1000)
   ```

4. **Take screenshots for verification**: Especially useful for AI agents:
   ```python
   client.click("@name:submit")
   client.wait_idle()
   client.screenshot_to_file("after_submit.png")
   ```

5. **Handle async operations**: Use `wait_idle()` after actions that trigger processing:
   ```python
   client.click("@name:load_data")
   client.wait_idle()  # Wait for event queue to empty
   ```

## Example: Full Test Script

```python
#!/usr/bin/env python3
"""Test script for MyApp."""

from pathlib import Path
from pyqtauto import PyQtAutoClient

def test_login():
    screenshots = Path("test_screenshots")
    screenshots.mkdir(exist_ok=True)

    with PyQtAutoClient() as client:
        # Initial state
        client.wait_idle()
        client.screenshot_to_file(screenshots / "01_initial.png")

        # Fill login form
        client.type("@name:username_input", "testuser")
        client.type("@name:password_input", "password123")
        client.screenshot_to_file(screenshots / "02_filled.png")

        # Submit
        client.click("@name:login_button")

        # Wait for result
        client.wait("@name:dashboard", "visible", timeout_ms=5000)
        client.screenshot_to_file(screenshots / "03_logged_in.png")

        # Verify
        welcome = client.get_text("@name:welcome_label")
        assert "testuser" in welcome

        print("Login test passed!")

if __name__ == "__main__":
    test_login()
```

## Error Handling

```python
from pyqtauto import PyQtAutoClient, CommandError, ConnectionError

try:
    with PyQtAutoClient() as client:
        client.click("@name:nonexistent")
except ConnectionError as e:
    print(f"Could not connect: {e.message}")
except CommandError as e:
    print(f"Command failed [{e.code}]: {e.message}")
```

## Typical AI Agent Workflow

For AI agents testing applications:

1. **Explore**: Get the widget tree to understand the UI
2. **Plan**: Identify the widgets to interact with
3. **Act**: Perform actions (click, type, etc.)
4. **Verify**: Take screenshots and check widget states
5. **Iterate**: Repeat based on screenshot analysis

```python
# AI agent example
with PyQtAutoClient() as client:
    # 1. Explore
    tree = client.get_tree()
    # AI analyzes tree...

    # 2. Act based on analysis
    client.type("@name:search_input", "query")
    client.click("@name:search_button")
    client.wait_idle()

    # 3. Verify with screenshot
    client.screenshot_to_file("result.png")
    # AI analyzes screenshot...

    # 4. Continue based on what AI sees
    result_text = client.get_text("@name:result_label")
    # AI decides next steps...
```
