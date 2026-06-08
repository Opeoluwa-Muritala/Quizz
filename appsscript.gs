// ══════════════════════════════════════════════════════════════
//  Mainstreet Exam Portal — Google Apps Script
// ══════════════════════════════════════════════════════════════

// ── CONFIG ────────────────────────────────────────────────────
const SHEET_ID = "https://docs.google.com/spreadsheets/d/1vkdOHo9Rrid2CnQOXHPYIRPSE_B84VRM-CA7yw5OAxk/edit?usp=sharing";
const FOLDER_ID = "1ZiobYFlEnIUYq5UEnqjiUTa4v-0DPX2j";
const RESULTS_SHEET_NAME = "Quizz";
const PENDING_SHEET_NAME = "Pending";
const ADMIN_TOKEN = "REPLACE_ME"; // Gated behind this constant

// ══════════════════════════════════════════════════════════════
//  ENTRY POINTS
// ═══════════════════════════════════════════════════════════

function doGet(e) {
  try {
    const action = (e && e.parameter && e.parameter.action) || "";
    const callback = (e && e.parameter && e.parameter.callback) || "";
    
    if (action === "checkEmail") {
      const email = (e && e.parameter && e.parameter.email) || "";
      const duplicate = checkEmailExists_(email);
      const data = { success: true, duplicate: duplicate };
      return callback ? jsonpResponse_(callback, data) : jsonResponse_(data);
      
    } else if (action === "results") {
      const token = (e && e.parameter && e.parameter.token) || "";
      if (token !== ADMIN_TOKEN) {
        const unauthorizedData = { success: false, error: "Unauthorized" };
        return callback ? jsonpResponse_(callback, unauthorizedData) : jsonResponse_(unauthorizedData);
      }
      const results = getResults_();
      const successData = { success: true, results: results };
      return callback ? jsonpResponse_(callback, successData) : jsonResponse_(successData);
      
    } else {
      const defaultData = { success: true, message: "Mainstreet Exam Portal API" };
      return callback ? jsonpResponse_(callback, defaultData) : jsonResponse_(defaultData);
    }
  } catch (error) {
    const errData = { success: false, error: error.message };
    const cb = (e && e.parameter && e.parameter.callback) || "";
    return cb ? jsonpResponse_(cb, errData) : jsonResponse_(errData);
  }
}

function doPost(e) {
  try {
    const payload = parsePayload_(e);
    const action = payload.action || "";
    
    if (action === "submit") {
      const lock = LockService.getScriptLock();
      let lockAcquired = false;
      try {
        lockAcquired = lock.tryLock(8000);
      } catch (err) {}
      
      const row = getRowFromPayload_(payload);
      if (lockAcquired) {
        try {
          const resultsSheet = getResultsSheet_();
          resultsSheet.appendRow(row);
          return jsonResponse_({ success: true, queued: false });
        } finally {
          lock.releaseLock();
        }
      } else {
        const pendingSheet = getPendingSheet_();
        pendingSheet.appendRow(row);
        return jsonResponse_({ success: true, queued: true });
      }
      
    } else if (action === "uploadImage") {
      const email = payload.email || "";
      const type = payload.type || "";
      const imageBase64 = payload.imageBase64 || "";
      if (!imageBase64) {
        throw new Error("Missing imageBase64 content.");
      }
      const decoded = Utilities.base64Decode(imageBase64);
      const name = type + "_" + sanitizeFilename_(email) + "_" + Date.now() + ".jpg";
      const folder = getOrCreateFolder_("Exam Verifications");
      const file = folder.createFile(Utilities.newBlob(decoded, "image/jpeg", name));
      file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      return jsonResponse_({
        success: true,
        fileId: file.getId(),
        url: file.getUrl()
      });
      
    } else if (action === "updateFileIds") {
      const updated = updateFileIdsInSheet_(getResultsSheet_(), payload.email, payload.selfieFileId, payload.idCardFileId);
      if (!updated) {
        updateFileIdsInSheet_(getPendingSheet_(), payload.email, payload.selfieFileId, payload.idCardFileId);
      }
      return jsonResponse_({ success: true });
      
    } else if (action === "flush") {
      const flushed = flushPending_();
      return jsonResponse_({ success: true, flushed: flushed });
      
    } else {
      return jsonResponse_({ success: false, error: "Unknown action: " + action });
    }
  } catch (error) {
    return jsonResponse_({ success: false, error: error.message });
  }
}

// ══════════════════════════════════════════════════════════════
//  TRIGGER AND FLUSH LOGIC
// ══════════════════════════════════════════════════════════════

function setupFlushTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    const funcName = triggers[i].getHandlerFunction();
    if (funcName === "flushPending" || funcName === "flushPending_") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger("flushPending")
    .timeBased()
    .everyMinutes(1)
    .create();
}

function flushPending() {
  flushPending_();
}

function flushPending_() {
  const properties = PropertiesService.getScriptProperties();
  const isRunning = properties.getProperty("FLUSH_RUNNING");
  if (isRunning === "true") {
    Logger.log("Flush already running, skipping.");
    return 0;
  }
  
  properties.setProperty("FLUSH_RUNNING", "true");
  const lock = LockService.getScriptLock();
  let lockAcquired = false;
  try {
    lockAcquired = lock.tryLock(30000);
    if (!lockAcquired) {
      Logger.log("Could not acquire lock for flushing.");
      return 0;
    }
    
    const pendingSheet = getPendingSheet_();
    const lastRow = pendingSheet.getLastRow();
    if (lastRow <= 1) {
      return 0;
    }
    
    const rowsToDrain = Math.min(50, lastRow - 1);
    const range = pendingSheet.getRange(2, 1, rowsToDrain, 11);
    const values = range.getValues();
    
    const resultsSheet = getResultsSheet_();
    const nextRow = resultsSheet.getLastRow() + 1;
    resultsSheet.getRange(nextRow, 1, rowsToDrain, 11).setValues(values);
    
    pendingSheet.deleteRows(2, rowsToDrain);
    return rowsToDrain;
  } finally {
    properties.setProperty("FLUSH_RUNNING", "false");
    if (lockAcquired) {
      try {
        lock.releaseLock();
      } catch (err) {}
    }
  }
}

// ══════════════════════════════════════════════════════════════
//  SHEET HELPERS
// ═══════════════════════════════════════════════════════════

function getResultsSheet_() {
  return getOrCreateSheetByName_(RESULTS_SHEET_NAME);
}

function getPendingSheet_() {
  return getOrCreateSheetByName_(PENDING_SHEET_NAME);
}

function getOrCreateSheetByName_(name) {
  let ss;
  const idStr = String(SHEET_ID).trim();
  if (idStr.indexOf("http") === 0) {
    ss = SpreadsheetApp.openByUrl(idStr);
  } else {
    ss = SpreadsheetApp.openById(idStr);
  }
  let sheet = ss.getSheetByName(name);
  const headers = [
    "Timestamp",
    "Full Name",
    "Email",
    "Score (%)",
    "Score (fraction)",
    "Pass/Fail",
    "Time Taken",
    "Tab Switches",
    "Per-question breakdown (JSON)",
    "Selfie File ID",
    "ID Card File ID"
  ];
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(headers);
    const headerRange = sheet.getRange(1, 1, 1, headers.length);
    headerRange.setFontWeight("bold");
    headerRange.setBackground("#4c1d95");
    headerRange.setFontColor("#ffffff");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function checkEmailExists_(email) {
  if (!email) return false;
  const normalized = normalizeEmail_(email);
  
  const resultsSheet = getResultsSheet_();
  const lastRowResults = resultsSheet.getLastRow();
  if (lastRowResults > 1) {
    const emailsResults = resultsSheet.getRange(2, 3, lastRowResults - 1, 1).getValues();
    for (let i = 0; i < emailsResults.length; i++) {
      if (normalizeEmail_(emailsResults[i][0]) === normalized) {
        return true;
      }
    }
  }
  
  const pendingSheet = getPendingSheet_();
  const lastRowPending = pendingSheet.getLastRow();
  if (lastRowPending > 1) {
    const emailsPending = pendingSheet.getRange(2, 3, lastRowPending - 1, 1).getValues();
    for (let j = 0; j < emailsPending.length; j++) {
      if (normalizeEmail_(emailsPending[j][0]) === normalized) {
        return true;
      }
    }
  }
  
  return false;
}

function getResults_() {
  const sheet = getResultsSheet_();
  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) return [];
  const headers = values[0];
  return values.slice(1).map(function(row) {
    const record = {};
    headers.forEach(function(header, index) {
      record[header] = row[index];
    });
    return record;
  });
}

function updateFileIdsInSheet_(sheet, email, selfieFileId, idCardFileId) {
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) return false;
  const emails = sheet.getRange(2, 3, lastRow - 1, 1).getValues();
  for (let i = emails.length - 1; i >= 0; i--) {
    if (normalizeEmail_(emails[i][0]) === normalizeEmail_(email)) {
      const rowIndex = i + 2;
      if (selfieFileId) {
        sheet.getRange(rowIndex, 10).setValue(selfieFileId);
      }
      if (idCardFileId) {
        sheet.getRange(rowIndex, 11).setValue(idCardFileId);
      }
      return true;
    }
  }
  return false;
}

// ══════════════════════════════════════════════════════════════
//  DRIVE HELPERS
// ══════════════════════════════════════════════════════════════

function getOrCreateFolder_(name) {
  const folders = DriveApp.getFoldersByName(name);
  if (folders.hasNext()) {
    return folders.next();
  }
  const folder = DriveApp.createFolder(name);
  folder.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return folder;
}

// ══════════════════════════════════════════════════════════════
//  UTILITY HELPERS
// ══════════════════════════════════════════════════════════════

function parsePayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new Error("Missing POST body.");
  }
  const payload = JSON.parse(e.postData.contents);
  if (!payload || typeof payload !== "object") {
    throw new Error("POST body must be a JSON object.");
  }
  return payload;
}

function getRowFromPayload_(payload) {
  return [
    payload.timestamp || new Date().toISOString(),
    payload.fullName || "",
    normalizeEmail_(payload.email),
    Number(payload.scorePercent || 0),
    payload.scoreFraction || "",
    payload.passFail || "",
    payload.timeTaken || "",
    Number(payload.tabSwitches || 0),
    JSON.stringify(payload.breakdown || []),
    payload.selfieFileId || "",
    payload.idCardFileId || ""
  ];
}

function normalizeEmail_(email) {
  return String(email || "").trim().toLowerCase();
}

function sanitizeFilename_(str) {
  return String(str).replace(/[^a-zA-Z0-9._-]/g, "_").substring(0, 60);
}

function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function jsonpResponse_(callback, data) {
  const safeCallback = String(callback).replace(/[^\w$.]/g, "");
  return ContentService
    .createTextOutput(safeCallback + "(" + JSON.stringify(data) + ");")
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}