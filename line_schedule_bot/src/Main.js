/**
 * LINE スケジュール管理bot（Google Apps Script 版）
 *
 * - doPost            … LINE からのメッセージを受け取る入口（ウェブアプリとして公開）
 * - checkReminders    … 5分ごとに動き、もうすぐ始まる予定をお知らせする
 * - sendMorningDigest … 毎朝、今日の予定をまとめて送る
 * - setup             … 最初に1回だけ手動で実行する（シート作成・トリガー登録）
 *
 * スクリプトプロパティ（プロジェクトの設定 → スクリプト プロパティ）:
 *   LINE_CHANNEL_ACCESS_TOKEN … 必須。LINE Developers で発行したチャネルアクセストークン（長期）
 *   REMIND_MINUTES            … 何分前にリマインドするか（既定 30。0 でリマインドしない）
 *   MORNING_HOUR              … 毎朝の予定通知の時刻（0〜23、既定 7。-1 で送らない）
 *   GROUP_REQUIRE_PREFIX      … グループでは「予定 」で始まる文だけ登録するか（既定 true）
 */

const SHEET_NAME_ = '予定';
const HEADERS_ = ['ID', 'トークID', '日時', '終日', '内容', '登録者', '登録日時', 'リマインド済み'];
const TIME_ZONE_ = 'Asia/Tokyo';
const MAX_LIST_ITEMS_ = 30;
const LINE_TEXT_LIMIT_ = 5000;

// ───────────────────────── 設定 ─────────────────────────

function getConfig_() {
  const props = PropertiesService.getScriptProperties();
  const intProp = (key, fallback) => {
    const value = props.getProperty(key);
    if (value == null || String(value).trim() === '') return fallback;
    const n = parseInt(value, 10);
    return isNaN(n) ? fallback : n;
  };
  return {
    token: props.getProperty('LINE_CHANNEL_ACCESS_TOKEN'),
    remindMinutes: intProp('REMIND_MINUTES', 30),
    morningHour: intProp('MORNING_HOUR', 7),
    groupRequirePrefix: String(props.getProperty('GROUP_REQUIRE_PREFIX')).toLowerCase() !== 'false',
  };
}

// ───────────────────────── LINE からの受信 ─────────────────────────

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    (body.events || []).forEach((event) => {
      try {
        handleLineEvent_(event);
      } catch (err) {
        console.error(err && err.stack ? err.stack : err);
      }
    });
  } catch (err) {
    console.error(err && err.stack ? err.stack : err);
  }
  return ContentService.createTextOutput('OK');
}

/** ブラウザでURLを開いたときの動作確認用 */
function doGet() {
  return ContentService.createTextOutput('LINEスケジュールbotは動いています。');
}

function handleLineEvent_(event) {
  // 通信エラーなどでLINEが同じイベントを送り直してきた場合は、二重登録しないよう無視する
  if (event.deliveryContext && event.deliveryContext.isRedelivery) return;

  if (event.type === 'follow' || event.type === 'join') {
    replyText_(event.replyToken, welcomeText_(event.source.type !== 'user'));
    return;
  }
  if (event.type !== 'message' || !event.message || event.message.type !== 'text') return;

  const reply = handleText_(event.message.text, event.source, new Date());
  if (reply) replyText_(event.replyToken, reply);
}

function getChatId_(source) {
  return source.groupId || source.roomId || source.userId;
}

/**
 * 受け取った文に対する返信文を作る。返信しないときは null。
 */
function handleText_(rawText, source, now) {
  const text = normalizeText_(rawText);
  const chatId = getChatId_(source);
  const isGroup = source.type !== 'user';
  const config = getConfig_();
  let m;

  // 頭の「予定」「登録」は付けても付けなくてもよい（「予定 今日」「予定 10/20 歯医者」など）
  let body = text;
  let hasPrefix = false;
  if ((m = text.match(/^(予定|登録|追加)\s*:?\s*([\s\S]+)$/))) {
    body = m[2];
    hasPrefix = true;
  }

  if (/^(ヘルプ|へるぷ|help|使い方|つかいかた)$/i.test(body)) return helpText_(isGroup);

  if (/^(一覧|予定一覧|予定|よてい)$/.test(text) || (hasPrefix && body === '一覧')) {
    return listReply_(chatId, now, startOfDay_(now), null, '📅 これからの予定', isGroup);
  }
  // グループでは普段の会話の「明日」などに反応しないよう「明日の予定」「予定 明日」の形だけ受け付ける
  if ((m = body.match(/^(今日|きょう|明日|あした|今週|1週間)(の?予定)?$/)) &&
      (!isGroup || hasPrefix || m[2] || !config.groupRequirePrefix)) {
    const today = startOfDay_(now);
    if (m[1] === '今日' || m[1] === 'きょう') {
      return listReply_(chatId, now, today, addDays_(today, 1), '📅 今日の予定 ' + formatDate_(today), isGroup);
    }
    if (m[1] === '明日' || m[1] === 'あした') {
      const tomorrow = addDays_(today, 1);
      return listReply_(chatId, now, tomorrow, addDays_(today, 2), '📅 明日の予定 ' + formatDate_(tomorrow), isGroup);
    }
    return listReply_(chatId, now, today, addDays_(today, 7), '📅 今日から1週間の予定', isGroup);
  }

  if ((m = body.match(/^(削除|消去|消して|取消|取り消し|キャンセル)\s*([\s\S]*)$/))) {
    return deleteReply_(chatId, m[2], now);
  }

  // ここから予定の登録
  if (isGroup && config.groupRequirePrefix && !hasPrefix) return null;

  const parsed = parseEventText_(body, now);
  if (!parsed) {
    // グループでは普段の会話に反応しないよう、頭に「予定」が付いたときだけ案内する
    if (isGroup && !hasPrefix) return null;
    return 'ごめんなさい、予定として読み取れませんでした。\n\n' + formatExamples_(isGroup) +
      '\n\n「ヘルプ」と送ると使い方を表示します。';
  }
  if (parsed.error) return '⚠️ ' + parsed.error + '\n\n' + formatExamples_(isGroup);

  const isPast = parsed.allDay ? parsed.start < startOfDay_(now) : parsed.start <= now;
  if (isPast) return '⚠️ 過去の日時は登録できません（' + formatDate_(parsed.start, now) + ' ' + formatTime_(parsed) + '）';

  const event = {
    chatId,
    start: parsed.start,
    allDay: parsed.allDay,
    title: parsed.title,
    createdBy: isGroup ? getDisplayName_(source) : '',
    createdAt: now,
    reminded: false,
  };
  event.id = getStore_().add(event);

  let reply = '✅ 予定を登録しました\n[' + event.id + '] ' + formatDate_(event.start, now) + ' ' +
    formatTime_(event) + ' ' + event.title;
  if (!event.allDay && config.remindMinutes > 0) {
    reply += '\n⏰ ' + config.remindMinutes + '分前にお知らせします';
  }
  return reply;
}

// ───────────────────────── 返信文 ─────────────────────────

function isUpcoming_(event, now) {
  return event.allDay ? event.start >= startOfDay_(now) : event.start >= now;
}

function listReply_(chatId, now, from, to, heading, isGroup) {
  const events = getStore_().listByChat(chatId)
    .filter((ev) => isUpcoming_(ev, now) && ev.start >= from && (!to || ev.start < to))
    .sort(compareEvents_);
  if (events.length === 0) return heading + '\n\n予定はありません。';
  return heading + '（' + events.length + '件）\n' + formatEventList_(events, now, isGroup) +
    '\n\n消すときは「削除 番号」と送ってください。';
}

/** 日付ごとにまとめた一覧 */
function formatEventList_(events, now, showCreator) {
  const lines = [];
  let lastDay = '';
  events.slice(0, MAX_LIST_ITEMS_).forEach((ev) => {
    const day = formatDate_(ev.start, now);
    if (day !== lastDay) {
      lines.push('', '■ ' + day);
      lastDay = day;
    }
    const creator = showCreator && ev.createdBy ? '（' + ev.createdBy + '）' : '';
    lines.push('[' + ev.id + '] ' + formatTime_(ev) + ' ' + ev.title + creator);
  });
  if (events.length > MAX_LIST_ITEMS_) lines.push('', '…ほか ' + (events.length - MAX_LIST_ITEMS_) + '件');
  return lines.join('\n');
}

function deleteReply_(chatId, argText, now) {
  const ids = (argText.match(/\d+/g) || []).map(Number);
  if (ids.length === 0) return '消したい予定の番号を「削除 3」のように送ってください。\n番号は「一覧」で確認できます。';

  const removed = getStore_().remove(chatId, ids);
  const removedIds = removed.map((ev) => ev.id);
  const notFound = ids.filter((id) => removedIds.indexOf(id) < 0);
  const lines = [];
  if (removed.length > 0) {
    lines.push('🗑 予定を削除しました');
    removed.sort(compareEvents_).forEach((ev) => {
      lines.push('[' + ev.id + '] ' + formatDate_(ev.start, now) + ' ' + formatTime_(ev) + ' ' + ev.title);
    });
  }
  if (notFound.length > 0) {
    if (lines.length) lines.push('');
    lines.push('番号 ' + notFound.join(', ') + ' の予定は見つかりませんでした。');
  }
  return lines.join('\n');
}

function formatExamples_(isGroup) {
  const prefix = isGroup ? '予定 ' : '';
  return '【登録のしかた】\n' +
    prefix + '10/20 14:00 歯医者\n' +
    prefix + '明日 9時 会議\n' +
    prefix + '金曜 19:00~21:00 飲み会\n' +
    prefix + '12/24 クリスマス（時刻なし＝終日）';
}

function helpText_(isGroup) {
  return '📘 使い方\n\n' + formatExamples_(isGroup) + '\n\n' +
    '【見る】\n一覧 … これからの予定\n今日 / 明日 / 今週\n\n' +
    '【消す】\n削除 3 … 番号3の予定を削除（「削除 3 5」で複数）\n\n' +
    '【お知らせ】\n時刻つきの予定は少し前にお知らせします。\n毎朝その日の予定もお送りします。' +
    (isGroup ? '\n\n※グループでは、普段の会話と区別するため頭に「予定」を付けて登録してください。' : '');
}

function welcomeText_(isGroup) {
  return (isGroup ? 'グループへの招待' : '友だち追加') +
    'ありがとうございます！\n予定を送ると登録して、時間が近づいたらお知らせします。\n\n' + helpText_(isGroup);
}

// ───────────────────────── 定期実行（トリガー） ─────────────────────────

/** これからリマインドを送るべき予定を返す（時刻つき・未通知・開始まで remindMinutes 分以内） */
function findDueReminders_(events, now, remindMinutes) {
  if (remindMinutes <= 0) return [];
  const limit = now.getTime() + remindMinutes * 60 * 1000;
  return events.filter((ev) => !ev.allDay && !ev.reminded && ev.start.getTime() <= limit);
}

/** 5分ごとに実行 */
function checkReminders() {
  const config = getConfig_();
  const now = new Date();
  const store = getStore_();
  const due = findDueReminders_(store.listAll(), now, config.remindMinutes);
  if (due.length === 0) return;

  groupByChat_(due.filter((ev) => ev.start > now)).forEach((group) => {
    const lines = ['⏰ まもなく予定の時間です'];
    group.events.sort(compareEvents_).forEach((ev) => {
      const minutes = Math.max(1, Math.round((ev.start - now) / 60000));
      lines.push(formatTime_(ev) + ' ' + ev.title + '（あと' + minutes + '分）');
    });
    pushText_(group.chatId, lines.join('\n'));
  });
  // 送信に失敗しても何度も送り直さないよう、まとめて「通知済み」にする（過ぎてしまった予定も含む）
  store.markReminded(due.map((ev) => ev.id));
}

/** その日の予定をトークごとにまとめた送信文を作る */
function buildMorningDigests_(events, now) {
  const today = startOfDay_(now);
  const tomorrow = addDays_(today, 1);
  const todays = events.filter((ev) => ev.start >= today && ev.start < tomorrow);
  return groupByChat_(todays).map((group) => {
    const lines = ['☀️ おはようございます！今日 ' + formatDate_(today) + ' の予定です'];
    group.events.sort(compareEvents_).forEach((ev) => {
      lines.push('・' + formatTime_(ev) + ' ' + ev.title);
    });
    return { chatId: group.chatId, text: lines.join('\n') };
  });
}

/** 毎朝実行 */
function sendMorningDigest() {
  const now = new Date();
  const store = getStore_();
  buildMorningDigests_(store.listAll(), now).forEach((digest) => pushText_(digest.chatId, digest.text));
  // 30日以上前の予定はシートから片付ける
  store.removeBefore(addDays_(startOfDay_(now), -30));
}

function groupByChat_(events) {
  const groups = {};
  const order = [];
  events.forEach((ev) => {
    if (!groups[ev.chatId]) {
      groups[ev.chatId] = { chatId: ev.chatId, events: [] };
      order.push(ev.chatId);
    }
    groups[ev.chatId].events.push(ev);
  });
  return order.map((id) => groups[id]);
}

// ───────────────────────── 初期設定 ─────────────────────────

/** 最初に1回だけ、エディタ上部の関数選択で「setup」を選んで実行してください */
function setup() {
  const config = getConfig_();
  if (!config.token) {
    throw new Error('スクリプトプロパティ LINE_CHANNEL_ACCESS_TOKEN が設定されていません。README の手順3を確認してください。');
  }
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setSpreadsheetTimeZone(TIME_ZONE_);
  getSheet_();

  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (['checkReminders', 'sendMorningDigest'].indexOf(trigger.getHandlerFunction()) >= 0) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  if (config.remindMinutes > 0) {
    ScriptApp.newTrigger('checkReminders').timeBased().everyMinutes(5).create();
  }
  const hour = config.morningHour;
  if (hour >= 0 && hour <= 23) {
    ScriptApp.newTrigger('sendMorningDigest').timeBased().atHour(hour).everyDays(1)
      .inTimezone(TIME_ZONE_).create();
  }
  console.log('セットアップが完了しました。リマインド: ' +
    (config.remindMinutes > 0 ? config.remindMinutes + '分前' : 'なし') +
    ' / 朝の通知: ' + (hour >= 0 && hour <= 23 ? hour + '時台' : 'なし'));
}

// ───────────────────────── 保存先（スプレッドシート） ─────────────────────────

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME_);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME_);
    sheet.getRange(1, 1, 1, HEADERS_.length).setValues([HEADERS_]).setFontWeight('bold');
    sheet.setFrozenRows(1);
    sheet.getRange('C:C').setNumberFormat('yyyy/mm/dd hh:mm');
    sheet.getRange('G:G').setNumberFormat('yyyy/mm/dd hh:mm');
  }
  return sheet;
}

function getStore_() {
  return new SheetStore_(getSheet_());
}

function withLock_(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    return fn();
  } finally {
    lock.releaseLock();
  }
}

class SheetStore_ {
  constructor(sheet) {
    this.sheet = sheet;
  }

  readRows_() {
    const last = this.sheet.getLastRow();
    if (last < 2) return [];
    return this.sheet.getRange(2, 1, last - 1, HEADERS_.length).getValues()
      .map((row, i) => ({
        rowNumber: i + 2,
        id: Number(row[0]),
        chatId: String(row[1]),
        start: new Date(row[2]),
        allDay: row[3] === true || row[3] === 'TRUE',
        title: String(row[4]),
        createdBy: String(row[5]),
        createdAt: row[6],
        reminded: row[7] === true || row[7] === 'TRUE',
      }))
      .filter((ev) => ev.id && ev.chatId && !isNaN(ev.start.getTime()));
  }

  listAll() {
    return this.readRows_();
  }

  listByChat(chatId) {
    return this.readRows_().filter((ev) => ev.chatId === chatId);
  }

  add(event) {
    return withLock_(() => {
      const props = PropertiesService.getScriptProperties();
      const id = parseInt(props.getProperty('NEXT_ID') || '1', 10);
      props.setProperty('NEXT_ID', String(id + 1));
      this.sheet.appendRow([id, event.chatId, event.start, event.allDay, event.title,
        event.createdBy, event.createdAt, false]);
      return id;
    });
  }

  /** 指定トークの予定だけを削除する（ほかのトークの予定は番号が合っても消さない） */
  remove(chatId, ids) {
    return withLock_(() => {
      const targets = this.readRows_().filter((ev) => ev.chatId === chatId && ids.indexOf(ev.id) >= 0);
      this.deleteRows_(targets);
      return targets;
    });
  }

  removeBefore(date) {
    return withLock_(() => {
      this.deleteRows_(this.readRows_().filter((ev) => ev.start < date));
    });
  }

  markReminded(ids) {
    if (ids.length === 0) return;
    withLock_(() => {
      this.readRows_().filter((ev) => ids.indexOf(ev.id) >= 0).forEach((ev) => {
        this.sheet.getRange(ev.rowNumber, 8).setValue(true);
      });
    });
  }

  deleteRows_(events) {
    // 下の行から消すと行番号がずれない
    events.map((ev) => ev.rowNumber).sort((a, b) => b - a)
      .forEach((rowNumber) => this.sheet.deleteRow(rowNumber));
  }
}

// ───────────────────────── LINE への送信 ─────────────────────────

function callLineApi_(method, path, payload) {
  const options = {
    method,
    headers: { Authorization: 'Bearer ' + getConfig_().token },
    muteHttpExceptions: true,
  };
  if (payload) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  const res = UrlFetchApp.fetch('https://api.line.me' + path, options);
  const code = res.getResponseCode();
  if (code !== 200) {
    console.error('LINE API エラー ' + code + ' ' + path + ': ' + res.getContentText());
    return null;
  }
  return res.getContentText();
}

function truncateText_(text) {
  return text.length > LINE_TEXT_LIMIT_ ? text.slice(0, LINE_TEXT_LIMIT_ - 1) + '…' : text;
}

/** 返信（無料。受け取ったメッセージへの返事に使う） */
function replyText_(replyToken, text) {
  if (!replyToken) return;
  callLineApi_('post', '/v2/bot/message/reply', {
    replyToken,
    messages: [{ type: 'text', text: truncateText_(text) }],
  });
}

/** プッシュ送信（リマインド・朝の通知。月の送信数の上限にカウントされる） */
function pushText_(to, text) {
  callLineApi_('post', '/v2/bot/message/push', {
    to,
    messages: [{ type: 'text', text: truncateText_(text) }],
  });
}

/** グループでの「登録者」表示用に名前を取得する（取れなければ空文字） */
function getDisplayName_(source) {
  if (!source.userId) return '';
  const cache = CacheService.getScriptCache();
  const key = 'name_' + source.userId;
  const cached = cache.get(key);
  if (cached != null) return cached;

  let path = '/v2/bot/profile/' + source.userId;
  if (source.groupId) path = '/v2/bot/group/' + source.groupId + '/member/' + source.userId;
  else if (source.roomId) path = '/v2/bot/room/' + source.roomId + '/member/' + source.userId;
  let name = '';
  try {
    const json = callLineApi_('get', path);
    if (json) name = JSON.parse(json).displayName || '';
  } catch (err) {
    console.error(err);
  }
  cache.put(key, name, 21600);
  return name;
}
