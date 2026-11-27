//! Fetching from the web, through Windows, so the user's proxy and certificates are the ones used.

use crate::failure::{Failure, OrSay, Outcome};
use crate::package::VERSION;
use crate::paths::Paths;
use crate::win32::{self, WebAddress};

/// Fetches an address, which outside a sandbox has to be an HTTPS one, and returns the status the server answered
/// with and what it sent. An answer longer than `limit` bytes is a failure.
pub fn get(url: &str, limit: usize, paths: &Paths) -> Outcome<(u32, Vec<u8>)> {
    let address = address(url)
        .filter(|address| address.secure || paths.is_sandbox())
        .ok_or_else(|| Failure::new(format!("{url} isn't an address the app fetches from.")))?;
    let agent = format!("{}/{VERSION}", env!("CARGO_BIN_NAME"));
    win32::http_get(&address, &agent, limit)
        .or_say(|| format!("{} couldn't be reached. Check that this computer is online", address.host))
}

fn address(url: &str) -> Option<WebAddress> {
    let (secure, rest) = match url.split_once("://")? {
        ("https", rest) => (true, rest),
        ("http", rest) => (false, rest),
        _ => return None,
    };
    let (host, path) = rest.find('/').map_or((rest, "/"), |slash| rest.split_at(slash));
    let (host, port) = match host.rsplit_once(':') {
        Some((host, port)) => (host, port.parse().ok()?),
        None => (host, if secure { 443 } else { 80 }),
    };
    (!host.is_empty()).then(|| WebAddress { secure, host: host.to_owned(), port, path: path.to_owned() })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_address_is_split_into_what_windows_takes() {
        let whole = address("http://127.0.0.1:8123/node.zip?x=1").unwrap();
        let split =
            WebAddress { secure: false, host: "127.0.0.1".to_owned(), port: 8123, path: "/node.zip?x=1".to_owned() };
        assert_eq!(whole, split);
        let node = address("https://nodejs.org/dist/v26.13.1/node-v26.13.1-win-x64.zip").unwrap();
        assert!(node.secure && node.port == 443 && node.host == "nodejs.org");
        assert_eq!(address("https://nodejs.org").unwrap().path, "/");
        for not_one in ["", "nodejs.org/dist", "ftp://example.com/file", "https:///file", "http://host:port/"] {
            assert_eq!(address(not_one), None, "{not_one}");
        }
    }
}
