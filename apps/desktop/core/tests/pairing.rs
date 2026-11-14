//! Typed addresses, recent hubs, settings, back-off and themes.

use handover_core::address::*;
use handover_core::backoff::Backoff;
use handover_core::protocol::ClosePolicy;
use handover_core::store::{Recent, Settings, SettingsStore, RECENT_MAX};
use handover_core::themes::{catalog, catalog_from, parse_markdown, Looks, TOKENS};
use std::time::Duration;

fn temp_dir(name: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("handover-desktop-test-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn typed_addresses() {
    let base = |s: &str| HubAddress::parse(s).map(|h| h.base());
    assert_eq!(base("192.168.1.20").unwrap(), "http://192.168.1.20:8000");
    assert_eq!(base("  192.168.1.20:8099 ").unwrap(), "http://192.168.1.20:8099");
    assert_eq!(base("http://192.168.1.20:8000/#/learn").unwrap(), "http://192.168.1.20:8000");
    assert_eq!(base("HTTP://Hub.Local").unwrap(), "http://hub.local:8000");
    assert_eq!(base("ws://localhost:8000/ws/ui").unwrap(), "http://localhost:8000");
    assert_eq!(base("localhost:80").unwrap(), "http://localhost:80");
    assert_eq!(base("http://localhost:80").unwrap(), "http://localhost:80");
    assert_eq!(base("[::1]:8099").unwrap(), "http://[::1]:8099");
    assert_eq!(base("[::1]").unwrap(), "http://[::1]:8000");
    assert!(base("").is_err());
    assert!(base("https://hub.local:8443").unwrap_err().contains("http address"));
    assert!(base("ftp://hub").is_err());
    assert!(base("two words").is_err());
    assert!(base("user:pw@hub").is_err());
    assert!(base("hub:99999").is_err());
    assert!(base("hub:0").is_err());
}

#[test]
fn address_parts() {
    let h = HubAddress::parse("10.0.0.5").unwrap();
    assert_eq!(h.ui_socket(), "ws://10.0.0.5:8000/ws/ui");
    assert_eq!(h.display(), "10.0.0.5");
    assert_eq!(HubAddress::parse("10.0.0.5:8099").unwrap().display(), "10.0.0.5:8099");
}

#[test]
fn lesson_ids_and_paths() {
    assert!(valid_lesson_id("demo-v1"));
    assert!(valid_lesson_id("A_b-9"));
    assert!(!valid_lesson_id("-lead"));
    assert!(!valid_lesson_id("a/b"));
    assert!(!valid_lesson_id(&"a".repeat(65)));
    assert!(valid_lesson_path("clips/01.mp4"));
    assert!(!valid_lesson_path("../secret"));
    assert!(!valid_lesson_path("/etc/passwd"));
    assert!(!valid_lesson_path("clips//01.mp4"));
    assert!(!valid_lesson_path("clips/a b.mp4"));
}

#[test]
fn recent_hubs_keep_order_and_limit() {
    let dir = temp_dir("recent");
    let r = Recent::new(&dir);
    assert!(r.list().is_empty());
    r.touch_at("http://a:8000", "a", 10).unwrap();
    r.touch_at("http://b:8000", "b", 20).unwrap();
    let list = r.touch_at("http://a:8000", "a", 30).unwrap();
    assert_eq!(list.iter().map(|h| h.base.as_str()).collect::<Vec<_>>(), ["http://a:8000", "http://b:8000"]);
    for i in 0..10 {
        r.touch_at(&format!("http://h{i}:8000"), "h", 100 + i).unwrap();
    }
    let list = Recent::new(&dir).list();
    assert_eq!(list.len(), RECENT_MAX);
    assert_eq!(list[0].base, "http://h9:8000");
    let list = r.forget("http://h9:8000").unwrap();
    assert_eq!(list[0].base, "http://h8:8000");
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn settings_round_trip_and_tolerate_junk() {
    let dir = temp_dir("settings");
    let store = SettingsStore::new(&dir);
    assert_eq!(store.load(), Settings::default());
    let s = Settings { theme: "night".into(), appearance: "dark".into(), chime: false, ..Settings::default() };
    store.save(&s).unwrap();
    assert_eq!(store.load(), s);
    std::fs::write(dir.join("settings.json"), "{not json").unwrap();
    assert_eq!(store.load(), Settings::default());
    std::fs::write(dir.join("settings.json"), r#"{"theme":"dark"}"#).unwrap();
    assert_eq!(store.load().theme, "dark");
    assert!(store.load().reopen_last_hub, "missing keys take defaults");
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn backoff_curve() {
    let mut b = Backoff::new();
    let ms = |d: Option<Duration>| d.map(|d| d.as_millis() as u64);
    assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(400));
    assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(800));
    assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(1600));
    assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(3200));
    assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(5000));
    for _ in 0..40 {
        assert_eq!(ms(b.next_delay(ClosePolicy::Backoff)), Some(5000));
    }
    b.reset();
    assert_eq!(ms(b.next_delay(ClosePolicy::Immediately)), Some(0));
    assert_eq!(ms(b.next_delay(ClosePolicy::Immediately)), Some(800), "only the first retry is instant");
    b.reset();
    assert_eq!(ms(b.next_delay(ClosePolicy::SlowBackoff)), Some(2000));
    b.reset();
    assert_eq!(b.next_delay(ClosePolicy::Stop), None);
}

#[test]
fn builtin_catalog() {
    let c = catalog_from("");
    assert_eq!(c.source, "built-in");
    assert_eq!(c.themes.len(), 1);
    let t = &c.themes[0];
    assert_eq!((t.id.as_str(), t.looks), ("system", Looks::System));
    for look in [t.light.as_ref().unwrap(), t.dark.as_ref().unwrap()] {
        for token in TOKENS {
            assert!(look.contains_key(*token), "built-in has {token}");
        }
    }
}

#[test]
fn themes_markdown_sections() {
    let md =
        std::fs::read_to_string(format!("{}/tests/fixtures/themes_sample.md", env!("CARGO_MANIFEST_DIR"))).unwrap();
    let themes = parse_markdown(&md);
    let ids: Vec<&str> = themes.iter().map(|t| t.id.as_str()).collect();
    assert_eq!(ids, ["system", "night", "paperish"], "a catalog row with no section is skipped");

    let d = &themes[0];
    assert_eq!(
        (d.name.as_str(), d.group.as_str(), d.detail.as_str(), d.looks),
        ("Default", "Classic", "Cool gray", Looks::System)
    );
    let (l, k) = (d.light.as_ref().unwrap(), d.dark.as_ref().unwrap());
    assert_eq!(l["bg"], "#f0f1f2");
    assert_eq!(l["panel"], "#fbfbfc");
    assert_eq!(l["panel-2"], "#e4e5e8");
    assert_eq!(l["muted"], "rgba(26, 27, 30, 0.7)");
    assert_eq!(l["border"], "rgba(26, 27, 30, 0.09)", "light lines are ink");
    assert_eq!(k["border"], "rgba(255, 255, 255, 0.1)", "dark lines are white");
    assert_eq!(k["border-strong"], "rgba(255, 255, 255, 0.17)");
    assert_eq!(l["accent-ink"], "#3249b8");
    assert_eq!(l["red"], "#b80011", "default for light");
    assert_eq!(k["red"], "#ff7a70", "theme value for dark");
    assert_eq!(l["green"], "#186629");
    assert_eq!(k["green"], "#30d158");
    assert_eq!(l["grain"], "0");

    let n = &themes[1];
    assert_eq!(n.looks, Looks::Dark);
    assert!(n.light.is_none());
    let k = n.dark.as_ref().unwrap();
    assert_eq!(k["bg"], "#000000");
    assert_eq!(k["panel-2"], "#0f0f11", "well defaults to raised");
    assert_eq!(k["muted"], "rgba(242, 242, 244, 0.66)");
    assert_eq!(k["faint"], "rgba(242, 242, 244, 0.44)");
    assert_eq!(k["border-strong"], "rgba(255, 255, 255, 0.2)");
    assert_eq!((k["accent"].as_str(), k["accent-ink"].as_str()), ("#8aa8ff", "#8aa8ff"));

    let p = &themes[2];
    assert_eq!((p.looks, p.group.as_str()), (Looks::Light, "Grain"));
    let l = p.light.as_ref().unwrap();
    assert_eq!(
        (l["green"].as_str(), l["amber"].as_str(), l["red"].as_str(), l["grey"].as_str()),
        ("#155c25", "#843900", "#9e000f", "#626266")
    );
    assert_eq!(l["grain"], "0.035");
    for t in &themes {
        for look in t.light.iter().chain(t.dark.iter()) {
            for token in TOKENS {
                assert!(look.contains_key(*token), "{} has {token}", t.id);
            }
        }
    }
    let c = catalog_from(&md);
    assert_eq!(c.source, "THEMES.md");
    assert_eq!(c.groups, ["Classic", "Grain"]);
}

/// The shared catalog in apps/design, when it is in the checkout: all 14 themes read, and the
/// build embedded the same file.
#[test]
fn shared_catalog() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../design/THEMES.md");
    let Ok(md) = std::fs::read_to_string(&path) else { return };
    let c = catalog_from(&md);
    let ids: Vec<&str> = c.themes.iter().map(|t| t.id.as_str()).collect();
    assert_eq!(
        ids,
        [
            "system",
            "night",
            "highContrast",
            "ivory",
            "dim",
            "grain",
            "newsprint",
            "chalkboard",
            "harbor",
            "sage",
            "clay",
            "nocturne",
            "mono",
            "matte"
        ]
    );
    assert_eq!(c.groups, ["Classic", "Grain", "Color", "Mono"]);
    let get = |id: &str| c.get(id).unwrap();
    assert_eq!(get("night").looks, Looks::Dark);
    assert_eq!(get("newsprint").looks, Looks::Light);
    assert_eq!(get("matte").looks, Looks::Light);
    assert_eq!(get("mono").looks, Looks::System);
    let hc = get("highContrast").dark.as_ref().unwrap();
    assert_eq!((hc["bg"].as_str(), hc["green"].as_str(), hc["grey"].as_str()), ("#000000", "#6cf294", "#b4b4b8"));
    assert_eq!(hc["muted"], "rgba(255, 255, 255, 0.86)");
    assert_eq!(get("grain").light.as_ref().unwrap()["grain"], "0.03");
    assert_eq!(get("chalkboard").dark.as_ref().unwrap()["accent"], "#f0e19a");
    for t in &c.themes {
        for look in t.light.iter().chain(t.dark.iter()) {
            for token in TOKENS {
                assert!(look.contains_key(*token), "{} has {token}", t.id);
            }
        }
    }
    assert_eq!(catalog(), c, "the build embedded the current THEMES.md");
}

#[test]
fn byte_ranges() {
    use handover_core::http::{resolve_range, slice, CachedFile};
    assert_eq!(resolve_range("bytes=0-1", 10), Some((0, 1)));
    assert_eq!(resolve_range("bytes=0-", 10), Some((0, 9)));
    assert_eq!(resolve_range("bytes=5-100", 10), Some((5, 9)));
    assert_eq!(resolve_range("bytes=-3", 10), Some((7, 9)));
    assert_eq!(resolve_range("bytes=10-", 10), None);
    assert_eq!(resolve_range("bytes=3-2", 10), None);
    assert_eq!(resolve_range("bytes=0-1,4-5", 10), None);
    assert_eq!(resolve_range("items=0-1", 10), None);
    let f = CachedFile { content_type: "video/mp4".into(), body: (0u8..10).collect() };
    let r = slice(&f, Some("bytes=2-4"));
    assert_eq!((r.status, r.body.as_slice()), (206, &[2u8, 3, 4][..]));
    assert!(r.headers.contains(&("Content-Range".into(), "bytes 2-4/10".into())));
    assert_eq!(slice(&f, None).status, 200);
    assert_eq!(slice(&f, Some("bytes=20-")).status, 416);
}

#[test]
fn api_paths_and_queries() {
    use handover_core::api::{query_string, valid_api_path, Tokens};
    assert!(valid_api_path("/api/courses"));
    assert!(valid_api_path("/api/courses/fold-v1/edit/boundaries"));
    assert!(!valid_api_path("/lessons/x/clips/01.mp4"), "only /api/");
    assert!(!valid_api_path("/api/../ws/ui"));
    assert!(!valid_api_path("/api/courses?filter=all"), "queries go in their own field");
    assert!(!valid_api_path("http://evil/api/x"));
    let q = query_string(&serde_json::json!({ "filter": "orgs", "org": "", "q": "fold it", "n": 3, "skip": null }));
    assert_eq!(q, "filter=orgs&n=3&q=fold+it");
    assert_eq!(query_string(&serde_json::Value::Null), "");

    let dir = temp_dir("tokens");
    let t = Tokens::new(&dir);
    assert_eq!(t.get("http://a:8000"), None);
    t.set("http://a:8000", Some("secret")).unwrap();
    t.set("http://b:8000", Some("other")).unwrap();
    assert_eq!(Tokens::new(&dir).get("http://a:8000").as_deref(), Some("secret"));
    t.set("http://a:8000", None).unwrap();
    assert_eq!(t.get("http://a:8000"), None);
    assert_eq!(t.get("http://b:8000").as_deref(), Some("other"));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(dir.join("tokens.json")).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600, "tokens are readable by this user only");
    }
    let _ = std::fs::remove_dir_all(dir);
}
