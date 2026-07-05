use aho_corasick::AhoCorasick;
use memchr::memchr;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::Regex;
use std::collections::HashMap;
use sha1::Digest;
use std::sync::Mutex;

fn _ensure_proto(line: &[u8]) -> Vec<u8> {
    if line.windows(3).any(|w| w == b"://") {
        line.to_vec()
    } else {
        let mut r = b"https://".to_vec();
        r.extend_from_slice(line);
        r
    }
}

fn _extract_login(line: &[u8], delim: &[u8]) -> Vec<u8> {
    if let Some(pos) = line.iter().position(|b| delim.contains(b)) {
        line[..pos].to_vec()
    } else {
        line.to_vec()
    }
}

fn _extract_password(line: &[u8], delim: &[u8]) -> Vec<u8> {
    if let Some(pos) = line.iter().position(|b| delim.contains(b)) {
        line[pos + 1..].to_vec()
    } else {
        b"".to_vec()
    }
}

fn parse_line_bytes(line: &[u8], mode: &str, delim: &[u8]) -> Option<Vec<u8>> {
    match mode {
        "url" | "default" => {
            let parts: Vec<&[u8]> = line.split(|b| delim.contains(b)).collect();
            if parts.len() < 2 {
                return None;
            }
            let login = parts[parts.len() - 2];
            let password = parts[parts.len() - 1];
            if login.is_empty() || password.is_empty() {
                return None;
            }
            let mut r = login.to_vec();
            r.push(b':');
            r.extend_from_slice(password);
            Some(r)
        }
        "exact" => {
            let colon_pos = line.iter().position(|b| *b == b':');
            match colon_pos {
                Some(pos) if pos > 0 && pos < line.len() - 1 => {
                    let login = &line[..pos];
                    let password = &line[pos + 1..];
                    if login.is_empty() || password.is_empty() {
                        return None;
                    }
                    let mut r = login.to_vec();
                    r.push(b':');
                    r.extend_from_slice(password);
                    Some(r)
                }
                _ => None,
            }
        }
        "domain" => {
            let s = std::str::from_utf8(line).unwrap_or("");
            let s = s.trim();
            let s = s.strip_prefix("http://").or_else(|| s.strip_prefix("https://")).unwrap_or(s);
            let s = s.strip_prefix("www.").unwrap_or(s);
            let domain = s.split('/').next().unwrap_or(s);
            Some(domain.as_bytes().to_vec())
        }
        _ => Some(line.to_vec()),
    }
}

fn format_output_line(
    line: &[u8],
    lp: &[u8],
    safe_q_bytes: &[u8],
    export_delim: &[u8],
    save_full: bool,
) -> Vec<u8> {
    let mut out = Vec::new();
    let safe_q_encoded = if safe_q_bytes.contains(&b'\x00') {
        hex::encode(safe_q_bytes).into_bytes()
    } else {
        safe_q_bytes.to_vec()
    };
    out.extend_from_slice(&safe_q_encoded);
    out.push(b'\x00');
    if save_full {
        let proto = _ensure_proto(line);
        out.extend_from_slice(&proto);
    } else if export_delim == b"password" {
        let pw = _extract_password(lp, b":");
        out.extend_from_slice(&pw);
    } else if export_delim == b"login" {
        let login = _extract_login(lp, b":");
        out.extend_from_slice(&login);
    } else if export_delim == b":" || export_delim == b";" || export_delim == b"|" || export_delim == b"\t" {
        let login = _extract_login(lp, b":");
        let password = _extract_password(lp, b":");
        out.extend_from_slice(&login);
        out.extend_from_slice(export_delim);
        out.extend_from_slice(&password);
    } else {
        out.extend_from_slice(lp);
    }
    out.push(b'\n');
    out
}

#[pyfunction]
#[pyo3(signature = (block, queries, flags, mode, delim, export_delim, default_save_full, exclude_empty, require_email, case_sensitive, regex_mode, blacklist=None))]
fn process_block(
    block: &[u8],
    queries: Vec<Vec<u8>>,
    flags: HashMap<String, bool>,
    mode: &str,
    delim: Vec<u8>,
    export_delim: Vec<u8>,
    default_save_full: bool,
    exclude_empty: bool,
    require_email: bool,
    case_sensitive: bool,
    regex_mode: bool,
    blacklist: Option<Vec<Vec<u8>>>,
) -> PyResult<Vec<(String, Vec<u8>)>> {
    let bl = blacklist.unwrap_or_default();

    let automaton: std::cell::OnceCell<AhoCorasick> = std::cell::OnceCell::new();
    let regexes: std::cell::OnceCell<Vec<(usize, Regex)>> = std::cell::OnceCell::new();

    if regex_mode {
        let _ = regexes.get_or_init(|| {
            queries
                .iter()
                .enumerate()
                .filter_map(|(i, q)| {
                    let pat = std::str::from_utf8(q).ok()?;
                    Regex::new(pat).ok().map(|r| (i, r))
                })
                .collect()
        });
    } else {
        let _ = automaton.get_or_init(|| {
            let patterns: Vec<Vec<u8>> = if case_sensitive {
                queries.clone()
            } else {
                queries.iter().map(|q| q.to_ascii_lowercase()).collect()
            };
            AhoCorasick::new(patterns.iter().map(|p| &p[..])).unwrap()
        });
    }

    let mut results: Vec<(String, Vec<u8>)> = Vec::new();

    let mut line_start = 0usize;
    loop {
        if line_start >= block.len() {
            break;
        }
        let remaining = &block[line_start..];
        let line_end = match memchr(b'\n', remaining) {
            Some(rel) => line_start + rel,
            None => {
                if remaining.is_empty() {
                    break;
                }
                block.len()
            }
        };
        let raw_line = &block[line_start..line_end];
        let line = if raw_line.ends_with(b"\r") {
            &raw_line[..raw_line.len() - 1]
        } else {
            raw_line
        };

        if exclude_empty && line.is_empty() {
            line_start = line_end + 1;
            continue;
        }

        let matched_indices: Vec<usize> = if regex_mode {
            if let Some(ref regs) = regexes.get() {
                regs.iter()
                    .filter_map(|(i, re)| {
                        let haystack = std::str::from_utf8(line).unwrap_or("");
                        if re.is_match(haystack) {
                            Some(*i)
                        } else {
                            None
                        }
                    })
                    .collect()
            } else {
                Vec::new()
            }
        } else if let Some(ac) = automaton.get() {
            let haystack = if case_sensitive {
                line.to_vec()
            } else {
                line.to_ascii_lowercase()
            };
            let mut v: Vec<usize> = ac.find_iter(&haystack).map(|m| m.pattern().as_usize()).collect();
            v.sort();
            v.dedup();
            v
        } else {
            let haystack = if case_sensitive {
                line.to_vec()
            } else {
                line.to_ascii_lowercase()
            };
            queries
                .iter()
                .enumerate()
                .filter_map(|(i, q)| {
                    let needle = if case_sensitive {
                        q.clone()
                    } else {
                        q.to_ascii_lowercase()
                    };
                    if haystack.windows(needle.len()).any(|w| w == needle.as_slice()) {
                        Some(i)
                    } else {
                        None
                    }
                })
                .collect()
        };

        if matched_indices.is_empty() {
            line_start = line_end + 1;
            continue;
        }

        if !bl.is_empty() {
            let low_line = line.to_ascii_lowercase();
            let blocked = bl.iter().any(|b| {
                low_line.windows(b.len()).any(|w| w == b.as_slice())
            });
            if blocked {
                line_start = line_end + 1;
                continue;
            }
        }

        let lp = match parse_line_bytes(line, mode, &delim) {
            Some(p) => p,
            None => {
                line_start = line_end + 1;
                continue;
            }
        };

        if require_email {
            let login_part = _extract_login(&lp, b":");
            let login_str = std::str::from_utf8(&login_part).unwrap_or("");
            let email_re = Regex::new(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$").unwrap();
            if !email_re.is_match(login_str) {
                line_start = line_end + 1;
                continue;
            }
        }

        for &qi in &matched_indices {
            let q_name = std::str::from_utf8(&queries[qi]).unwrap_or("").to_string();
            let save_full = flags.get(&q_name).copied().unwrap_or(default_save_full);
            let out_line = format_output_line(line, &lp, &queries[qi], &export_delim, save_full);
            results.push((q_name, out_line));
        }

        if line_end >= block.len() {
            break;
        }
        line_start = line_end + 1;
    }

    Ok(results)
}

static AC_CACHE: Mutex<Option<HashMap<u64, AhoCorasick>>> = Mutex::new(None);

fn hash_patterns(patterns: &[Vec<u8>]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    patterns.len().hash(&mut h);
    for p in patterns {
        p.hash(&mut h);
    }
    h.finish()
}

fn get_or_build_ac(queries: &[Vec<u8>], case_sensitive: bool) -> PyResult<AhoCorasick> {
    let patterns: Vec<Vec<u8>> = if case_sensitive {
        queries.to_vec()
    } else {
        queries.iter().map(|q| q.to_ascii_lowercase()).collect()
    };
    let key = hash_patterns(&patterns);

    let mut cache = AC_CACHE.lock().map_err(|e| {
        PyValueError::new_err(format!("Mutex poisoned: {}", e))
    })?;
    if let Some(ref map) = *cache {
        if let Some(ac) = map.get(&key) {
            return Ok(ac.clone());
        }
    }
    let ac = AhoCorasick::new(patterns.iter().map(|p| &p[..]))
        .map_err(|e| PyValueError::new_err(format!("AhoCorasick build failed: {}", e)))?;
    let map = cache.get_or_insert_with(HashMap::new);
    map.insert(key, ac.clone());
    Ok(ac)
}

#[pyfunction]
fn scan_block_rust(
    block: &[u8],
    queries: Vec<Vec<u8>>,
    case_sensitive: bool,
) -> PyResult<Vec<(usize, usize, Vec<usize>)>> {
    if block.is_empty() {
        return Ok(Vec::new());
    }

    let ac = get_or_build_ac(&queries, case_sensitive)?;

    let mut results: Vec<(usize, usize, Vec<usize>)> = Vec::new();
    let mut line_start = 0usize;

    loop {
        let remaining = &block[line_start..];
        match memchr(b'\n', remaining) {
            Some(rel_pos) => {
                let line_end = line_start + rel_pos;
                let line = &block[line_start..line_end];
                let haystack = if case_sensitive {
                    line.to_vec()
                } else {
                    line.to_ascii_lowercase()
                };

                let mut matched: Vec<usize> = ac
                    .find_iter(&haystack)
                    .map(|m| m.pattern().as_usize())
                    .collect();
                matched.sort();
                matched.dedup();

                if !matched.is_empty() {
                    results.push((line_start, line_end, matched));
                }

                line_start = line_end + 1;
            }
            None => {
                let line = &block[line_start..];
                if line.is_empty() {
                    break;
                }
                let haystack = if case_sensitive {
                    line.to_vec()
                } else {
                    line.to_ascii_lowercase()
                };

                let mut matched: Vec<usize> = ac
                    .find_iter(&haystack)
                    .map(|m| m.pattern().as_usize())
                    .collect();
                matched.sort();
                matched.dedup();

                if !matched.is_empty() {
                    results.push((line_start, block.len(), matched));
                }
                break;
            }
        }
    }

    Ok(results)
}

#[pyfunction]
#[pyo3(signature = (input_bytes, unique_hashes=None, hash_bytes=8))]
fn merge_dedup_lines(
    input_bytes: Vec<Vec<u8>>,
    unique_hashes: Option<Vec<Vec<u8>>>,
    hash_bytes: usize,
) -> PyResult<(Vec<Vec<u8>>, usize, usize, Vec<Vec<u8>>)> {
    let unique_set: Option<Vec<Vec<u8>>> = unique_hashes;
    let mut seen: Vec<Vec<u8>> = Vec::new();
    let mut total = 0usize;
    let mut cross_skip = 0usize;
    let mut db_skip = 0usize;
    let mut new_hashes: Vec<Vec<u8>> = Vec::new();
    let mut output_lines: Vec<Vec<u8>> = Vec::new();

    for line in &input_bytes {
        let stripped = line
            .strip_suffix(b"\n")
            .or_else(|| line.strip_suffix(b"\r\n"))
            .unwrap_or(line)
            .strip_suffix(b"\r")
            .unwrap_or(line);

        if seen.contains(&stripped.to_vec()) {
            cross_skip += 1;
            continue;
        }

        if let Some(ref db) = unique_set {
            let h = sha1::Sha1::digest(stripped);
            let short = &h[..hash_bytes.min(h.len())];
            if db.contains(&short.to_vec()) {
                db_skip += 1;
                continue;
            }
            new_hashes.push(short.to_vec());
        }

        seen.push(stripped.to_vec());
        total += 1;
        output_lines.push(line.clone());
    }

    Ok((output_lines, cross_skip, db_skip, new_hashes))
}

#[pymodule]
fn rust_scan(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(process_block, m)?)?;
    m.add_function(wrap_pyfunction!(scan_block_rust, m)?)?;
    m.add_function(wrap_pyfunction!(merge_dedup_lines, m)?)?;
    m.add("__version__", "2.0.0")?;
    Ok(())
}
