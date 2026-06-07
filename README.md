# Corporate Quiz App

Self-hosted quiz app built as a single static HTML file with SurveyJS, Tailwind CSS, and Google Sheets result saving through Google Apps Script.

There is no application database and no custom backend server. Google Sheets, accessed through the Google Apps Script Web App, is the only results backend.

## Files

- `index.html` - the quiz UI, scoring, timing, tab-switch tracking, and result POST.
- `admin.html` - a separate live results dashboard that reads from the Apps Script GET endpoint.
- `config.js` - quiz title, description, logo, pass mark, admin password, Apps Script URL, Sheet URL, and questions.
- `appsscript.gs` - the Google Apps Script Web App endpoint that appends quiz results to a sheet.

If a result POST fails because of a network or configuration error, the app stores the result in `localStorage` and retries pending submissions on the next page load. Google Apps Script does not provide custom CORS response headers through `ContentService`, so the app sends JSON as `text/plain` with `no-cors`. That lets browsers POST directly without a preflight request, but the browser cannot read the response body from the static page.

After completion, candidates can download their results as a PDF generated in the browser.

## Google Sheets Setup

1. Create a Google Sheet.
2. Open **Extensions > Apps Script**.
3. Paste the contents of `appsscript.gs` into the Apps Script editor.
4. Deploy as **Web app**.
5. Set **Execute as** to yourself.
6. Set **Who has access** to the intended audience, commonly **Anyone** or **Anyone with the link** for a public static quiz.
7. Copy the Web App URL.
8. Copy the Google Sheet URL.
9. In `config.js`, replace:

```js
sheetsWebAppUrl: "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec",
sheetUrl: "PASTE_YOUR_GOOGLE_SHEET_URL_HERE",
```

with your deployed Web App URL and Google Sheet URL.

For `admin.html`, also replace `adminPassword` in `config.js`. This is a simple client-side password gate for casual access control, not strong security.

### Troubleshooting: connection / CORS issues

- Ensure the Apps Script is deployed as a Web App with **Execute as** set to your account and **Who has access** set to **Anyone, even anonymous** (or at least **Anyone with the link**) so the static pages can call it.
- If the admin dashboard shows "Could not fetch results" or the quiz cannot save results, check the deployed Web App URL in `config.js` and that the script is published (not only saved).
- The frontend uses fetch POSTs for photo uploads and result saving. If the browser blocks the request due to CORS, the app will fall back to a fire-and-forget `navigator.sendBeacon` attempt for results and will continue without server-side photo uploads — in which case submissions still succeed locally, but images may not be stored in Drive.
- To inspect server-side errors, open the Apps Script editor, run the `getResults_()` function manually, or check the script executions log (Executions) in the Apps Script dashboard.

If you want, I can update the Apps Script to write CORS-friendly responses and add a small server-side health endpoint — tell me and I'll patch `appsscript.gs` and provide redeploy steps.

## Static Deployment

The app is a static site. Deploy these files together to Nginx, Apache, GitHub Pages, Netlify, or any static host:

- `index.html`
- `admin.html`
- `config.js`
- optional `logo.png` if `QUIZ_CONFIG.logo` points to it

The pages load SurveyJS, Tailwind CSS, and jsPDF from public CDNs, so the deployed site needs browser internet access for those assets unless you vendor them locally.

## Docker Compose

Serve the static files with Nginx on port 80. This container only serves HTML, JS, and static assets; it does not run an application backend or database.

```bash
docker compose up -d
```

Then open `http://localhost/`.

Local URLs:

- Quiz page: `http://localhost/`
- Admin dashboard: `http://localhost/admin.html`

## Quick Validation

1. Open `index.html` or the deployed quiz URL.
2. Enter a full name and email.
3. Complete the quiz.
4. Confirm the results screen shows score, pass/fail, breakdown, PDF download, and the submission success message.
5. Open the Google Sheet and confirm a new row was appended.
6. Open `admin.html`, enter the configured admin password, and confirm the result appears in the dashboard.

## Saved Columns

The Apps Script appends to the active sheet and initializes it with these columns when it is empty:

- Timestamp
- Full Name
- Email
- Score (%)
- Score (fraction)
- Pass/Fail
- Time Taken
- Tab Switches
- Per-question breakdown (JSON)

## Editing Quiz Content

Questions live in `config.js` under `QUIZ_CONFIG.questions`.

Each question can define `timeLimit`. If omitted, the app uses `defaultQuestionTimeLimitSeconds` from `config.js` when present, or 60 seconds.

Supported scored question types:

- `mcq` for single-choice questions, with `correct` as the zero-based option index.
- `multi` for multi-select questions, with `correct` as zero-based option indexes.
- any other type is treated as short answer, with `correct` as a string or list of accepted strings.
