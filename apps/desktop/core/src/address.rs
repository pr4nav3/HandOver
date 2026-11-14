//! Typed hub addresses. People type `192.168.1.20`, `hub.local:8000`, or paste
//! `http://192.168.1.20:8000/#/learn` from a browser; all of them mean one hub.

use url::Url;

/// The hub's default http port (CONTRACT.md 1).
pub const DEFAULT_PORT: u16 = 8000;

/// A hub's base address: `http://host:port`, with no path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubAddress {
    pub host: String,
    pub port: u16,
}

impl HubAddress {
    /// Reads what the person typed. The error is a sentence to show them.
    pub fn parse(typed: &str) -> Result<HubAddress, String> {
        let typed = typed.trim();
        if typed.is_empty() {
            return Err("Type the hub's address.".into());
        }
        if typed.chars().any(char::is_whitespace) {
            return Err("An address has no spaces.".into());
        }
        let lower = typed.to_ascii_lowercase();
        let with_scheme = if lower.starts_with("http://") || lower.starts_with("ws://") {
            format!("http://{}", &typed[typed.find("://").expect("checked") + 3..])
        } else if lower.starts_with("https://") || lower.starts_with("wss://") {
            return Err("Use the hub's http address, port 8000. The app talks to the hub on the local network.".into());
        } else if lower.contains("://") {
            return Err("That is not a hub address.".into());
        } else {
            format!("http://{typed}")
        };
        let url = Url::parse(&with_scheme).map_err(|_| "That is not a hub address.".to_string())?;
        let host = match url.host() {
            Some(url::Host::Domain(d)) => d.to_string(),
            Some(url::Host::Ipv4(ip)) => ip.to_string(),
            Some(url::Host::Ipv6(ip)) => format!("[{ip}]"),
            None => return Err("That is not a hub address.".into()),
        };
        if !url.username().is_empty() || url.password().is_some() {
            return Err("That is not a hub address.".into());
        }
        // `Url` drops the port when it is the scheme default (80); keep what was typed.
        let port = url.port().unwrap_or(if has_explicit_port(&with_scheme) { 80 } else { DEFAULT_PORT });
        if port == 0 {
            return Err("That port is not valid.".into());
        }
        Ok(HubAddress { host, port })
    }

    /// `http://host:port`
    pub fn base(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }

    /// `ws://host:port/ws/ui`
    pub fn ui_socket(&self) -> String {
        format!("ws://{}:{}/ws/ui", self.host, self.port)
    }

    /// `host:port`, for socket connects and for showing.
    pub fn authority(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    /// What the app shows: the port is left out when it is the default.
    pub fn display(&self) -> String {
        if self.port == DEFAULT_PORT {
            self.host.clone()
        } else {
            self.authority()
        }
    }
}

fn has_explicit_port(with_scheme: &str) -> bool {
    let rest = &with_scheme["http://".len()..];
    let authority = rest.split(['/', '?', '#']).next().unwrap_or("");
    match authority.rfind(']') {
        Some(i) => authority[i..].contains(':'),
        None => authority.contains(':'),
    }
}

/// A lesson id the hub would accept (CONTRACT.md 2), so a bad id never reaches a URL.
pub fn valid_lesson_id(id: &str) -> bool {
    let mut chars = id.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_alphanumeric())
        && id.len() <= 64
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

/// A path inside a lesson folder that is safe to fetch: relative, forward slashes, no `..`.
pub fn valid_lesson_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= 256
        && !path.starts_with('/')
        && path.split('/').all(|seg| !seg.is_empty() && seg != "." && seg != "..")
        && path.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '/' | '.' | '_' | '-'))
}
