//! コマンドライン引数の判定。IME の起動を伴わない純関数だけを置く。
#![forbid(unsafe_code)]

/// 開発用フラグ。`main` が従来の優先順位で分岐する。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DevFlag {
    KkcCheck,
    KkcCompare,
    KkcConvert,
    KkcBench,
    JudgeBench,
    Simulate,
    SimulateFile,
    CheckMainQueue,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    /// IME 本体を起動する。
    LaunchIme,
    /// 開発用フラグを実行する。
    Dev(DevFlag),
    /// 未知の `--` フラグ。IME を起動せず終了コード 2 で終わる。
    Reject(String),
}

/// 知っているフラグ (補助フラグと値つきフラグの名前を含む)。
const KNOWN_FLAGS: &[&str] = &[
    "--kkc-check",
    "--kkc-compare",
    "--kkc-convert",
    "--kkc-bench",
    "--judge-bench",
    "--simulate",
    "--simulate-file",
    "--check-main-queue",
    "--check-preedit",
    "--golden",
    "--limit",
    "--show",
];

/// 次の引数を値として取るフラグ。
const VALUE_FLAGS: &[&str] = &[
    "--kkc-convert",
    "--kkc-bench",
    "--judge-bench",
    "--simulate",
    "--simulate-file",
    "--golden",
    "--limit",
    "--show",
];

/// 使えるフラグの案内 (標準エラー用)。
pub const USAGE: &str = "usage: shizuku [--kkc-check | --kkc-compare | --kkc-convert <reading> | --kkc-bench <reading> | --judge-bench <tsv> | --simulate <keys> | --simulate-file <file> | --check-main-queue] [--check-preedit] [--golden <path>] [--limit <n>] [--show <n>]";

/// `args` は argv[0] を含む。`--` で始まる引数が 1 つでも未知なら拒否する。
/// `--` で始まらない引数 (macOS が渡す `-psn_…` / `-NS…` を含む) は IME 起動を妨げない。
pub fn classify(args: &[String]) -> Action {
    // 値を取るフラグの直後の引数は値なので、`--` で始まっていても調べない (`--simulate '--'` は打鍵列)。
    let is_value = |i: usize| i > 0 && VALUE_FLAGS.contains(&args[i - 1].as_str());
    let unknown = |(i, a): &(usize, &String)| {
        a.starts_with("--") && !KNOWN_FLAGS.contains(&a.as_str()) && !is_value(*i)
    };
    if let Some((_, bad)) = args.iter().enumerate().skip(1).find(unknown) {
        return Action::Reject(bad.clone());
    }
    const ORDER: &[(&str, DevFlag)] = &[
        ("--kkc-check", DevFlag::KkcCheck),
        ("--kkc-compare", DevFlag::KkcCompare),
        ("--kkc-convert", DevFlag::KkcConvert),
        ("--kkc-bench", DevFlag::KkcBench),
        ("--judge-bench", DevFlag::JudgeBench),
        ("--simulate", DevFlag::Simulate),
        ("--simulate-file", DevFlag::SimulateFile),
        ("--check-main-queue", DevFlag::CheckMainQueue),
    ];
    for (name, flag) in ORDER {
        if args.iter().any(|a| a == name) {
            return Action::Dev(*flag);
        }
    }
    Action::LaunchIme
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn no_args_launches_ime() {
        assert_eq!(classify(&v(&["shizuku"])), Action::LaunchIme);
        assert_eq!(classify(&[]), Action::LaunchIme);
    }

    #[test]
    fn a_value_that_starts_with_two_hyphens_is_not_a_flag() {
        assert_eq!(
            classify(&v(&["shizuku", "--simulate", "--"])),
            Action::Dev(DevFlag::Simulate)
        );
        assert_eq!(
            classify(&v(&[
                "shizuku",
                "--simulate",
                "--a<enter>",
                "--check-preedit"
            ])),
            Action::Dev(DevFlag::Simulate)
        );
        assert_eq!(
            classify(&v(&["shizuku", "--simulate", "a", "--bogus"])),
            Action::Reject("--bogus".to_string())
        );
        assert_eq!(
            classify(&v(&["shizuku", "--check-preedit", "--bogus"])),
            Action::Reject("--bogus".to_string())
        );
    }

    #[test]
    fn single_hyphen_and_plain_args_launch_ime() {
        assert_eq!(
            classify(&v(&["shizuku", "-psn_0_12345"])),
            Action::LaunchIme
        );
        assert_eq!(
            classify(&v(&["shizuku", "-NSDocumentRevisionsDebugMode", "YES"])),
            Action::LaunchIme
        );
        assert_eq!(classify(&v(&["shizuku", "-"])), Action::LaunchIme);
        assert_eq!(classify(&v(&["shizuku", "foo"])), Action::LaunchIme);
    }

    #[test]
    fn every_dev_flag_is_dispatched() {
        for (flag, want) in [
            ("--kkc-check", DevFlag::KkcCheck),
            ("--kkc-compare", DevFlag::KkcCompare),
            ("--kkc-convert", DevFlag::KkcConvert),
            ("--kkc-bench", DevFlag::KkcBench),
            ("--judge-bench", DevFlag::JudgeBench),
            ("--simulate", DevFlag::Simulate),
            ("--simulate-file", DevFlag::SimulateFile),
            ("--check-main-queue", DevFlag::CheckMainQueue),
        ] {
            assert_eq!(
                classify(&v(&["shizuku", flag])),
                Action::Dev(want),
                "{flag}"
            );
        }
    }

    #[test]
    fn dev_flag_with_values() {
        assert_eq!(
            classify(&v(&["shizuku", "--simulate", "kyouha<space>"])),
            Action::Dev(DevFlag::Simulate)
        );
        assert_eq!(
            classify(&v(&["shizuku", "--simulate", "ab", "--check-preedit"])),
            Action::Dev(DevFlag::Simulate)
        );
        assert_eq!(
            classify(&v(&["shizuku", "--kkc-convert", "きょう", "9"])),
            Action::Dev(DevFlag::KkcConvert)
        );
        assert_eq!(
            classify(&v(&[
                "shizuku",
                "--kkc-compare",
                "--golden",
                "g.gz",
                "--limit",
                "10",
                "--show",
                "3"
            ])),
            Action::Dev(DevFlag::KkcCompare)
        );
    }

    #[test]
    fn unknown_double_hyphen_is_rejected() {
        assert_eq!(
            classify(&v(&["shizuku", "--version"])),
            Action::Reject("--version".into())
        );
        assert_eq!(
            classify(&v(&["shizuku", "--simulat", "x"])),
            Action::Reject("--simulat".into())
        );
        assert_eq!(
            classify(&v(&["shizuku", "--"])),
            Action::Reject("--".into())
        );
        assert_eq!(
            classify(&v(&["shizuku", "--help"])),
            Action::Reject("--help".into())
        );
    }

    #[test]
    fn unknown_flag_after_known_flag_is_rejected() {
        assert_eq!(
            classify(&v(&["shizuku", "--simulate", "a", "--bogus"])),
            Action::Reject("--bogus".into())
        );
        assert_eq!(
            classify(&v(&["shizuku", "--bogus", "--simulate", "a"])),
            Action::Reject("--bogus".into())
        );
    }

    #[test]
    fn check_preedit_alone_launches_ime() {
        assert_eq!(
            classify(&v(&["shizuku", "--check-preedit"])),
            Action::LaunchIme
        );
    }
}
