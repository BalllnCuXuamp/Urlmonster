use aho_corasick::AhoCorasick;
use pyo3::prelude::*;
use regex::Regex;
use std::borrow::Cow;
use std::collections::HashMap;
use once_cell::sync::Lazy;

static EMAIL_REGEX: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$").unwrap()
});

struct ParsedLine {
    url: Vec<u8>,
    login: Vec<u8>,
    password: Vec<u8>,
}

fn find_first(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || needle.len() > haystack.len() {
        return None;
    }
    haystack.windows(needle.len()).position(|w| w == needle)
}

fn parse_line_bytes(line: &[u8], mode: &str, delim: &[u8]) -> Option<ParsedLine> {
    if line.is_empty() || delim.is_empty() {
        return None;
    }

    match mode {
        "exact" => {
            let pos = find_first(line, delim)?;
            let login = &line[..pos];
            let password = &line[pos + delim.len()..];
            if login.is_empty() || password.is_empty() {
                return None;
            }
            Some(ParsedLine {
                url: b"".to_vec(),
                login: login.to_vec(),
                password: password.to_vec(),
            })
        }
        "url" | "default" | "domain" => {
            let proto_end = line.windows(3).position(|w| w == b"://").map(|p| p + 3).unwrap_or(0);
            let after_proto = &line[proto_end..];
            let is_url = proto_end > 0;

            // ---- URL: userinfo "protocol://login:password@host/..." ----
            if is_url {
                let first_slash = find_first(after_proto, b"/");
                if let Some(at_pos) = find_first(after_proto, b"@") {
                    let at_in_authority = match first_slash {
                        Some(s) => at_pos < s,
                        None => true,
                    };
                    if at_in_authority {
                        let userinfo = &after_proto[..at_pos];
                        if let Some(colon) = find_first(userinfo, b":") {
                            let login = &userinfo[..colon];
                            let password = &userinfo[colon + 1..];
                            if !login.is_empty() && !password.is_empty() {
                                return Some(ParsedLine {
                                    url: line[..proto_end].to_vec(),
                                    login: login.to_vec(),
                                    password: password.to_vec(),
                                });
                            }
                        }
                    }
                }
            }

            // ---- URL: credentials at the end of the path (after the last '/') ----
            if is_url {
                let seg_start = after_proto.iter().rposition(|b| *b == b'/').map(|s| s + 1).unwrap_or(0);
                let endpoint = &after_proto[seg_start..];
                // The last two ':'-separated parts of the endpoint are login:password,
                // everything before them stays in the URL.
                if let Some(c1) = endpoint.iter().rposition(|b| *b == b':') {
                    let password = &endpoint[c1 + 1..];
                    if !password.is_empty() {
                        if let Some(c2) = endpoint[..c1].iter().rposition(|b| *b == b':') {
                            let login = &endpoint[c2 + 1..c1];
                            if !login.is_empty() {
                                let url_end = proto_end + seg_start + c2;
                                return Some(ParsedLine {
                                    url: line[..url_end].to_vec(),
                                    login: login.to_vec(),
                                    password: password.to_vec(),
                                });
                            }
                        } else {
                            let login = &endpoint[..c1];
                            if !login.is_empty() {
                                let url_end = proto_end + seg_start;
                                return Some(ParsedLine {
                                    url: line[..url_end].to_vec(),
                                    login: login.to_vec(),
                                    password: password.to_vec(),
                                });
                            }
                        }
                    }
                }
                return None;
            }

            // ---- Generic / plain lines (no "://") ----
            let safe_seps: [&[u8]; 5] = [b":", b";", b"|", b",", b"\t"];
            let mut boundary_seps: Vec<&[u8]> = Vec::new();
            if safe_seps.contains(&delim) {
                boundary_seps.push(delim);
            }
            for d in &safe_seps {
                if !boundary_seps.iter().any(|e| *e == *d) {
                    boundary_seps.push(d);
                }
            }

            let mut best: Option<(usize, Vec<u8>, Vec<u8>)> = None; // (url_end, login, password)

            for sep in &boundary_seps {
                if sep.len() > line.len() {
                    continue;
                }
                let mut ok_for_sep = false;

                // "login:password" with an empty URL prefix (email / username / phone).
                if let Some(first_sep) = find_first(line, sep) {
                    let login = &line[..first_sep];
                    let password = &line[first_sep + sep.len()..];
                    if !login.is_empty() && !password.is_empty() {
                        ok_for_sep = true;
                        if best.is_none() {
                            best = Some((0, login.to_vec(), password.to_vec()));
                        }
                    }
                }

                // Every occurrence of the separator can be the site/login boundary;
                // the latest valid one wins ("host:port:login:password").
                let mut from = 0usize;
                loop {
                    let pos = match find_first(&line[from..], sep) {
                        Some(p) => p + from,
                        None => break,
                    };
                    from = pos + sep.len();
                    let rest_start = pos + sep.len();
                    let login_end = match find_first(&line[rest_start..], sep) {
                        Some(q) => q + rest_start,
                        None => break, // trailing text is the password; an empty password is invalid
                    };
                    let login = &line[rest_start..login_end];
                    let password = &line[login_end + sep.len()..];
                    if login.is_empty() || password.is_empty() {
                        continue;
                    }
                    ok_for_sep = true;
                    match &best {
                        Some((best_end, _, _)) if pos <= *best_end => {}
                        _ => {
                            best = Some((pos, login.to_vec(), password.to_vec()));
                        }
                    }
                }

                if ok_for_sep {
                    break; // the preferred (detected) separator already worked
                }
            }

            if let Some((url_end, login, password)) = best {
                // Absorb a trailing path segment of the login into the URL
                // (e.g. "//site.com/path/login" -> url ends at the last '/').
                if let Some(slash_pos) = login.iter().rposition(|b| *b == b'/') {
                    let after_slash = &login[slash_pos + 1..];
                    if !after_slash.is_empty() {
                        return Some(ParsedLine {
                            url: line[..url_end + slash_pos + 1].to_vec(),
                            login: after_slash.to_vec(),
                            password,
                        });
                    }
                }
                Some(ParsedLine {
                    url: line[..url_end].to_vec(),
                    login,
                    password,
                })
            } else {
                None
            }
        }
        _ => {
            Some(ParsedLine {
                url: b"".to_vec(),
                login: line.to_vec(),
                password: b"".to_vec(),
            })
        }
    }
}

fn ensure_https(line: &[u8]) -> Vec<u8> {
    if find_first(line, b"://").is_some() {
        if let Some(pos) = find_first(line, b"http://") {
            let mut out = Vec::new();
            out.extend_from_slice(&line[..pos]);
            out.extend_from_slice(b"https://");
            out.extend_from_slice(&line[pos + 7..]);
            return out;
        }
        return line.to_vec();
    }

    let mut out = b"https://".to_vec();
    out.extend_from_slice(line);
    out
}

/// Pre-built matching + parsing engine. Construct once per worker (or per
/// (mode, delim) combination), then call `process(block)` for every block.
/// The Aho-Corasick automaton is built exactly once, which removes the
/// dominant per-block rebuild cost of the old `process_block` design.
#[pyclass(module = "rust_scan")]
struct Engine {
    queries: Vec<Vec<u8>>,
    flags: Vec<bool>,
    mode: String,
    delim: Vec<u8>,
    default_save_full: bool,
    require_email: bool,
    case_sensitive: bool,
    regex_mode: bool,
    automaton: Option<AhoCorasick>,
    regexes: Vec<(usize, Regex)>,
    blacklist_ac: Option<AhoCorasick>,
}

impl Engine {
    fn format_into(&self, out: &mut Vec<u8>, q: &[u8], orig_line: &[u8], parsed: &ParsedLine, save_full: bool) {
        out.extend_from_slice(q);
        out.push(b'\x00');
        if save_full {
            if parsed.url.is_empty() {
                out.extend_from_slice(&ensure_https(orig_line));
            } else {
                out.extend_from_slice(&ensure_https(&parsed.url));
                out.push(b':');
                out.extend_from_slice(&parsed.login);
                out.push(b':');
                out.extend_from_slice(&parsed.password);
            }
        } else {
            out.extend_from_slice(&parsed.login);
            out.push(b':');
            out.extend_from_slice(&parsed.password);
        }
        out.push(b'\n');
    }
}

#[pymethods]
impl Engine {
    #[new]
    #[pyo3(signature = (queries, flags, mode, delim, default_save_full, require_email, case_sensitive, regex_mode, blacklist))]
    fn new(
        queries: Vec<Vec<u8>>,
        flags: Vec<bool>,
        mode: &str,
        delim: Vec<u8>,
        default_save_full: bool,
        require_email: bool,
        case_sensitive: bool,
        regex_mode: bool,
        blacklist: Option<Vec<Vec<u8>>>,
    ) -> Self {
        let mut automaton = None;
        if !regex_mode && !queries.is_empty() {
            let patterns: Vec<Vec<u8>> = if case_sensitive {
                queries.clone()
            } else {
                queries.iter().map(|q| q.to_ascii_lowercase()).collect()
            };
            let ac = AhoCorasick::new(patterns.iter().map(|p| &p[..])).unwrap();
            automaton = Some(ac);
        }

        let regexes: Vec<(usize, Regex)> = if regex_mode {
            queries
                .iter()
                .enumerate()
                .filter_map(|(i, q)| {
                    let pat = std::str::from_utf8(q).ok()?;
                    Regex::new(pat).ok().map(|r| (i, r))
                })
                .collect()
        } else {
            Vec::new()
        };

        let blacklist_ac = blacklist.map(|bl| {
            let lowered: Vec<Vec<u8>> = bl.iter().map(|b| b.to_ascii_lowercase()).collect();
            AhoCorasick::new(lowered.iter().map(|b| &b[..])).unwrap()
        });

        Engine {
            queries,
            flags,
            mode: mode.to_string(),
            delim,
            default_save_full,
            require_email,
            case_sensitive,
            regex_mode,
            automaton,
            regexes,
            blacklist_ac,
        }
    }

    /// Process one block of bytes (many full lines). Returns per-query-index
    /// aggregated buffers: (idx, bytes) where bytes are lines already marked
    /// with `query\x00content\n`. One (idx, buffer) per query with matches.
    fn process(&self, block: &[u8]) -> Vec<(usize, Vec<u8>)> {
        if block.is_empty() {
            return Vec::new();
        }

        // Lowercase the whole block ONCE (matching is the hot path; parsing
        // and output always use the original case).
        let need_lower = !self.case_sensitive || self.blacklist_ac.is_some();
        let low_block: Cow<[u8]> = if need_lower {
            Cow::Owned(block.to_ascii_lowercase())
        } else {
            Cow::Borrowed(block)
        };
        let low_block = low_block.as_ref();

        let mut bufs: Vec<Vec<u8>> = Vec::with_capacity(self.queries.len());
        for _ in 0..self.queries.len() {
            bufs.push(Vec::new());
        }
        let mut matched: Vec<usize> = Vec::new();
        let mut orig_pos = 0usize;

        for line in low_block.split(|b| *b == b'\n') {
            let orig_line = &block[orig_pos..orig_pos + line.len()];
            orig_pos += line.len() + 1;

            if orig_line.is_empty() {
                continue;
            }

            matched.clear();
            if self.regex_mode {
                if let Ok(s) = std::str::from_utf8(line) {
                    for (i, re) in &self.regexes {
                        if re.is_match(s) {
                            matched.push(*i);
                        }
                    }
                }
            } else if let Some(ac) = &self.automaton {
                // find_overlapping_iter reports EVERY match occurrence, so
                // overlapping queries ("site.com" + "site") all fire.
                for m in ac.find_overlapping_iter(line) {
                    matched.push(m.pattern().as_usize());
                }
                matched.sort_unstable();
                matched.dedup();
            }

            if matched.is_empty() {
                continue;
            }

            if let Some(bl_ac) = &self.blacklist_ac {
                if bl_ac.find(line).is_some() {
                    continue;
                }
            }

            if let Some(parsed) = parse_line_bytes(orig_line, &self.mode, &self.delim) {
                if self.require_email {
                    let login = std::str::from_utf8(&parsed.login).unwrap_or("");
                    if !EMAIL_REGEX.is_match(login) {
                        continue;
                    }
                }

                for &idx in &matched {
                    let q = &self.queries[idx];
                    let save_full = self.flags.get(idx).copied().unwrap_or(self.default_save_full);
                    let out = &mut bufs[idx];
                    self.format_into(out, q, orig_line, &parsed, save_full);
                }
            }
        }

        bufs
            .into_iter()
            .enumerate()
            .filter(|(_, b)| !b.is_empty())
            .map(|(i, b)| (i, b))
            .collect()
    }
}

/// Backward-compatible one-shot entry point (slow path — builds the engine
/// per call). Kept so older callers / existing .pyd users keep working.
#[pyfunction]
#[pyo3(signature = (block, queries, flags, mode, delim, _export_delim, default_save_full, _exclude_empty, require_email, case_sensitive, regex_mode, blacklist))]
fn process_block(
    block: &[u8],
    queries: Vec<Vec<u8>>,
    flags: HashMap<String, bool>,
    mode: &str,
    delim: Vec<u8>,
    _export_delim: Vec<u8>,
    default_save_full: bool,
    _exclude_empty: bool,
    require_email: bool,
    case_sensitive: bool,
    regex_mode: bool,
    blacklist: Option<Vec<Vec<u8>>>,
) -> PyResult<Vec<(String, Vec<u8>)>> {
    let flags_list: Vec<bool> = queries
        .iter()
        .map(|q| {
            let q_str = String::from_utf8_lossy(q);
            flags.get(q_str.as_ref()).copied().unwrap_or(default_save_full)
        })
        .collect();

    let engine = Engine::new(
        queries,
        flags_list,
        mode,
        delim,
        default_save_full,
        require_email,
        case_sensitive,
        regex_mode,
        blacklist,
    );

    Ok(engine
        .process(block)
        .into_iter()
        .map(|(idx, buf)| {
            let q = engine.queries[idx].clone();
            (String::from_utf8_lossy(&q).to_string(), buf)
        })
        .collect())
}

#[pymodule]
fn rust_scan(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Engine>()?;
    m.add_function(wrap_pyfunction!(process_block, m)?)?;
    Ok(())
}
