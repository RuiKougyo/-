/**
 * 予定テキストの読み取りと日付の表示（LINEやスプレッドシートには依存しない部分）
 *
 * 読み取れる書き方の例:
 *   10/20 14:00 歯医者      10月20日 14時半 歯医者    2026/10/20 歯医者（終日）
 *   明日 9時 会議            あさって 午後3時 打ち合わせ
 *   金曜 19:00 飲み会        来週月曜 10:00 面談       15:00 電話（日付なし＝今日。過ぎていれば明日）
 */

const WEEKDAYS_ = ['日', '月', '火', '水', '木', '金', '土'];

/** 全角数字・記号を半角にそろえる（長音「ー」はタイトルで使うので変えない） */
function normalizeText_(text) {
  return String(text == null ? '' : text)
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/／/g, '/')
    .replace(/：/g, ':')
    .replace(/[－−]/g, '-')
    .replace(/[〜～]/g, '~')
    .replace(/　/g, ' ')
    .trim();
}

function startOfDay_(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays_(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days,
    date.getHours(), date.getMinutes());
}

/** 実在する日付なら Date、2/30 のような日付なら null */
function makeDate_(year, month, day) {
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null;
  return d;
}

const RELATIVE_DAYS_ = {
  今日: 0, きょう: 0, 本日: 0,
  明日: 1, あした: 1, あす: 1,
  明後日: 2, あさって: 2,
};

/**
 * 先頭の日付部分を読む。
 * 戻り値: null（日付なし） / { error } / { date, rest }
 */
function parseDatePart_(text, now) {
  const today = startOfDay_(now);
  let m;

  if ((m = text.match(/^(今日|きょう|本日|明後日|あさって|明日|あした|あす)/))) {
    return { date: addDays_(today, RELATIVE_DAYS_[m[1]]), rest: text.slice(m[0].length) };
  }

  if ((m = text.match(/^(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})日?/))) {
    const date = makeDate_(+m[1], +m[2], +m[3]);
    if (!date) return { error: '日付が正しくありません: ' + m[0] };
    return { date, rest: text.slice(m[0].length) };
  }

  if ((m = text.match(/^(\d{1,2})[/月](\d{1,2})日?/))) {
    const month = +m[1];
    const day = +m[2];
    let date = makeDate_(now.getFullYear(), month, day);
    if (!date && !(month === 2 && day === 29)) return { error: '日付が正しくありません: ' + m[0] };
    // 年を省略した日付がすでに過ぎていれば来年とみなす（2/29 は次のうるう年まで探す）
    let year = now.getFullYear();
    while (!date || date < today) {
      year += 1;
      date = makeDate_(year, month, day);
      if (year > now.getFullYear() + 8) return { error: '日付が正しくありません: ' + m[0] };
    }
    return { date, rest: text.slice(m[0].length) };
  }

  if ((m = text.match(/^(今週|来週|再来週)?の?([日月火水木金土])曜日?/))) {
    const target = WEEKDAYS_.indexOf(m[2]);
    const dow = today.getDay();
    let date;
    if (!m[1]) {
      date = addDays_(today, (target - dow + 7) % 7); // 今日以降で一番近いその曜日
    } else {
      const monday = addDays_(today, -((dow + 6) % 7)); // 週は月曜はじまり
      const weekOffset = { 今週: 0, 来週: 7, 再来週: 14 }[m[1]];
      date = addDays_(monday, weekOffset + ((target + 6) % 7));
    }
    return { date, rest: text.slice(m[0].length) };
  }

  return null;
}

const TIME_RE_ = /^(午前|午後|朝|夜|夕方)?\s*(\d{1,2})(?::(\d{2})|時(?:(\d{1,2})分|(半))?)/;

/** 先頭の時刻部分を読む。戻り値: null / { error } / { hour, minute, rest } */
function parseTimePart_(text) {
  const m = text.match(TIME_RE_);
  if (!m) return null;
  let hour = +m[2];
  const minute = m[3] != null ? +m[3] : m[4] != null ? +m[4] : m[5] ? 30 : 0;
  if (m[1] === '午後' || m[1] === '夜' || m[1] === '夕方') {
    if (hour < 12) hour += 12;
  } else if (m[1] === '午前' && hour === 12) {
    hour = 0;
  }
  if (hour > 23 || minute > 59) return { error: '時刻が正しくありません: ' + m[0].trim() };
  return { hour, minute, rest: text.slice(m[0].length) };
}

/**
 * 「10/20 14:00 歯医者」のような文を予定として読む。
 * 戻り値:
 *   null                              … 日付も時刻も書かれていない（予定の文ではない）
 *   { error: '...' }                  … 予定の文っぽいが読めない
 *   { start: Date, allDay, title }    … 読めた
 */
function parseEventText_(rawText, now) {
  let text = normalizeText_(rawText);
  let date = null;

  const datePart = parseDatePart_(text, now);
  if (datePart && datePart.error) return datePart;
  if (datePart) {
    date = datePart.date;
    text = datePart.rest.replace(/^\s*(の|、|,)?\s*/, '');
  }

  const timePart = parseTimePart_(text);
  if (timePart && timePart.error) return timePart;
  if (!datePart && !timePart) return null;

  let start;
  let allDay = false;
  let endLabel = '';
  if (timePart) {
    text = timePart.rest;
    // 「14:00~15:00」「14時-16時」の終わりの時刻は内容の頭に残す
    const range = text.match(/^\s*[~\-]\s*((?:午前|午後|夜)?\s*\d{1,2}(?::\d{2}|時(?:\d{1,2}分|半)?))/);
    if (range) {
      endLabel = '~' + range[1].replace(/\s+/g, '') + ' ';
      text = text.slice(range[0].length);
    }
    if (date) {
      start = new Date(date.getFullYear(), date.getMonth(), date.getDate(), timePart.hour, timePart.minute);
    } else {
      // 時刻だけ → 今日。すでに過ぎていれば明日
      start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), timePart.hour, timePart.minute);
      if (start <= now) start = addDays_(start, 1);
    }
  } else {
    start = date;
    allDay = true;
  }

  const title = (endLabel + text.replace(/^\s*(から|より)?\s*/, '')).trim();
  if (!title) return { error: '予定の内容（例：歯医者）も一緒に書いてください。' };
  return { start, allDay, title };
}

function pad2_(n) {
  return (n < 10 ? '0' : '') + n;
}

/** 10/20(火)。今年以外は 2027/1/5(火) */
function formatDate_(date, now) {
  const year = now && date.getFullYear() !== now.getFullYear() ? date.getFullYear() + '/' : '';
  return year + (date.getMonth() + 1) + '/' + date.getDate() + '(' + WEEKDAYS_[date.getDay()] + ')';
}

function formatTime_(event) {
  return event.allDay ? '終日' : event.start.getHours() + ':' + pad2_(event.start.getMinutes());
}

/** 予定を時刻順に並べる（同じ日の終日予定は先頭） */
function compareEvents_(a, b) {
  const diff = a.start - b.start;
  if (diff !== 0) return diff;
  if (a.allDay !== b.allDay) return a.allDay ? -1 : 1;
  return a.id - b.id;
}
