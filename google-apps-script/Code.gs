/**
 * Приёмник результатов викторины «Что ты знаешь о Точке роста?» → Google Таблица.
 *
 * БЕЗ сервера, без ключей, без регистрации API — работает бесплатно
 * в связке Apps Script + Google Sheets.
 *
 * ─── УСТАНОВКА ──────────────────────────────────────────────────────
 *  1. Создайте Google Таблицу (docs.google.com → пустая таблица).
 *  2. Меню «Расширения» → «Apps Script».
 *  3. Удалите всё из файла Code.gs и вставьте этот код.
 *  4. Впишите ID таблицы в SHEET_ID (см. ниже — как его узнать).
 *  5. В Apps Script нажмите «Выполнить» → выберите функцию setup.
 *     Она сама создаст шапку. Потребуется один раз дать доступ.
 *  6. «Развернуть» → «Новое развёртывание» →
 *        Тип: Веб-приложение
 *        Кто имеет доступ: Любой
 *  7. Скопируйте ссылку, которая заканчивается на /exec
 *     и впишите её в викторину (см. последний раздел).
 * ────────────────────────────────────────────────────────────────────
 */

// ─────────────── НАСТРОЙКИ ───────────────

// ID таблицы. Он виден в ссылке:
//   https://docs.google.com/spreadsheets/d/1a2b3c4d5e6f7g8h/edit?usp=sharing
//                            ^^^^^^^^^^^^^^^^^^^^^^ вот он
const SHEET_ID = '1xHKN4Bsh_KUsSkShLqXyVcwYG8yLx3MXJX5HliBkRCs';

// Имя листа. Если переименуете — поменяйте и здесь.
const SHEET_NAME = 'Ответы';

// Шапка таблицы
const HEADER = [
  'Дата и время', 'Класс', 'Участник', 'Баллы', 'Максимум',
  'Время (сек)', 'Время прохождения'
];


// ─────────────── СЛУЖЕБНОЕ ───────────────

function mmss(sec) {
  sec = Math.round(Number(sec) || 0);
  const m = Math.floor(sec / 60);
  return m + ' мин ' + String(sec % 60).padStart(2, '0') + ' сек';
}

function sheet_() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  return sh;
}

// Создать шапку. Запустите один раз вручную.
function setup() {
  const sh = sheet_();
  sh.getRange(1, 1, 1, HEADER.length).setValues([HEADER]);
  sh.getRange(1, 1, 1, HEADER.length)
    .setFontWeight('bold').setBackground('#e8f5e9');
  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, HEADER.length);
  return 'Готово: лист «' + sh.getName() + '», шапка создана.';
}

// Проверка: GET https://адрес/exec покажет, что приёмник жив.
function doGet() {
  try {
    const n = sheet_().getLastRow() - 1;
    return ContentService
      .createTextOutput('Приёмник работает. Ответов в таблице: ' + n)
      .setMimeType(ContentService.MimeType.TEXT);
  } catch (e) {
    return ContentService
      .createTextOutput('Ошибка: ' + e.message)
      .setMimeType(ContentService.MimeType.TEXT);
  }
}

// Приём результата.
function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);

    if (!d.name) throw new Error('не передано имя');

    sheet_().appendRow([
      String(d.ts || ''),
      String(d.cls || ''),
      String(d.name).slice(0, 80),
      Number(d.score) || 0,
      Number(d.total) || 0,
      Math.round(Number(d.secs) || 0),
      mmss(d.secs)
    ]);

    return ContentService
      .createTextOutput('ok')
      .setMimeType(ContentService.MimeType.TEXT);
  } catch (err) {
    return ContentService
      .createTextOutput('error: ' + err.message)
      .setMimeType(ContentService.MimeType.TEXT);
  }
}