
function doPost(e) {
  try {
    const payload = parsePayload_(e);
    const sheet = getResultsSheet_();

    sheet.appendRow([
      payload.timestamp || new Date().toISOString(),
      payload.fullName || '',
      payload.email || '',
      Number(payload.scorePercent || 0),
      payload.scoreFraction || '',
      payload.passFail || '',
      payload.timeTaken || '',
      Number(payload.tabSwitches || 0),
      JSON.stringify(payload.breakdown || [])
    ]);

    return jsonResponse_({ success: true });
  } catch (error) {
    return jsonResponse_({
      success: false,
      error: error.message
    });
  }
}

function doGet(e) {
  try {
    const data = {
      success: true,
      results: getResults_()
    };

    if (e && e.parameter && e.parameter.callback) {
      return jsonpResponse_(e.parameter.callback, data);
    }

    return jsonResponse_(data);
  } catch (error) {
    const data = {
      success: false,
      error: error.message,
      results: []
    };

    if (e && e.parameter && e.parameter.callback) {
      return jsonpResponse_(e.parameter.callback, data);
    }

    return jsonResponse_(data);
  }
}

function parsePayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new Error('Missing POST body.');
  }

  const contents = e.postData.contents;
  const payload = JSON.parse(contents);

  if (!payload || typeof payload !== 'object') {
    throw new Error('POST body must be a JSON object.');
  }

  return payload;
}

function getResultsSheet_() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getActiveSheet();

  const headers = [
    'Timestamp',
    'Full Name',
    'Email',
    'Score (%)',
    'Score (fraction)',
    'Pass/Fail',
    'Time Taken',
    'Tab Switches',
    'Per-question breakdown (JSON)'
  ];

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(headers);
    sheet.setFrozenRows(1);
  }

  return sheet;
}

function getResults_() {
  const sheet = getResultsSheet_();
  const values = sheet.getDataRange().getValues();

  if (values.length <= 1) {
    return [];
  }

  const headers = values[0];
  return values.slice(1).map(function(row) {
    const record = {};
    headers.forEach(function(header, index) {
      record[header] = row[index];
    });
    return record;
  });
}

function jsonResponse_(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function jsonpResponse_(callback, data) {
  const safeCallback = String(callback).replace(/[^\w$.]/g, '');
  return ContentService
    .createTextOutput(safeCallback + '(' + JSON.stringify(data) + ');')
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}
