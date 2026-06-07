// ══════════════════════════════════════════════════════════════
//  Mainstreet Exam Portal — Google Apps Script
//  Handles: photo upload to Drive, result saving to Sheet,
//           duplicate email check, script-level locking
// ══════════════════════════════════════════════════════════════

// ── CONFIG ────────────────────────────────────────────────────
var SHEET_ID   = "https://docs.google.com/spreadsheets/d/1vkdOHo9Rrid2CnQOXHPYIRPSE_B84VRM-CA7yw5OAxk/edit?usp=sharing";   
var FOLDER_ID  = "1ZiobYFlEnIUYq5UEnqjiUTa4v-0DPX2j";
var SHEET_NAME = "Quizz";
// ─────────────────────────────────────────────────────────────

var RESULTS_HEADERS = [
  "Timestamp",
  "Full Name",
  "Email",
  "Score (%)",
  "Score (fraction)",
  "Pass/Fail",
  "Time Taken",
  "Tab Switches",
  "Per-question breakdown (JSON)",
  "Selfie URL",
  "ID Card URL",
  "Status"
];


// ══════════════════════════════════════════════════════════════
//  ENTRY POINTS
// ══════════════════════════════════════════════════════════════

/**
 * Handles all incoming POST requests from the quiz frontend.
 * Dispatches by payload.action:
 *   "uploadPhotos" — saves selfie + ID to Drive, writes placeholder row
 *   "saveResults"  — fills in score columns on the existing row (or appends)
 */
function doPost(e) {
  var lock = LockService.getScriptLock();

  try {
    lock.waitLock(10000);

    var payload = parsePayload_(e);
    var action  = payload.action || "";
    var callback = (e && e.parameter && e.parameter.callback) || "";

    var result;
    if (action === "uploadPhotos") {
      result = handleUploadPhotos_(payload);
    } else if (action === "saveResults") {
      result = handleSaveResults_(payload);
    } else {
      result = { success: false, error: "Unknown action: " + action };
    }

    // Support JSONP fallback for POSTs when caller provides a callback query param
    return callback ? jsonpResponse_(callback, result) : jsonResponse_(result);

  } catch (err) {
    var cb = (e && e.parameter && e.parameter.callback) || "";
    var errData = { success: false, error: err.message };
    return cb ? jsonpResponse_(cb, errData) : jsonResponse_(errData);

  } finally {
    try { lock.releaseLock(); } catch (e2) {}
  }
}


/**
 * Handles GET requests.
 *   ?action=getEmails  — returns submitted emails (for frontend dupe check)
 *   ?action=getResults — returns full results array
 *   ?callback=fn       — wraps response in JSONP
 */
function doGet(e) {
  try {
    var action   = (e && e.parameter && e.parameter.action)   || "";
    var callback = (e && e.parameter && e.parameter.callback) || "";
    var data;

    if (action === "getEmails") {
      var sheet  = getOrCreateSheet_();
      var values = sheet.getDataRange().getValues();
      var emails = [];

      // Row 0 is header; email is column index 2
      for (var i = 1; i < values.length; i++) {
        var email = normalizeEmail_(values[i][2]);
        if (email) emails.push({ email: email });
      }

      data = { success: true, results: emails };

    } else if (action === "getResults") {
      data = { success: true, results: getResults_() };

    } else {
      data = { success: true, message: "Mainstreet Exam Portal API" };
    }

    return callback
      ? jsonpResponse_(callback, data)
      : jsonResponse_(data);

  } catch (err) {
    var errData = { success: false, error: err.message, results: [] };
    var cb = (e && e.parameter && e.parameter.callback) || "";
    return cb ? jsonpResponse_(cb, errData) : jsonResponse_(errData);
  }
}


// ══════════════════════════════════════════════════════════════
//  ACTION HANDLERS
// ══════════════════════════════════════════════════════════════

/**
 * Run this once from the Apps Script editor after adding/updating scopes.
 * It forces Google to show the Spreadsheet + Drive authorization prompt.
 */
function authorizeStorage_() {
  getOrCreateSheet_();
  try {
    var folder = getOrCreateUploadFolder_(FOLDER_ID, "Mainstreet Exam Photos");
    Logger.log("Folder ready! Name: " + folder.getName() + " | ID: " + folder.getId() + " | URL: " + folder.getUrl());
  } catch (e) {
    Logger.log("Drive folder access error: " + e.message);
  }
  return "Storage authorization OK";
}

/**
 * Phase 1 — called right before the quiz starts.
 * Rejects duplicates, uploads photos to Drive, writes a
 * placeholder row with Status = "photos_uploaded".
 */
function handleUploadPhotos_(payload) {
  var sheet = getOrCreateSheet_();
  var email = normalizeEmail_(payload.email);

  // Duplicate guard — reject if a completed row already exists
  if (hasCompletedSubmission_(sheet, email)) {
    return jsonResponse_({
      success:   false,
      duplicate: true,
      message:   "This email has already completed the exam."
    });
  }

  var folder = getOrCreateUploadFolder_(FOLDER_ID, "Mainstreet Exam Photos");
  var selfieUrl = "";
  var idUrl     = "";
  var slug      = sanitizeFilename_(email);

  if (payload.selfie) {
    selfieUrl = saveBase64ToDrive_(
      payload.selfie,
      "selfie_" + slug + "_" + Date.now() + ".jpg",
      folder
    );
  }

  if (payload.idCard) {
    // Add 1-second delay to ensure Drive API processes uploads sequentially
    Utilities.sleep(1000);
    idUrl = saveBase64ToDrive_(
      payload.idCard,
      "id_" + slug + "_" + Date.now() + ".jpg",
      folder
    );
  }

  // Append placeholder row — score columns filled by saveResults later
  sheet.appendRow([
    new Date(payload.timestamp || new Date()),  //  A: Timestamp
    payload.fullName || "",                      //  B: Full Name
    email,                                       //  C: Email
    "",                                          //  D: Score (%)
    "",                                          //  E: Score (fraction)
    "",                                          //  F: Pass/Fail
    "",                                          //  G: Time Taken
    "",                                          //  H: Tab Switches
    "",                                          //  I: Per-question breakdown
    selfieUrl,                                   //  J: Selfie URL
    idUrl,                                       //  K: ID Card URL
    "photos_uploaded"                            //  L: Status
  ]);

  return jsonResponse_({ success: true, selfieUrl: selfieUrl, idUrl: idUrl });
}


/**
 * Phase 2 — called when the quiz ends.
 * Finds the placeholder row by email + status and fills it in.
 * Falls back to appending a fresh row if no placeholder is found.
 */
function handleSaveResults_(payload) {
  var sheet     = getOrCreateSheet_();
  var email     = normalizeEmail_(payload.email);
  var rowIndex  = findPlaceholderRow_(sheet, email);

  if (rowIndex > 0) {
    // Update score columns in the existing row
    sheet.getRange(rowIndex, 4).setValue(Number(payload.scorePercent  || 0));
    sheet.getRange(rowIndex, 5).setValue(payload.scoreFraction        || "");
    sheet.getRange(rowIndex, 6).setValue(payload.passFail             || (payload.passed ? "YES" : "NO"));
    sheet.getRange(rowIndex, 7).setValue(payload.timeTaken            || formatTime_(payload.timeTakenSeconds || 0));
    sheet.getRange(rowIndex, 8).setValue(Number(payload.tabSwitches   || 0));
    sheet.getRange(rowIndex, 9).setValue(JSON.stringify(payload.breakdown || []));
    sheet.getRange(rowIndex, 12).setValue("completed");

  } else {
    // Fallback: no placeholder found — append a complete row without photos
    sheet.appendRow([
      new Date(payload.timestamp || new Date()),
      payload.fullName    || "",
      email,
      Number(payload.scorePercent  || 0),
      payload.scoreFraction        || "",
      payload.passFail             || (payload.passed ? "YES" : "NO"),
      payload.timeTaken            || formatTime_(payload.timeTakenSeconds || 0),
      Number(payload.tabSwitches   || 0),
      JSON.stringify(payload.breakdown || []),
      "",   // No selfie (not uploaded or skipped)
      "",   // No ID card
      "completed"
    ]);
  }

  return jsonResponse_({ success: true, duplicate: false });
}


// ══════════════════════════════════════════════════════════════
//  SHEET HELPERS
// ══════════════════════════════════════════════════════════════

/** Returns the results sheet, creating it with headers if needed. */
function getOrCreateSheet_() {
  var ss;
  var idStr = String(SHEET_ID).trim();
  if (idStr.indexOf("http") === 0) {
    ss = SpreadsheetApp.openByUrl(idStr);
  } else {
    ss = SpreadsheetApp.openById(idStr);
  }
  var sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(RESULTS_HEADERS);

    var headerRange = sheet.getRange(1, 1, 1, RESULTS_HEADERS.length);
    headerRange.setFontWeight("bold");
    headerRange.setBackground("#4c1d95");
    headerRange.setFontColor("#ffffff");
    sheet.setFrozenRows(1);
    sheet.setColumnWidth(10, 220);  // Selfie URL
    sheet.setColumnWidth(11, 220);  // ID Card URL
    sheet.setColumnWidth(9,  300);  // Per-question breakdown
  }

  return sheet;
}


/**
 * Returns true if a row with Status = "completed" already
 * exists for this email (prevents double submissions).
 */
function hasCompletedSubmission_(sheet, email) {
  var lastRow = sheet.getLastRow();
  if (lastRow <= 1) return false;

  var data = sheet.getRange(2, 1, lastRow - 1, 12).getValues();
  return data.some(function(row) {
    return normalizeEmail_(row[2]) === email &&
           String(row[11]).toLowerCase() === "completed";
  });
}


/**
 * Finds the 1-indexed sheet row for the "photos_uploaded"
 * placeholder for this email. Returns -1 if not found.
 */
function findPlaceholderRow_(sheet, email) {
  var lastRow = sheet.getLastRow();
  if (lastRow <= 1) return -1;

  var data = sheet.getRange(2, 1, lastRow - 1, 12).getValues();
  for (var i = 0; i < data.length; i++) {
    if (
      normalizeEmail_(data[i][2]) === email &&
      String(data[i][11]) === "photos_uploaded"
    ) {
      return i + 2;  // +1 for header row, +1 for 1-indexing
    }
  }
  return -1;
}


/**
 * Returns all completed rows as an array of header-keyed objects.
 */
function getResults_() {
  var sheet  = getOrCreateSheet_();
  var values = sheet.getDataRange().getValues();
  if (values.length <= 1) return [];

  var headers = values[0];
  return values.slice(1).map(function(row) {
    var record = {};
    headers.forEach(function(header, i) { record[header] = row[i]; });
    return record;
  });
}


// ══════════════════════════════════════════════════════════════
//  DRIVE HELPERS
// ══════════════════════════════════════════════════════════════

/**
 * Decodes a base64 string and saves it as a JPEG in the
 * specified Drive folder. Returns the shareable URL.
 */
/**
 * Resolves the target upload folder.
 * 1. Tries to get the folder by ID if provided and valid.
 * 2. Falls back to searching for a folder named folderName.
 * 3. Creates the folder in the Google Drive root if it does not exist.
 */
function getOrCreateUploadFolder_(folderId, folderName) {
  var folder;
  var cleanId = String(folderId || "").trim();

  // 1. Try accessing by ID if valid
  if (cleanId.length > 5) {
    try {
      folder = DriveApp.getFolderById(cleanId);
      return folder;
    } catch (e) {
      Logger.log("Folder not found by ID (or access denied), searching by name instead: " + e.message);
    }
  }

  // 2. Fallback: Search by name
  var name = folderName || "Mainstreet Exam Photos";
  try {
    var folders = DriveApp.getFoldersByName(name);
    if (folders.hasNext()) {
      folder = folders.next();
      return folder;
    }
  } catch (e) {
    Logger.log("Failed to search folders by name: " + e.message);
  }

  // 3. Fallback: Create folder in Drive root
  try {
    folder = DriveApp.createFolder(name);
    return folder;
  } catch (err) {
    throw new Error("Unable to access or create Google Drive folder. " +
                    "Please verify your account permissions. Detail: " + err.message);
  }
}

/**
 * Decodes a base64 string and saves it as a JPEG in the
 * specified Drive folder. Returns the shareable URL.
 */
function saveBase64ToDrive_(base64String, fileName, folder) {
  var decoded = Utilities.base64Decode(base64String);
  var blob    = Utilities.newBlob(decoded, "image/jpeg", fileName);
  var file    = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return file.getUrl();
}


// ══════════════════════════════════════════════════════════════
//  UTILITY HELPERS
// ══════════════════════════════════════════════════════════════

/** Parses and validates the POST body as JSON. */
function parsePayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new Error("Missing POST body.");
  }
  var payload = JSON.parse(e.postData.contents);
  if (!payload || typeof payload !== "object") {
    throw new Error("POST body must be a JSON object.");
  }
  return payload;
}

/** Lowercases and trims an email address. */
function normalizeEmail_(email) {
  return String(email || "").trim().toLowerCase();
}

/** Formats elapsed seconds as MM:SS */
function formatTime_(seconds) {
  var s  = Math.max(0, Math.round(seconds));
  var mm = String(Math.floor(s / 60)).padStart(2, "0");
  var ss = String(s % 60).padStart(2, "0");
  return mm + ":" + ss;
}

/** Strips unsafe characters from a filename component. */
function sanitizeFilename_(str) {
  return String(str).replace(/[^a-zA-Z0-9._-]/g, "_").substring(0, 60);
}

/** Returns a JSON ContentService response. */
function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Returns a JSONP ContentService response. */
function jsonpResponse_(callback, data) {
  var safeCallback = String(callback).replace(/[^\w$.]/g, "");
  return ContentService
    .createTextOutput(safeCallback + "(" + JSON.stringify(data) + ");")
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}