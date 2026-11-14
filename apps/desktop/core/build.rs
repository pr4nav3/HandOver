//! Embeds the shared theme catalog, `apps/design/THEMES.md`, when it exists. Without it the
//! core ships its built-in Dark and Light pair (src/themes.rs).

use std::path::Path;

fn main() {
    let catalog = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../design/THEMES.md");
    println!("cargo:rerun-if-changed={}", catalog.display());
    // Also rerun when the folder appears, so a catalog added later is picked up.
    println!("cargo:rerun-if-changed={}", catalog.parent().expect("has a parent").display());
    let text = std::fs::read_to_string(&catalog).unwrap_or_default();
    let out = Path::new(&std::env::var("OUT_DIR").expect("cargo sets OUT_DIR")).join("THEMES.md");
    std::fs::write(out, text).expect("OUT_DIR is writable");
}
