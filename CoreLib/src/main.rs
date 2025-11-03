use eframe::{egui, CreationContext};
use egui::{CentralPanel, Context, Grid, ScrollArea, TopBottomPanel};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone)]
struct Item {
    id: u32,
    text: String,
}

#[derive(Serialize, Deserialize)]
struct MyApp {
    items: Vec<Item>,
    num_columns: u32,
}

impl Default for MyApp {
    fn default() -> Self {
        let items = (1..=102)
            .map(|id| Item {
                id,
                text: format!("Item #{}", id),
            })
            .collect();
        Self {
            items,
            num_columns: 5,
        }
    }
}

impl eframe::App for MyApp {
    fn update(&mut self, ctx: &Context, frame: &mut eframe::Frame) {
        let mut theme = self.theme_from_storage(frame.storage().unwrap());

        TopBottomPanel::top("top_panel").show(ctx, |ui| {
            ui.horizontal_centered(|ui| {
                ui.label("Theme:");
                if ui.radio_value(&mut theme, 0, "Dark").clicked() {
                    self.store_theme(frame.storage_mut().unwrap(), theme);
                }
                if ui.radio_value(&mut theme, 1, "Light").clicked() {
                    self.store_theme(frame.storage_mut().unwrap(), theme);
                }
                ctx.set_visuals(if theme == 0 {
                    egui::Visuals::dark()
                } else {
                    egui::Visuals::light()
                });

                ui.separator();

                if ui.button("-").clicked() {
                    if self.num_columns > 1 {
                        self.num_columns -= 1;
                    }
                }
                ui.label(format!("{} columns", self.num_columns));
                if ui.button("+").clicked() {
                    if self.num_columns < 20 {
                        self.num_columns += 1;
                    }
                }
            });
        });

        CentralPanel::default().show(ctx, |ui| {
            ScrollArea::vertical().show(ui, |ui| {
                Grid::new("item_grid")
                    .num_columns(self.num_columns as usize)
                    .show(ui, |ui| {
                        for item in &self.items {
                            ui.label(&item.text);
                            if item.id % self.num_columns == 0 {
                                ui.end_row();
                            }
                        }
                    });
            });
        });
    }

    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        eframe::set_value(storage, eframe::APP_KEY, self);
    }
}

impl MyApp {
    fn theme_from_storage(&self, storage: &dyn eframe::Storage) -> i32 {
        storage.get_string("theme").and_then(|s| s.parse().ok()).unwrap_or(0)
    }

    fn store_theme(&self, storage: &mut dyn eframe::Storage, theme: i32) {
        storage.set_string("theme", theme.to_string());
    }

    fn new(cc: &CreationContext) -> Self {
        if let Some(storage) = cc.storage {
            if let Some(state) = eframe::get_value::<Self>(storage, eframe::APP_KEY) {
                return state;
            }
        }

        let theme = cc.storage.and_then(|s| s.get_string("theme")).and_then(|s| s.parse().ok()).unwrap_or(0);
        cc.egui_ctx.set_visuals(if theme == 0 {
            egui::Visuals::dark()
        } else {
            egui::Visuals::light()
        });
        Self::default()
    }
}

fn main() -> Result<(), eframe::Error> {
    let options = eframe::NativeOptions {
        ..Default::default()
    };
    eframe::run_native(
        "My egui App",
        options,
        Box::new(|cc| Ok(Box::new(MyApp::new(cc)))),
    )
}
