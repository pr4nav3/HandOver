//! Pairing a phone: the address phones on the local network can reach, the
//! `handover://connect?hub=<url-encoded http://host:port>` link the phone apps scan, and its QR
//! code as SVG. Everything is computed here; nothing goes over the network.

use crate::address::HubAddress;
use qrcode::render::svg;
use qrcode::{EcLevel, QrCode};
use std::net::{IpAddr, Ipv4Addr, UdpSocket};

/// This computer's address on the local network, or None when it has none.
///
/// Asks the system which interface it would use to reach a few private and public addresses.
/// Connecting a UDP socket only picks a route: no packet is sent.
pub fn lan_ip() -> Option<IpAddr> {
    let probes = ["10.254.254.254:1", "192.168.254.254:1", "172.31.254.254:1", "8.8.8.8:80"];
    probes.iter().find_map(|p| {
        let s = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok()?;
        s.connect(p).ok()?;
        let ip = s.local_addr().ok()?.ip();
        usable(ip).then_some(ip)
    })
}

fn usable(ip: IpAddr) -> bool {
    !ip.is_loopback() && !ip.is_unspecified() && !matches!(ip, IpAddr::V4(v4) if v4.is_link_local())
}

/// True when the host names this computer only (localhost, 127.x, ::1), so a phone cannot use it.
pub fn is_loopback_host(host: &str) -> bool {
    let h = host.trim_start_matches('[').trim_end_matches(']').to_ascii_lowercase();
    h == "localhost"
        || h.ends_with(".localhost")
        || h.parse::<IpAddr>().map(|ip| ip.is_loopback() || ip.is_unspecified()).unwrap_or(false)
}

/// The hub address a phone should use: the paired address, with a loopback host swapped for
/// this computer's LAN address. None when the hub is on loopback and there is no LAN address.
pub fn phone_hub(hub: &HubAddress, lan: Option<IpAddr>) -> Option<HubAddress> {
    if !is_loopback_host(&hub.host) {
        return Some(hub.clone());
    }
    let host = match lan? {
        IpAddr::V4(v4) => v4.to_string(),
        IpAddr::V6(v6) => format!("[{v6}]"),
    };
    Some(HubAddress { host, port: hub.port })
}

/// `handover://connect?hub=http%3A%2F%2F192.168.1.20%3A8000`
pub fn connect_link(hub: &HubAddress) -> String {
    let encoded: String = url::form_urlencoded::byte_serialize(hub.base().as_bytes()).collect();
    format!("handover://connect?hub={encoded}")
}

/// The hub URL and pairing link from the hub's `GET /api/hub-info` answer, when it has them.
/// None on hubs without the route or without a LAN address (the caller falls back).
pub fn from_hub_info(ans: &crate::api::Answer) -> Option<(String, String)> {
    if !(200..300).contains(&ans.status) {
        return None;
    }
    let url = ans.body.get("hub_url")?.as_str()?.to_string();
    let link = ans.body.get("pair_link")?.as_str()?.to_string();
    (HubAddress::parse(&url).is_ok() && link.starts_with("handover://connect?hub=")).then_some((url, link))
}

/// The QR code for `text` as an SVG, dark on white with the standard quiet zone, so phone
/// cameras read it in any theme.
pub fn qr_svg(text: &str) -> Result<String, String> {
    let code = QrCode::with_error_correction_level(text.as_bytes(), EcLevel::M).map_err(|e| e.to_string())?;
    Ok(code
        .render::<svg::Color<'_>>()
        .min_dimensions(240, 240)
        .dark_color(svg::Color("#000000"))
        .light_color(svg::Color("#ffffff"))
        .quiet_zone(true)
        .build())
}
