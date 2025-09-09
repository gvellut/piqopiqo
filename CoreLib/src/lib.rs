//! Core library exposing uniffi bindings for Swift interop.

use std::sync::Arc;

/// Represents an individual item in the application.
#[derive(uniffi::Record, Clone, Debug, PartialEq)]
pub struct Item {
    pub id: u32,
    pub text: String,
}

/// Configuration settings for the application.
#[derive(uniffi::Record, Clone, Debug, PartialEq)]
pub struct Config {
    pub num_columns: u32,
}

/// Main state container for the application.
#[derive(uniffi::Object)]
pub struct Core {
    items: Vec<Item>,
    config: Config,
}

#[uniffi::export]
impl Core {
    /// Creates a new Core instance.
    #[uniffi::constructor]
    pub fn new() -> Arc<Core> {
        Arc::new(Core::default())
    }

    /// Gets the current configuration.
    pub fn get_config(&self) -> Config {
        self.config.clone()
    }

    /// Gets all items.
    pub fn get_items(&self) -> Vec<Item> {
        self.items.clone()
    }

    /// Gets the number of items.
    pub fn get_items_count(&self) -> u32 {
        self.items.len() as u32
    }
}

impl Core {
    /// Internal method used for testing.
    /// For external use, use the uniffi constructor Core::new().
    #[cfg(test)]
    fn new_for_test() -> Self {
        Self::default()
    }
}

impl Default for Core {
    fn default() -> Self {
        let config = Config { num_columns: 5 };

        let items = (1..=100)
            .map(|id| Item {
                id,
                text: format!("Item #{}", id),
            })
            .collect();

        Core { items, config }
    }
}

/// Returns a greeting message from Rust.
/// This function is exposed via uniffi and can be called from Swift.
pub fn hello_from_rust() -> String {
    "Hello from Rust!".to_string()
}

// Include the generated uniffi bindings
uniffi::include_scaffolding!("core_lib");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_core_initialization() {
        let core = Core::new_for_test();

        // Assert that core.config.num_columns is equal to 5
        assert_eq!(core.config.num_columns, 5);

        // Assert that core.items.len() is equal to 100
        assert_eq!(core.items.len(), 100);

        // Assert that core.items[0].id is 1 and core.items[0].text is "Item #1"
        assert_eq!(core.items[0].id, 1);
        assert_eq!(core.items[0].text, "Item #1");

        // Assert that core.items[99].id is 100 and core.items[99].text is "Item #100"
        assert_eq!(core.items[99].id, 100);
        assert_eq!(core.items[99].text, "Item #100");
    }

    #[test]
    fn test_core_arc_constructor() {
        let core_arc = Core::new();

        // Test that we can access the core through Arc
        assert_eq!(core_arc.get_config().num_columns, 5);
        assert_eq!(core_arc.get_items_count(), 100);

        let items = core_arc.get_items();
        assert_eq!(items[0].id, 1);
        assert_eq!(items[0].text, "Item #1");
        assert_eq!(items[99].id, 100);
        assert_eq!(items[99].text, "Item #100");
    }
}
