// 実行方法: line_schedule_bot フォルダで `npm test`（Node.js 18 以上）
// Apps Script のコードを Node の vm で読み込み、Google のサービスは簡単な偽物に差し替えて確かめる。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

if (process.env.TZ !== 'Asia/Tokyo') {
  throw new Error('TZ=Asia/Tokyo で実行してください（npm test なら自動で設定されます）');
}

function loadBot(props = {}) {
  const pushed = [];
  const context = vm.createContext({
    console,
    PropertiesService: {
      getScriptProperties: () => ({ getProperty: (k) => (k in props ? props[k] : null) }),
    },
  });
  for (const file of ['Parser.js', 'Main.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'src', file), 'utf8'), context, { filename: file });
  }
  // 保存先と LINE 送信をメモリ上の偽物に差し替える
  vm.runInContext(`
    var memoryEvents = [];
    var nextId = 1;
    getStore_ = () => ({
      listAll: () => memoryEvents.map((e) => Object.assign({}, e)),
      listByChat: (chatId) => memoryEvents.filter((e) => e.chatId === chatId).map((e) => Object.assign({}, e)),
      add: (ev) => { const id = nextId++; memoryEvents.push(Object.assign({}, ev, { id })); return id; },
      remove: (chatId, ids) => {
        const hit = memoryEvents.filter((e) => e.chatId === chatId && ids.indexOf(e.id) >= 0);
        memoryEvents = memoryEvents.filter((e) => hit.indexOf(e) < 0);
        return hit;
      },
      removeBefore: (date) => { memoryEvents = memoryEvents.filter((e) => e.start >= date); },
      markReminded: (ids) => memoryEvents.forEach((e) => { if (ids.indexOf(e.id) >= 0) e.reminded = true; }),
    });
    getDisplayName_ = () => 'たろう';
  `, context);
  context.pushText_ = (to, text) => pushed.push({ to, text });
  vm.runInContext('pushText_ = this.pushText_;', context);
  return { ctx: context, run: (code) => vm.runInContext(code, context), pushed };
}

const bot = loadBot();
// 2026/10/15(木) 10:00
const NOW = new Date(2026, 9, 15, 10, 0);
const parse = (text, now = NOW) => bot.ctx.parseEventText_(text, now);
const ymdhm = (d) => [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()];

test('日付と時刻を読み取る', () => {
  const cases = [
    ['10/20 14:00 歯医者', [2026, 10, 20, 14, 0], '歯医者'],
    ['１０／２０　１４：３０　歯医者', [2026, 10, 20, 14, 30], '歯医者'],
    ['10月20日 14時半 歯医者', [2026, 10, 20, 14, 30], '歯医者'],
    ['2027/1/5 9時5分 初詣', [2027, 1, 5, 9, 5], '初詣'],
    ['2027-01-05 9:00 初詣', [2027, 1, 5, 9, 0], '初詣'],
    ['明日 9時 会議', [2026, 10, 16, 9, 0], '会議'],
    ['あさって 午後3時 打ち合わせ', [2026, 10, 17, 15, 0], '打ち合わせ'],
    ['今日 夜8時から飲み会', [2026, 10, 15, 20, 0], '飲み会'],
    ['金曜 19:00 飲み会', [2026, 10, 16, 19, 0], '飲み会'],
    ['木曜日 19:00 今日', [2026, 10, 15, 19, 0], '今日'],
    ['来週月曜 10:00 面談', [2026, 10, 19, 10, 0], '面談'],
    ['今週の日曜 10:00 掃除', [2026, 10, 18, 10, 0], '掃除'],
    ['15:00 電話', [2026, 10, 15, 15, 0], '電話'],
    ['9:00 電話', [2026, 10, 16, 9, 0], '電話'], // 今日の9時は過ぎている → 明日
    ['10/20 14:00~15:30 ミーティング', [2026, 10, 20, 14, 0], '~15:30 ミーティング'],
  ];
  for (const [text, expected, title] of cases) {
    const r = parse(text);
    assert.ok(r && !r.error, text + ' → ' + JSON.stringify(r));
    assert.deepEqual(ymdhm(r.start), expected, text);
    assert.equal(r.allDay, false, text);
    assert.equal(r.title, title, text);
  }
});

test('時刻がなければ終日、過ぎた月日は来年', () => {
  let r = parse('12/24 クリスマス');
  assert.equal(r.allDay, true);
  assert.deepEqual(ymdhm(r.start), [2026, 12, 24, 0, 0]);
  r = parse('1/5 仕事始め');
  assert.deepEqual(ymdhm(r.start), [2027, 1, 5, 0, 0]);
  r = parse('2/29 うるう日');
  assert.deepEqual(ymdhm(r.start), [2028, 2, 29, 0, 0]);
});

test('予定ではない文・おかしな日時', () => {
  assert.equal(parse('こんにちは'), null);
  assert.equal(parse('金沢に行きたい'), null);
  assert.equal(parse('3人で食事'), null);
  assert.ok(parse('2/30 歯医者').error);
  assert.ok(parse('10/20 25:00 歯医者').error);
  assert.ok(parse('10/20 14:00').error); // 内容がない
});

test('1対1トーク: 登録・一覧・削除', () => {
  const user = { type: 'user', userId: 'U1' };
  const other = { type: 'user', userId: 'U2' };
  const say = (text, src = user) => bot.ctx.handleText_(text, src, NOW);

  assert.match(say('10/20 14:00 歯医者'), /登録しました\n\[1\] 10\/20\(火\) 14:00 歯医者\n⏰ 30分前/);
  assert.match(say('予定 明日 誕生日'), /登録しました\n\[2\] 10\/16\(金\) 終日 誕生日$/);
  assert.match(say('今日 9:00 朝会'), /過去の日時/);
  assert.match(say('なにか'), /読み取れませんでした/);
  assert.match(say('ヘルプ'), /使い方/);

  const list = say('一覧');
  assert.match(list, /これからの予定（2件）/);
  assert.ok(list.indexOf('■ 10/16(金)') < list.indexOf('■ 10/20(火)'));
  assert.match(say('明日'), /明日の予定.*（1件）/);
  assert.match(say('今日'), /予定はありません/);

  // ほかの人の予定は見えないし消せない
  assert.match(say('一覧', other), /予定はありません/);
  assert.match(say('削除 1', other), /見つかりませんでした/);

  assert.match(say('削除 1 99'), /削除しました\n\[1\] 10\/20\(火\) 14:00 歯医者\n\n番号 99 の予定は見つかりませんでした/);
  assert.match(say('一覧'), /（1件）/);
  assert.match(say('削除'), /番号を/);
});

test('グループ: 普段の会話には反応せず「予定」付きで登録', () => {
  const group = { type: 'group', groupId: 'G1', userId: 'U1' };
  const say = (text) => bot.ctx.handleText_(text, group, NOW);

  assert.equal(say('明日 9時 集合ね'), null);
  assert.equal(say('明日'), null);
  assert.equal(say('今日は暑い'), null);
  assert.match(say('予定 明日 9時 集合'), /登録しました/);
  assert.match(say('予定 ごはん'), /読み取れませんでした/);
  assert.match(say('明日の予定'), /9:00 集合（たろう）/);
  assert.match(say('予定 明日'), /9:00 集合/);
  assert.match(say('一覧'), /9:00 集合/);

  const loose = loadBot({ GROUP_REQUIRE_PREFIX: 'false' });
  assert.match(loose.ctx.handleText_('明日 9時 集合', group, NOW), /登録しました/);
});

test('リマインドと毎朝の通知', () => {
  const b = loadBot({ REMIND_MINUTES: '30' });
  const u = { type: 'user', userId: 'U1' };
  b.ctx.handleText_('今日 10:20 電話', u, NOW);
  b.ctx.handleText_('今日 11:00 会議', u, NOW);
  b.ctx.handleText_('今日 ランチ会', u, NOW);
  b.ctx.handleText_('明日 10:10 歯医者', u, NOW);

  const due = b.ctx.findDueReminders_(b.run('getStore_().listAll()'), NOW, 30);
  assert.deepEqual([...due.map((e) => e.title)], ['電話']);

  const digests = b.ctx.buildMorningDigests_(b.run('getStore_().listAll()'), new Date(2026, 9, 15, 7, 0));
  assert.equal(digests.length, 1);
  assert.equal(digests[0].chatId, 'U1');
  assert.equal(digests[0].text, '☀️ おはようございます！今日 10/15(木) の予定です\n・終日 ランチ会\n・10:20 電話\n・11:00 会議');

  assert.equal(b.ctx.findDueReminders_(b.run('getStore_().listAll()'), NOW, 0).length, 0);
});
