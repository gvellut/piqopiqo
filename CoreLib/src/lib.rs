//! Core library exposing uniffi bindings for Swift interop.

use std::sync::{Arc, Mutex};

/// Represents an individual item in the application.
#[derive(Clone, Debug, PartialEq)]
pub struct Item {
    pub id: u32,
    pub text: String,
}

/// Configuration settings for the application.
#[derive(Clone, Debug, PartialEq)]
pub struct Config {
    pub num_columns: u32,
}

/// Main state container for the application.
pub struct Core {
    items: Vec<Item>,
    config: Mutex<Config>,
}

impl Core {
    /// Creates a new Core instance.
    pub fn new() -> Arc<Core> {
        Arc::new(Core::default())
    }

    /// Gets the current configuration.
    pub fn get_config(&self) -> Config {
        self.config.lock().unwrap().clone()
    }

    /// Gets the total number of items.
    pub fn get_total_item_count(&self) -> u32 {
        self.items.len() as u32
    }

    /// Gets a subset of items by index range.
    /// Returns a slice of items starting from `start` with up to `count` items.
    /// Handles out-of-bounds requests gracefully by returning a smaller or empty vector.
    pub fn get_items(&self, start: u32, count: u32) -> Vec<Item> {
        let start_idx = start as usize;
        let total_items = self.items.len();

        // If start is beyond the total items, return empty vector
        if start_idx >= total_items {
            return Vec::new();
        }

        // Calculate the actual end index, ensuring we don't go beyond the available items
        let end_idx = std::cmp::min(start_idx + count as usize, total_items);

        // Return the slice as a new vector
        self.items[start_idx..end_idx].to_vec()
    }

    /// Increases the number of columns by 1, up to a maximum of 20.
    pub fn increase_columns(&self) {
        let mut config = self.config.lock().unwrap();
        if config.num_columns < 20 {
            config.num_columns += 1;
        }
    }

    /// Decreases the number of columns by 1, down to a minimum of 1.
    pub fn decrease_columns(&self) {
        let mut config = self.config.lock().unwrap();
        if config.num_columns > 1 {
            config.num_columns -= 1;
        }
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
        let config = Mutex::new(Config { num_columns: 5 });

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

/// Creates a new Core instance.
/// This function is exposed via uniffi and can be called from Swift.
pub fn core_new() -> Arc<Core> {
    Arc::new(Core::default())
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
        assert_eq!(core.config.lock().unwrap().num_columns, 5);

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
        assert_eq!(core_arc.get_total_item_count(), 100);

        let items = core_arc.get_items(0, 100);
        assert_eq!(items[0].id, 1);
        assert_eq!(items[0].text, "Item #1");
        assert_eq!(items[99].id, 100);
        assert_eq!(items[99].text, "Item #100");
    }

    #[test]
    fn test_get_items() {
        let core = Core::new();

        // Test getting first 10 items
        let items = core.get_items(0, 10);
        assert_eq!(items.len(), 10);
        assert_eq!(items[0].id, 1);
        assert_eq!(items[9].id, 10);

        // Test getting items near the end (95, 10) should return only 5 items
        let items = core.get_items(95, 10);
        assert_eq!(items.len(), 5);
        assert_eq!(items[0].id, 96);
        assert_eq!(items[4].id, 100);

        // Test out-of-bounds start
        let items = core.get_items(100, 10);
        assert_eq!(items.len(), 0);

        // Test out-of-bounds start beyond total
        let items = core.get_items(200, 10);
        assert_eq!(items.len(), 0);

        // Test getting all items
        let items = core.get_items(0, 100);
        assert_eq!(items.len(), 100);

        // Test getting more than available
        let items = core.get_items(0, 150);
        assert_eq!(items.len(), 100);
    }

    #[test]
    fn test_column_modification() {
        let core = Core::new();

        // Test initial state
        assert_eq!(core.get_config().num_columns, 5);

        // Test increasing columns
        core.increase_columns();
        assert_eq!(core.get_config().num_columns, 6);

        // Test increasing to maximum (20)
        for _ in 0..14 {
            core.increase_columns();
        }
        assert_eq!(core.get_config().num_columns, 20);

        // Test that it doesn't go beyond maximum
        core.increase_columns();
        assert_eq!(core.get_config().num_columns, 20);

        // Test decreasing columns
        core.decrease_columns();
        assert_eq!(core.get_config().num_columns, 19);

        // Test decreasing to minimum (1)
        for _ in 0..18 {
            core.decrease_columns();
        }
        assert_eq!(core.get_config().num_columns, 1);

        // Test that it doesn't go below minimum
        core.decrease_columns();
        assert_eq!(core.get_config().num_columns, 1);

        // Test increasing from minimum
        core.increase_columns();
        assert_eq!(core.get_config().num_columns, 2);
    }
}
