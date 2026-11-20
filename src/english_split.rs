#![forbid(unsafe_code)]

// english_split.rs - 英単語のあとに助詞などが続く打鍵列 (artifactni) を、英単語とかなに分ける。
// かなの単位に頼らず打鍵列を切り直す (artifactwo の two は とぉ ではなく t + を)。

use crate::romaji_converter::RomajiConverter;

/// 英単語の直後に来てよいかなの始まり。include の de や partner の ne を切らないよう、よく使う助詞などに限る。
const TAILS: &[&str] = &[
    "に", "を", "が", "は", "で", "と", "の", "も", "へ", "から", "まで", "より", "って", "する", "して",
    "した", "しま", "され", "させ", "でき",
];

/// 辞書の英単語を頭に使う最小の長さ (Composer::is_typing_english の MIN_LEN と同じ)。
const DICTIONARY_MIN_LEN: usize = 4;

/// 続きの先頭をカタカナ語の読みと見なす最小のかな数 (`starts_with_katakana_word`)。
const KATAKANA_WORD_MIN_KANA: usize = 3;

/// 助詞で始まらない続き (loginjinihiraku の じに…) を許すとき、頭に含まれているべき字。
/// 日本語のローマ字ではほぼ使わない (l, x は小文字かなだけ)。time + い (timei) のような日本語の打ち間違いを切らないための歯止め。
const FOREIGN_LETTERS: [char; 4] = ['l', 'q', 'v', 'x'];

/// 助詞で始まらない続きの打鍵に含まれていたら切らない字。続きが外来語の綴りの一部だと見なす。
const FOREIGN_TAIL_LETTERS: [char; 5] = ['l', 'q', 'v', 'x', 'c'];

/// 前のかなが i 段のとき (きょう, じゃ) に限り続けてよい小さいかな。
const YOUON: [char; 3] = ['ゃ', 'ゅ', 'ょ'];
const I_ROW: [char; 12] = ['き', 'し', 'ち', 'に', 'ひ', 'み', 'り', 'ぎ', 'じ', 'ぢ', 'び', 'ぴ'];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Split {
    pub head: String,
    /// かなの部分の (打鍵, かな) の組。
    pub tail: Vec<(String, String)>,
    /// かなの部分の未確定のローマ字。
    pub pending: String,
}

impl Split {
    /// かなの部分の読み (未確定のローマ字は含めない)。
    pub fn tail_kana(&self) -> String {
        self.tail.iter().map(|(_, kana)| kana.as_str()).collect()
    }

    pub fn display(&self) -> String {
        std::iter::once(self.head.as_str())
            .chain(self.tail.iter().map(|(_, kana)| kana.as_str()))
            .chain(std::iter::once(self.pending.as_str()))
            .collect()
    }
}

/// 打鍵列をかなにした (打鍵, かな) の組と、残ったローマ字。finished なら残りも確定する。
fn convert(raw: &str, finished: bool) -> (Vec<(String, String)>, String) {
    let mut conv = RomajiConverter::new();
    let mut units = Vec::new();
    let mut typed = String::new();
    for ch in raw.chars() {
        typed.push(ch);
        if let Some(kana) = conv.process_input(ch) {
            let carry = conv.buffer();
            let split = typed.strip_suffix(carry).map_or(typed.len(), str::len);
            let rest = typed.split_off(split);
            units.push((std::mem::replace(&mut typed, rest), kana));
        }
    }
    if let Some(kana) = finished.then(|| conv.flush()).flatten() {
        units.push((std::mem::take(&mut typed), kana));
    }
    (units, conv.buffer().to_string())
}

fn has_ascii(units: &[(String, String)]) -> bool {
    units.iter().any(|(_, kana)| kana.chars().any(|c| c.is_ascii_alphabetic()))
}

/// 辞書の英単語を頭に使ってよいか。日本語の打ちかけと紛れないよう 4 文字以上で、かな読みが日本語の語なら使わない。
fn dictionary_head(head: &str, is_word: &impl Fn(&str) -> bool, is_japanese: &impl Fn(&str) -> bool) -> bool {
    head.len() >= DICTIONARY_MIN_LEN && is_word(head) && not_japanese(head, is_japanese)
}

/// 頭のかな読みが日本語の語でないか。かなにしきれない語 (commit の こっみt) は日本語の語になりえない。
fn not_japanese(head: &str, is_japanese: &impl Fn(&str) -> bool) -> bool {
    let (units, pending) = convert(head, true);
    let kana: String = units.iter().map(|(_, k)| k.as_str()).collect();
    has_ascii(&units) || !pending.is_empty() || !is_japanese(&kana)
}

/// 続きのかなが、外来語の綴りの切れ端ではなく日本語として自然か。ぁぃぅぇぉゎは含まず、ゃゅょは i 段のあとだけ。
fn natural_kana(tail: &[(String, String)]) -> bool {
    let mut prev = None;
    for c in tail.iter().flat_map(|(_, kana)| kana.chars()) {
        let small = matches!(c, 'ぁ' | 'ぃ' | 'ぅ' | 'ぇ' | 'ぉ' | 'ゎ');
        let bad_youon = YOUON.contains(&c) && !prev.is_some_and(|p| I_ROW.contains(&p));
        if small || bad_youon {
            return false;
        }
        prev = Some(c);
    }
    true
}

/// 続きのかなの先頭が、辞書にあるカタカナ語の読み (ちぇっく → チェック, ふぁいる, ぺーじ) で、その読みに小さいかな (ぇ ぁ) が含まれ、残りが自然なかなか。
/// 読みは 3 かな以上に限る (ふぁ だけで語と見なさない)。辞書の問い合わせは `has_reading` と同じ (見出しがカタカナ語かどうかは見ない。小さいかなを含む読みは外来語だけ)。
fn starts_with_katakana_word(tail: &[(String, String)], is_reading: &impl Fn(&str) -> bool) -> bool {
    let mut prefix = String::new();
    for (n, (_, kana)) in tail.iter().enumerate() {
        prefix.push_str(kana);
        let unit = [(String::new(), prefix.clone())];
        if prefix.chars().count() >= KATAKANA_WORD_MIN_KANA && !natural_kana(&unit) && is_reading(&prefix) && natural_kana(&tail[n + 1..]) {
            return true;
        }
    }
    false
}

/// raw を 英単語 + 助詞などで始まるかな に分ける。分けられなければ None。
/// 英単語と見なすのは、全体がかなにしきれない (artifact の rt)、英語として確定したことのある語、
/// または辞書の英単語 (4 文字以上。merge, commit) のいずれか。
/// ただし、そのかな読みが日本語の語なら見なさない (made → まで)。辞書の英単語にも確定済みの語 (knows) にも掛ける
/// (done を英語で選んだ後でも donewo を done + を にしない)。かなにしきれない語 (git) は確定済みなら分ける。
/// 上の分け方で見つからず、全体がかなにしきれて、頭に l q v x を含む語 (login) のときに限り、助詞で始まらない続きでも分ける (loginjinihiraku → login + じに…)。
/// 同じ頭 (l q v x を含む語) なら、全体がかなにしきれなくても (null の l)、続きがカタカナ語の読み (3 かな以上で小さいかなを含む。ちぇっく, ふぁいる) で始まり、そのあとが自然なかななら分ける (nulltyekku → null + ちぇっく)。
/// 開発用語の一覧 (`is_dev_word`) の語は、長さやかな読みにかかわらず、続きが助詞などで始まるなら頭にする (gitwo → gitを, tokenga → tokenが)。ただし打鍵全体のかなの先頭が、頭のかなより長い辞書の見出し になるなら (jointo = ジョイント, todonotumari) 頭にしない。
/// 全体がまだ英単語の途中 (informa) なら分けない。
/// 「全体がかなにしきれる」は、打ちかけ (finished でない) なら末尾の未確定ローマ字 (loginj の j) を含んでよい。
/// finished は Enter などで打ち終えたとき。途中なら末尾の未確定ローマ字を許す。
pub fn split(
    raw: &str,
    finished: bool,
    knows: impl Fn(&str) -> bool,
    is_dictionary_word: impl Fn(&str) -> bool,
    is_word_prefix: impl Fn(&str) -> bool,
    is_japanese_reading: impl Fn(&str) -> bool,
    is_dev_word: impl Fn(&str) -> bool,
) -> Option<Split> {
    if raw.len() < 3 || !raw.bytes().all(|b| b.is_ascii_lowercase()) {
        return None;
    }
    let (whole, _) = convert(raw, finished);
    let foreign = has_ascii(&whole);
    let split_at = |i: usize| {
        let (head, rest) = raw.split_at(i);
        let (tail, pending) = convert(rest, finished);
        if has_ascii(&tail) || (finished && !pending.is_empty()) {
            return None;
        }
        let mut prefix = String::new();
        let starts_with_tail = tail.iter().any(|(_, kana)| {
            prefix.push_str(kana);
            TAILS.contains(&prefix.as_str())
        });
        starts_with_tail.then(|| Split { head: head.to_string(), tail, pending })
    };
    // 開発用語の一覧の語は、長さにも かな読みにもよらず頭にする (一覧は、読みが日常の日本語にならない語だけを入れる約束)。
    // ただし打鍵全体のかな (未確定の子音の手前まで) の先頭が、頭のかなより長い辞書の見出しになるなら (jointo = ジョイント, todonotumari = とどのつまり)、見出しをまたぐので頭にしない。
    // 見出しの前方一致 (とどが は とどがわ の先頭) までは見ない: todoga まで英語でなくなるため。打鍵の途中 (todono〜todonotumar) は todoの… で、見出しになった時点 (todonotumari) で日本語に戻る。
    // 全体のかなは 1 回だけ作り (打ちかけでも Enter でも同じ判定になるよう、未確定の n は ん として)、見出しになる長さを覚える。
    let whole_reading = std::cell::OnceCell::new();
    let crosses_headword = |head: &str| {
        // (単位の打鍵の始まる位置, その単位までのかなの数) の並びと、見出しになるかなの数。かなにならない単位 (未確定の子音) の手前まで。
        let (starts, headword_lens): &(Vec<(usize, usize)>, Vec<usize>) = whole_reading.get_or_init(|| {
            let (units, _) = convert(raw, true);
            let (mut at, mut count, mut kana) = (0, 0, String::new());
            let mut starts = Vec::new();
            for (typed, k) in units.iter().take_while(|(_, k)| !k.chars().any(|c| c.is_ascii_alphabetic())) {
                kana.push_str(k);
                count += k.chars().count();
                starts.push((at, count));
                at += typed.len();
            }
            let lens = kana.char_indices().map(|(i, c)| i + c.len_utf8()).filter(|&end| is_japanese_reading(&kana[..end])).map(|end| kana[..end].chars().count()).collect();
            (starts, lens)
        });
        // 頭の打鍵に掛かる単位までが頭のかな (gitwo の two は t が頭にも掛かるので、ぎとぉ までが頭)。
        let head_len = starts.iter().take_while(|(at, _)| *at < head.len()).last().map_or(0, |(_, count)| *count);
        headword_lens.iter().any(|&n| n > head_len)
    };
    let is_word = |head: &str| (is_dev_word(head) && !crosses_headword(head)) || (knows(head) && not_japanese(head, &is_japanese_reading)) || dictionary_head(head, &is_dictionary_word, &is_japanese_reading);
    // 助詞で始まらない続きを許す分け方。外来語の綴りらしい頭と、日本語として自然な続きだけに絞る。
    // 打ちかけの未確定ローマ字 (loginj の j) は、かなにしきれない印にしない。
    // 全体の変換で かな 1 つ分の途中 (leann の lean|n は ん=nn の内側) になる位置では切らない。
    // 全体がかなにしきれない (null の l が ASCII のまま残る) ときは foreign で、続きがカタカナ語で始まる場合 (nulltyekku → null + チェック) に限る。
    let relaxed_at = |boundaries: &[usize], i: usize| {
        let (head, rest) = raw.split_at(i);
        if !boundaries.contains(&i) || !head.contains(FOREIGN_LETTERS) || rest.contains(FOREIGN_TAIL_LETTERS) {
            return None;
        }
        let word = (knows(head) && head.len() >= DICTIONARY_MIN_LEN && not_japanese(head, &is_japanese_reading))
            || dictionary_head(head, &is_dictionary_word, &is_japanese_reading);
        if !word {
            return None;
        }
        let (tail, pending) = convert(rest, finished);
        let has_unit = !tail.is_empty() || !pending.is_empty();
        if has_ascii(&tail) || (finished && !pending.is_empty()) || !has_unit {
            return None;
        }
        // 続きの打鍵そのものが英単語 (fire, fan) やその前方一致なら、カタカナ語として切らない。末尾の未確定の n は、Enter と同じに ん として判定する。
        let katakana_word = !(is_dictionary_word(rest) || is_word_prefix(rest)) && {
            let settled = if pending == "n" { convert(rest, true).0 } else { tail.clone() };
            starts_with_katakana_word(&settled, &is_japanese_reading)
        };
        if !(katakana_word || (!foreign && natural_kana(&tail))) {
            return None;
        }
        Some(Split { head: head.to_string(), tail, pending })
    };
    let relaxed = || {
        if !raw.contains(FOREIGN_LETTERS) || is_word_prefix(raw) || knows(raw) {
            return None;
        }
        let boundaries: Vec<usize> = whole
            .iter()
            .scan(0, |end, (typed, _)| {
                *end += typed.len();
                Some(*end)
            })
            .collect();
        (2..raw.len()).rev().find_map(|i| relaxed_at(&boundaries, i))
    };
    // 語と分かる頭を先に、長い順で試す。語でない頭 (子音で終わる外来の綴り) は短い順で試す。長い順だと
    // artifactwokousinnsite を artifactwokousinn + して と切ってしまうため。
    (2..raw.len())
        .rev()
        .find_map(|i| is_word(&raw[..i]).then(|| split_at(i)).flatten())
        .or_else(|| {
            (2..raw.len()).find_map(|i| {
                let consonant_end = !raw[..i].ends_with(['a', 'i', 'u', 'e', 'o']);
                (consonant_end && foreign).then(|| split_at(i)).flatten()
            })
        })
        .or_else(relaxed)
}

/// 続き全体がこのかなのとき、英単語の綴りでもある (でも demo, まで made, して site) 続きは略語のあとの助詞として分ける。
/// `TAILS` のうち 1 かなの助詞と から まで より って する して した に、短い助詞の組み合わせ (でも とか とも では にも とは のは のも のが のを のに へは へも) を足したもの
/// (`TAILS` の しま / され / させ / でき は含まない)。ので (node) は PCnode / XMLnode と紛れるので入れない。
const PARTICLES: &[&str] = &[
    "に", "を", "が", "は", "で", "と", "の", "も", "へ", "から", "まで", "より", "って", "する", "して", "した", "でも", "とか", "とも", "では",
    "には", "にも", "とは", "のは", "のも", "のが", "のを", "のに", "へは", "へも",
];

/// かなの組 tail が余りなく (pending なし) `PARTICLES` の語になるか。
fn is_particle(tail: &[(String, String)], pending: &str) -> bool {
    let whole: String = tail.iter().map(|(_, kana)| kana.as_str()).collect();
    pending.is_empty() && PARTICLES.contains(&whole.as_str())
}

/// 打鍵 raw が全部かなになり、そのかな全体が `PARTICLES` の語か。
fn stem_is_particle(raw: &str) -> bool {
    let (tail, pending) = convert(raw, false);
    !has_ascii(&tail) && is_particle(&tail, &pending)
}

/// 略語として扱う頭か。大文字の ASCII だけで 2 文字以上 (URL, PC)。大文字 1 文字 (X, T) は含めない。
pub fn is_acronym(head: &str) -> bool {
    head.len() >= 2 && head.bytes().all(|b| b.is_ascii_uppercase())
}

/// 大文字だけの略語 head のあとに小文字の続き tail_raw が打たれたとき、略語 + かな に分ける。分けられなければ None。
/// 続きが助詞など (`TAILS`) で始まり、最後まで全部かなにしきれるときに限る。打ちかけの未確定ローマ字 (urlmok の k) は、小文字の英単語 + 助詞と同じに残して表示する (n だけは ん)。
/// 歯止め: 続き全体が英単語なら切らない (PCmode の mode, XMLnode の node)。略語を小文字にした全体が英単語のときも切らない (NOde。こちらは助詞でも優先しない)。
/// `is_english` は英単語か (`Composer::is_english_word_raw` と同じ基準)。ただし続きが余りなくかなになり、そのかな全体が `PARTICLES` の語なら、続きが英単語でも分ける (PCdemo → PCでも, PCmade → PCまで)。
pub fn split_acronym(head: &str, tail_raw: &str, is_english: impl Fn(&str) -> bool) -> Option<Split> {
    if !is_acronym(head) || tail_raw.is_empty() || !tail_raw.bytes().all(|b| b.is_ascii_lowercase()) {
        return None;
    }
    let (mut tail, mut pending) = convert(tail_raw, false);
    if pending == "n" {
        // 末尾の n だけは、確定で ん になる (小文字の英語分割と同じ)。
        (tail, pending) = convert(tail_raw, true);
    }
    if has_ascii(&tail) {
        return None;
    }
    let mut prefix = String::new();
    let starts_with_tail = tail.iter().any(|(_, kana)| {
        prefix.push_str(kana);
        TAILS.contains(&prefix.as_str())
    });
    if !starts_with_tail {
        return None;
    }
    let particle = is_particle(&tail, &pending);
    // 続き全体が英単語、またはその複数形 (modes, tokens) なら切らない。ただし語幹のかなが助詞 (demos の demo) なら複数形とは見なさない。
    let plural = tail_raw.strip_suffix('s').is_some_and(|stem| is_english(stem) && !stem_is_particle(stem));
    let word = is_english(tail_raw) || plural;
    if is_english(&(head.to_ascii_lowercase() + tail_raw)) || (!particle && word) {
        return None;
    }
    Some(Split { head: head.to_string(), tail, pending })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shown(raw: &str) -> Option<String> {
        split(raw, false, |_| false, |_| false, |_| false, |_| false, |_| false).map(|s| s.display())
    }

    #[test]
    fn 英単語のあとの助詞をかなにする() {
        assert_eq!(shown("artifactni").as_deref(), Some("artifactに"));
        assert_eq!(shown("artifactwotsukau").as_deref(), Some("artifactをつかう"));
        assert_eq!(shown("artifactnisuru").as_deref(), Some("artifactにする"));
    }

    #[test]
    fn 助詞のあとに長い日本語が続いても英単語の直後で分ける() {
        assert_eq!(shown("artifactwokousinnsite").as_deref(), Some("artifactをこうしんして"));
        assert_eq!(dict_split("artifactwokousinnsite", &["artifact"], &[]).as_deref(), Some("artifactをこうしんして"));
        assert_eq!(shown("githubwokousinnsite").as_deref(), Some("githubをこうしんして"));
    }

    #[test]
    fn 途中のローマ字は残して表示する() {
        assert_eq!(shown("artifactnis").as_deref(), Some("artifactにs"));
    }

    #[test]
    fn 打ち終えたら残りのローマ字が変換できないものは分けない() {
        assert_eq!(split("artifactnish", true, |_| false, |_| false, |_| false, |_| false, |_| false), None);
        let done = split("artifactnin", true, |_| false, |_| false, |_| false, |_| false, |_| false).unwrap();
        assert_eq!(done.display(), "artifactにん");
    }

    #[test]
    fn 英単語の中の音は助詞と見なさない() {
        assert_eq!(shown("include"), None);
        assert_eq!(shown("partner"), None);
        assert_eq!(shown("standard"), None);
    }

    #[test]
    fn かなにしきれる日本語は分けない() {
        assert_eq!(shown("kitto"), None);
        assert_eq!(shown("kantanni"), None);
        assert_eq!(shown("kyouhaishaniiku"), None);
    }

    #[test]
    fn 打ちかけの子音があっても日本語は分けない() {
        assert_eq!(shown("saikinnhaz"), None);
        assert_eq!(shown("sakihodohanasitakenndesug"), None);
        assert_eq!(shown("kittok"), None);
    }

    #[test]
    fn 英語として確定したことのある語は母音で終わっても詰まりがなくても分ける() {
        assert_eq!(split("mergeni", false, |w| w == "merge", |_| false, |_| false, |_| false, |_| false).map(|s| s.display()).as_deref(), Some("mergeに"));
        assert_eq!(split("openni", false, |w| w == "open", |_| false, |_| false, |_| false, |_| false).map(|s| s.display()).as_deref(), Some("openに"));
        assert_eq!(split("openni", false, |_| false, |_| false, |_| false, |_| false, |_| false), None);
    }

    fn dict_split(raw: &str, words: &[&str], japanese: &[&str]) -> Option<String> {
        split(raw, false, |_| false, |w| words.contains(&w), |_| false, |k| japanese.contains(&k), |_| false).map(|s| s.display())
    }

    #[test]
    fn 辞書の英単語は母音で終わっても助詞の前で分ける() {
        assert_eq!(dict_split("mergesite", &["merge"], &[]).as_deref(), Some("mergeして"));
        assert_eq!(dict_split("mergeshite", &["merge"], &[]).as_deref(), Some("mergeして"));
        assert_eq!(dict_split("mergeni", &["merge"], &[]).as_deref(), Some("mergeに"));
    }

    #[test]
    fn 辞書の英単語でも読みが日本語の語なら分けない() {
        assert_eq!(dict_split("madeni", &["made"], &["まで"]), None);
        assert_eq!(dict_split("madeni", &["made"], &[]).as_deref(), Some("madeに"));
    }

    /// 開発用語の一覧が words のとき (見出しは じょいんと、とどのつまり だけ) の分けた表示。
    fn dev_split(raw: &str, words: &[&str]) -> Option<String> {
        const READINGS: [&str; 2] = ["じょいんと", "とどのつまり"];
        split(raw, false, |_| false, |_| false, |_| false, |k| READINGS.contains(&k), |w| words.contains(&w)).map(|s| s.display())
    }

    #[test]
    fn 開発用語は3文字でも読みが日本語の語でも英語の頭にする() {
        assert_eq!(dev_split("gitwo", &["git"]).as_deref(), Some("gitを"));
        assert_eq!(dev_split("tokenga", &["token"]).as_deref(), Some("tokenが"));
        assert_eq!(dev_split("apiwo", &["api"]).as_deref(), Some("apiを"));
        assert_eq!(dev_split("jirasite", &["jira"]).as_deref(), Some("jiraして"));
        assert_eq!(dev_split("uvwo", &["uv"]).as_deref(), Some("uvを"));
        // 打鍵全体のかな読みが見出しなら (ジョイント) 頭にしない。
        assert_eq!(dev_split("jointo", &["join"]), None);
        // 見出しをまたぐ切り方もしない (ジョイント + マット、とどのつまり の途中)。
        assert_eq!(dev_split("jointowo", &["join"]), None);
        assert_eq!(dev_split("jointoha", &["join"]), None);
        assert_eq!(dev_split("jointosuru", &["join"]), None);
        assert_eq!(dev_split("todonotumari", &["todo"]), None);
        // 見出しになるまで (todono〜todonotumar) は英語の頭のまま。見出しの前方一致までは見ない (todoga の とどが は とどがわ の先頭)。
        assert_eq!(dev_split("todonotuma", &["todo"]).as_deref(), Some("todoのつま"));
        assert_eq!(dev_split("todonotumar", &["todo"]).as_deref(), Some("todoのつまr"));
        assert_eq!(dev_split("todonotumarinokoto", &["todo"]), None);
        // 頭のかなと同じ長さまでの見出し (とど) では止めない。
        assert_eq!(dev_split("todowo", &["todo"]).as_deref(), Some("todoを"));
        assert_eq!(dev_split("todoga", &["todo"]).as_deref(), Some("todoが"));
    }

    #[test]
    fn 一覧の語すべてが助詞の前で英語の頭になる() {
        let words = crate::loanword::parse_words(include_str!("../resources/dev_words.txt"));
        let lower: Vec<&str> = words.iter().map(String::as_str).filter(|w| w.bytes().all(|b| b.is_ascii_lowercase())).collect();
        assert!(lower.len() > 300 && lower.contains(&"main"));
        for w in &lower {
            for (tail, kana) in [("wo", "を"), ("ga", "が"), ("de", "で"), ("nisuru", "にする")] {
                for finished in [false, true] {
                    // 打鍵全体は見出しでなく、辞書の英単語でも覚えた語でもなくても分ける。
                    let s = split(&format!("{w}{tail}"), finished, |_| false, |_| false, |_| false, |_| false, |x| lower.contains(&x));
                    assert_eq!(s.map(|s| s.display()), Some(format!("{w}{kana}")), "{w}{tail} finished={finished}");
                }
            }
        }
    }

    #[test]
    fn 開発用語でも続きが助詞で始まらなければ分けない() {
        assert_eq!(dev_split("todoke", &["todo"]), None);
        assert_eq!(dev_split("tokei", &["toke"]), None);
        assert_eq!(dev_split("gitai", &["git"]), None);
        assert_eq!(dev_split("wo", &["git"]), None);
    }

    #[test]
    fn 辞書の英単語は4文字未満なら分けない() {
        assert_eq!(dict_split("atoni", &["ato"], &[]), None);
    }

    #[test]
    fn 辞書に無い語や助詞が続かない語は分けない() {
        assert_eq!(dict_split("mergesite", &[], &[]), None);
        assert_eq!(dict_split("merger", &["merge"], &[]), None);
    }

    #[test]
    fn かなにしきれない辞書の語は読みを引かずに分ける() {
        // commit は こっみt になるので、日本語の語かは問わない。
        assert_eq!(dict_split("commitni", &["commit"], &["こっみ"]).as_deref(), Some("commitに"));
    }

    #[test]
    fn 確定済みの語も読みが日本語の語なら分けない() {
        let s = split("madeni", false, |w| w == "made", |_| false, |_| false, |_| true, |_| false);
        assert_eq!(s, None);
        let s = split("donewo", false, |w| w == "done", |_| false, |_| false, |_| true, |_| false);
        assert_eq!(s, None);
    }

    #[test]
    fn 確定済みの語は読みが日本語の語でなければ分ける() {
        let s = split("madeni", false, |w| w == "made", |_| false, |_| false, |_| false, |_| false);
        assert_eq!(s.map(|s| s.display()).as_deref(), Some("madeに"));
        // git は ぎt になり、かなにしきれないので日本語の語になりえない。
        let s = split("gitni", false, |w| w == "git", |_| false, |_| false, |_| true, |_| false);
        assert_eq!(s.map(|s| s.display()).as_deref(), Some("gitに"));
    }

    /// 辞書の語 words と、前方一致の語 prefixes を持つ語彙で分ける。
    fn relaxed(raw: &str, finished: bool, words: &[&str], prefixes: &[&str]) -> Option<String> {
        split(
            raw,
            finished,
            |_| false,
            |w| words.contains(&w),
            |w| prefixes.iter().any(|p| p.starts_with(w)),
            |_| false,
            |_| false,
        )
        .map(|s| s.display())
    }

    #[test]
    fn 助詞で始まらない続きでも外来語らしい頭なら分ける() {
        assert_eq!(relaxed("loginjini", true, &["login"], &["login"]).as_deref(), Some("loginじに"));
        assert_eq!(relaxed("loginjinihiraku", true, &["login"], &["login"]).as_deref(), Some("loginじにひらく"));
        assert_eq!(relaxed("loginkyouha", true, &["login"], &["login"]).as_deref(), Some("loginきょうは"));
    }

    #[test]
    fn 頭に続く打ちかけのローマ字は残して表示する() {
        assert_eq!(relaxed("loginj", false, &["login"], &["login"]).as_deref(), Some("loginj"));
        assert_eq!(relaxed("loginj", true, &["login"], &["login"]), None);
    }

    #[test]
    fn かな1つ分の途中では切らない() {
        // lean|n は ん (nn) の内側。プリエディットと確定結果がずれる。
        assert_eq!(relaxed("leann", false, &["lean"], &["lean"]), None);
    }

    #[test]
    fn 確定したことのある語全体は分けない() {
        let s = split("loginji", false, |w| w == "loginji", |w| w == "login", |_| false, |_| false, |_| false);
        assert_eq!(s, None);
    }

    #[test]
    fn 頭に外来の字が無ければ助詞で始まらない続きは分けない() {
        assert_eq!(relaxed("timei", false, &["time"], &["time"]), None);
        assert_eq!(relaxed("sakeiku", false, &["sake"], &["sake"]), None);
    }

    #[test]
    fn 全体が英単語の途中なら分けない() {
        assert_eq!(relaxed("informa", false, &["inform"], &["information"]), None);
    }

    #[test]
    fn 助詞で始まる分け方があればそちらを使う() {
        assert_eq!(relaxed("lineni", false, &["line", "linen"], &["line", "linen"]).as_deref(), Some("lineに"));
        assert_eq!(relaxed("linksite", false, &["link", "links"], &["link", "links"]).as_deref(), Some("linkして"));
    }

    #[test]
    fn 全体が英単語に見える打鍵列は分けない() {
        assert_eq!(relaxed("playtime", true, &["play", "time"], &["play", "time"]), None);
        assert_eq!(relaxed("lockfile", true, &["lock", "file"], &["lock", "file"]), None);
        assert_eq!(relaxed("filetype", true, &["file", "type"], &["file", "type"]), None);
    }

    #[test]
    fn 小さいかなや外来の字を含む続きは分けない() {
        // fa は ふぁ、la は ぁ になる。
        assert_eq!(relaxed("loginfa", true, &["login"], &["login"]), None);
        assert_eq!(relaxed("loginlo", true, &["login"], &["login"]), None);
        assert_eq!(relaxed("logincha", true, &["login"], &["login"]), None);
    }

    /// 語彙を持たない (どの綴りも英単語でない) まま、略語 + 続きを分けた表示。
    fn acronym(head: &str, tail: &str) -> Option<String> {
        split_acronym(head, tail, |_| false).map(|s| s.display())
    }

    #[test]
    fn 略語のあとの助詞をかなにする() {
        assert_eq!(acronym("URL", "mo").as_deref(), Some("URLも"));
        assert_eq!(acronym("PC", "wo").as_deref(), Some("PCを"));
        assert_eq!(acronym("PR", "no").as_deref(), Some("PRの"));
        assert_eq!(acronym("API", "wotataku").as_deref(), Some("APIをたたく"));
        assert_eq!(acronym("PR", "desu").as_deref(), Some("PRです"));
        assert_eq!(acronym("PC", "womotteitte").as_deref(), Some("PCをもっていって"));
    }

    #[test]
    fn 略語のあとの打ちかけのローマ字は残し_nだけはんにする() {
        assert_eq!(acronym("URL", "mok").as_deref(), Some("URLもk"));
        assert_eq!(acronym("URL", "mon").as_deref(), Some("URLもん"));
    }

    #[test]
    fn 略語のあとが助詞で始まらないか_かなにしきれなければ分けない() {
        for tail in ["s", "m", "name", "server", "data", "kit", "file", "document", "memory", "error"] {
            assert_eq!(acronym("URL", tail), None, "{tail}");
        }
        assert_eq!(acronym("DB", "name"), None);
    }

    #[test]
    fn 略語は大文字2文字以上だけ() {
        assert!(is_acronym("PC") && is_acronym("HTTP"));
        assert!(!is_acronym("X") && !is_acronym("Url") && !is_acronym("pc") && !is_acronym("P1"));
        assert_eq!(acronym("U", "mo"), None);
        assert_eq!(acronym("Url", "mo"), None);
        assert_eq!(acronym("URL", "Mo"), None);
        assert_eq!(acronym("URL", ""), None);
    }

    #[test]
    fn 続き全体が英単語なら略語でも切らない() {
        let words = |w: &str| matches!(w, "mode" | "node" | "today" | "token");
        let shown = |tail: &str| split_acronym("PC", tail, words).map(|s| s.display());
        assert_eq!(shown("mo").as_deref(), Some("PCも"));
        assert_eq!(shown("mod").as_deref(), Some("PCもd"), "語の途中はかな表示");
        assert_eq!(shown("mode"), None);
        assert_eq!(shown("node"), None);
        assert_eq!(shown("today"), None);
        assert_eq!(shown("token"), None);
        assert_eq!(shown("modo").as_deref(), Some("PCもど"));
    }

    #[test]
    fn 英単語でもある助詞の組み合わせは歯止めより分けるほうを優先する() {
        let words = |w: &str| matches!(w, "demo" | "made" | "site" | "kara" | "tomo" | "toka" | "node" | "mode");
        let shown = |tail: &str| split_acronym("PC", tail, words).map(|s| s.display());
        assert_eq!(shown("demo").as_deref(), Some("PCでも"));
        assert_eq!(shown("made").as_deref(), Some("PCまで"));
        assert_eq!(shown("site").as_deref(), Some("PCして"));
        assert_eq!(shown("kara").as_deref(), Some("PCから"));
        assert_eq!(shown("tomo").as_deref(), Some("PCとも"));
        assert_eq!(shown("toka").as_deref(), Some("PCとか"));
        assert_eq!(shown("node"), None, "ので は入れない");
        assert_eq!(shown("mode"), None, "もで は組み合わせにない");
    }

    #[test]
    fn 略語を小文字にした全体が英単語なら切らない() {
        let r = split_acronym("NO", "de", |w| w == "node");
        assert_eq!(r, None);
    }

    /// 辞書の語 words、前方一致の語 prefixes、見出しの読み readings を持つ語彙で、打ち終えたあとに分けた表示。
    fn katakana(raw: &str, words: &[&str], prefixes: &[&str], readings: &[&str]) -> Option<String> {
        split(raw, true, |_| false, |w| words.contains(&w), |w| prefixes.iter().any(|p| p.starts_with(w)), |k| readings.contains(&k), |_| false).map(|s| s.display())
    }

    #[test]
    fn 頭が外来の綴りで続きがカタカナ語なら小さいかなを含んでいても分ける() {
        let readings = ["ちぇっく", "ふぁいる", "ぺーじ"];
        // null / build は全体がかなにしきれない (l, d が残る) が、続きがカタカナ語なら分ける。
        assert_eq!(katakana("nulltyekkuga", &["null"], &["null", "nullable"], &readings).as_deref(), Some("nullちぇっくが"));
        assert_eq!(katakana("nulltyekku", &["null"], &["null", "nullable"], &readings).as_deref(), Some("nullちぇっく"));
        assert_eq!(katakana("buildfairu", &["build"], &["build", "buildfile"], &readings).as_deref(), Some("buildふぁいる"));
        assert_eq!(katakana("loginpe-zi", &["login"], &["login"], &readings), None, "- は英語分割の対象外");
        // 全体がかなにしきれる頭 (login) でも、小さいかなを含む続きが語なら分ける。
        assert_eq!(katakana("loginfairu", &["login"], &["login"], &readings).as_deref(), Some("loginふぁいる"));
    }

    #[test]
    fn 続きがカタカナ語の読みで始まらなければ小さいかなを含む続きは今までどおり分けない() {
        let readings = ["ちぇっく", "ふぁいる"];
        // 読みが見出しにない、または 3 かな未満 (ふぁ)。
        assert_eq!(katakana("nulltyekku", &["null"], &["null"], &[]), None);
        assert_eq!(katakana("loginfa", &["login"], &["login"], &["ふぁ"]), None);
        assert_eq!(katakana("loginfa", &["login"], &["login"], &readings), None);
        // 頭に l q v x が無い語 (test, api) は対象外。
        assert_eq!(katakana("testkeesu", &["test"], &["test"], &["けえす"]), None);
        assert_eq!(katakana("apifairu", &["api"], &["api"], &readings), None);
        // 全体が英単語の綴り (nullable, buildfile) のままなら分けない。
        assert_eq!(katakana("nullable", &["null"], &["null", "nullable"], &readings), None);
        assert_eq!(katakana("buildfile", &["build", "file"], &["build", "buildfile"], &readings), None);
        // 続きが読みのあとに小さいかなを残すなら分けない。
        assert_eq!(katakana("nulltyekkufa", &["null"], &["null"], &readings), None);
    }

    #[test]
    fn 続きの打鍵そのものが英単語か英単語の前方一致ならカタカナ語として切らない() {
        let readings = ["ふぃれ", "ふぁれ", "ふぇあ", "ふぁん", "ふぃん", "ふぁいる"];
        let words = ["wild", "real", "null", "ceiling", "full", "fire", "fare", "fan", "fin", "feature"];
        let prefixes = ["wild", "real", "null", "ceiling", "full", "fire", "fare", "fan", "fin", "feature", "fi", "fil", "file"];
        for raw in ["wildfire", "realfare", "nullfeature", "ceilingfan", "fullfin", "nullfin"] {
            assert_eq!(katakana(raw, &words, &prefixes, &readings), None, "{raw}");
        }
        // 前方一致 (fil → file の途中) でも切らない。
        assert_eq!(katakana("nullfil", &["null"], &["null", "fil"], &["ふぃる"]), None);
        // 英単語でない続きなら切る。
        assert_eq!(katakana("nullfairu", &["null"], &["null"], &readings).as_deref(), Some("nullふぁいる"));
    }

    #[test]
    fn 末尾の未確定のnは打ちかけでも打ち終えても同じに判定する() {
        // loginfan: 打ちかけの ふぁ (2 かな) と n、Enter では ふぁん (3 かな)。どちらも切るか、どちらも切らない。
        let readings = ["ふぁん"];
        let at = |finished: bool| split("loginfan", finished, |_| false, |w| w == "login", |w| "login".starts_with(w), |k| readings.contains(&k), |_| false).map(|s| s.display());
        assert_eq!(at(false).is_some(), at(true).is_some());
        assert_eq!(at(true).as_deref(), Some("loginふぁん"));
        assert_eq!(at(false).as_deref(), Some("loginふぁn"));
    }

    #[test]
    fn 小さいかなを含まない日本語は続きが語でも外来の綴りの全体では分けない() {
        // 全体がかなにしきれない (null の l) とき、続きが自然なかなというだけでは null + こんにちは と分けない (今までどおり子音で終わる頭で分かれる)。
        assert_eq!(katakana("nullkonnnichiha", &["null"], &["null"], &["こんにちは"]).as_deref(), Some("nullkonnにちは"));
    }
}
