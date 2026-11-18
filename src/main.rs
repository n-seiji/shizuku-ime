#![deny(unsafe_code)]
mod cli;
mod composer;
mod config;
mod context;
mod controller;
mod deps;
mod gguf;
mod imk;
mod imk_client;
mod input;
mod judge;
mod keymap;
mod kkc;
mod emoji;
mod english_memory;
mod english_split;
mod loanword;
mod outbound;
mod platform;
mod private_fs;
mod romaji_converter;
mod session;
mod simulate;
mod symbols;
mod tokenizer;
mod trace;
mod translit;

/// 開発用フラグの実行。`CheckMainQueue` 以外は終了コードで抜けるか、戻って main が終わる。
fn run_dev(flag: cli::DevFlag, args: &[String]) {
    let at = |name: &str, off: usize| {
        args.iter()
            .position(|a| a == name)
            .and_then(|i| args.get(i + off))
    };
    let check_preedit = args.iter().any(|a| a == "--check-preedit");
    match flag {
        cli::DevFlag::KkcCheck => std::process::exit(kkc::check::run_cli(
            at("--kkc-check", 1).map(String::as_str),
        )),
        cli::DevFlag::KkcCompare => std::process::exit(kkc::compare::run(args)),
        cli::DevFlag::KkcConvert => std::process::exit(kkc::compare::convert_cli(
            at("--kkc-convert", 1).map_or("", String::as_str),
            at("--kkc-convert", 2)
                .and_then(|s| s.parse().ok())
                .unwrap_or(30),
        )),
        cli::DevFlag::KkcBench => std::process::exit(kkc::compare::bench_cli(
            at("--kkc-bench", 1).map_or("", String::as_str),
        )),
        cli::DevFlag::JudgeBench => {
            simulate::setup_env();
            std::process::exit(judge::bench_cli(
                at("--judge-bench", 1).map_or("", String::as_str),
            ));
        }
        cli::DevFlag::Simulate => simulate::simulate(
            at("--simulate", 1).map_or("", String::as_str),
            check_preedit,
        ),
        cli::DevFlag::SimulateFile => simulate::simulate_file(
            at("--simulate-file", 1).map_or("", String::as_str),
            check_preedit,
        ),
        cli::DevFlag::CheckMainQueue => platform::check_main_queue(),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match cli::classify(&args) {
        cli::Action::Reject(arg) => {
            eprintln!("unknown option: {arg}");
            eprintln!("{}", cli::USAGE);
            std::process::exit(2);
        }
        cli::Action::Dev(flag) => {
            run_dev(flag, &args);
            return;
        }
        cli::Action::LaunchIme => {}
    }

    // preload の背景スレッドが panic しても payload (ユーザー文字列を含みうる) を stderr に出さないよう、先に hook を入れる。
    platform::install_panic_hook();
    config::init(config::Config::from_env());
    judge::preload();
    imk::register_controller();
    imk::run();
}
