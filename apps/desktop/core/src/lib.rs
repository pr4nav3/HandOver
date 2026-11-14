//! The HandOver desktop core. No UI: the Tauri shell in `app/` and the tests use it.

pub mod address;
pub mod api;
pub mod backoff;
pub mod engine;
pub mod http;
pub mod protocol;
pub mod socket;
pub mod store;
pub mod themes;

pub const PRODUCT_NAME: &str = "HandOver";
