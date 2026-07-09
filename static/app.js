// ── Shared UI Utilities: Toasts & Lightbox ───────────────────────

function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    // Trigger transition
    setTimeout(() => toast.classList.add("show"), 10);
    
    // Auto-dismiss
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 350);
    }, 4000);
}

// Global AJAX Request helper with CSRF Header support
async function apiRequest(url, method = "GET", body = null) {
    const headers = {};
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
    if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
    }
    
    const options = { method, headers };
    if (body) {
        if (body instanceof FormData) {
            options.body = body;
        } else {
            headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
    }
    
    const response = await fetch(url, options);
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP error ${response.status}`);
    }
    return response.json();
}

// ── Candidate Portal Logic ──────────────────────────────────────────

function initCandidatePortal() {
    let candidateName = "";
    let candidateEmail = "";
    let candidatePhone = "";
    let candidateRole = "";
    let candidateLocation = "";
    let requireIdentityVerification = true;
    let preTestFields = [];
    let candidateId = null;
    let idCardBase64 = null;
    let selfieBase64 = null;
    
    let questionsList = [];
    let currentQuestionIndex = 0;
    let selectedAnswer = null;
    let answersPayload = [];
    
    let isExamRunning = false;
    let tabSwitchesCount = 0;
    let totalExamTimeSecs = 0;
    let examSettings = { secondsPerQuestion: 60, passMark: 50.0 };
    
    let examTimerInterval = null;
    let questionTimerInterval = null;
    let questionTimeLeft = 0;
    let questionStartTime = 0;

    // Navigation Step Helper
    function goToStep(stepNumber) {
        document.querySelectorAll(".wizard-step").forEach(step => {
            step.classList.remove("active");
        });
        document.getElementById(`step-${stepNumber}`).classList.add("active");
        
        // Handle step entry hooks
        if (stepNumber === 3) {
            startWebcam();
        } else {
            stopWebcam();
        }
        
        if (stepNumber === 4) {
            loadInstructionsStats();
        }
        
        if (stepNumber === 6) {
            submitResultsToServer();
        }
    }

    // Navigation Lockout: prevents candidate from using back button
    history.pushState(null, "", window.location.href);
    window.addEventListener("popstate", () => {
        window.location.reload(); // Wipes JS state, returns to Step 1 cleanly
    });

    // ── Step 1: Registration ──
    const regForm = document.getElementById("reg-form");
    regForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("reg-error");
        errorEl.classList.add("hidden");
        
        const name = document.getElementById("full-name").value.trim();
        const email = document.getElementById("email").value.trim();
        
        if (!name || !email) {
            errorEl.textContent = "Please enter your full name and email.";
            errorEl.classList.remove("hidden");
            return;
        }

        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            errorEl.textContent = "Please enter a valid email address.";
            errorEl.classList.remove("hidden");
            return;
        }
        
        try {
            const res = await apiRequest("/api/check-email", "POST", { email, full_name: name });
            candidateName = name;
            candidateEmail = email;
            candidatePhone = "";
            candidateRole = "";
            candidateLocation = "";
            requireIdentityVerification = res.require_identity_verification !== false;
            preTestFields = res.pre_test_fields || [];
            if (requireIdentityVerification) {
                goToStep(2);
            } else {
                renderPreTestStep(preTestFields);
                goToStep(2);
            }
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove("hidden");
        }
    });

    function renderPreTestStep(fields) {
        const step = document.getElementById("step-2");
        const enabled = (fields || []).filter(f => f.enabled !== false);
        const customFields = enabled.length ? enabled : [
            { key: "full_name", label: "Full name", required: true },
            { key: "email", label: "Email", required: true },
        ];
        step.innerHTML = `
            <div class="card upload-card">
                <h1 class="step-heading">A few details before you start</h1>
                <p class="step-subtext">Complete these fields before beginning the assessment.</p>
                <div id="pretest-error" class="alert alert-danger hidden"></div>
                <form id="pretest-form" novalidate>
                    ${customFields.map(field => `
                        <div class="form-group">
                            <label for="pretest-${field.key}">${field.label}${field.required ? ' *' : ''}</label>
                            <input type="${field.key === 'dob' ? 'date' : field.key === 'email' ? 'email' : 'text'}"
                                id="pretest-${field.key}"
                                data-key="${field.key}"
                                data-required="${field.required ? 'true' : 'false'}"
                                value="${field.key === 'full_name' ? candidateName : field.key === 'email' ? candidateEmail : ''}">
                            <div class="help-text hidden" id="pretest-${field.key}-error">This field is required.</div>
                        </div>
                    `).join('')}
                    <button type="submit" class="btn btn-primary btn-full">Start assessment</button>
                </form>
            </div>
        `;
        document.getElementById("pretest-form").addEventListener("submit", submitPreTestFields);
    }

    async function submitPreTestFields(e) {
        e.preventDefault();
        const errorEl = document.getElementById("pretest-error");
        errorEl.classList.add("hidden");
        const responses = {};
        let valid = true;
        document.querySelectorAll("#pretest-form [data-key]").forEach(input => {
            const key = input.dataset.key;
            const required = input.dataset.required === "true";
            const value = input.value.trim();
            responses[key] = value;
            const fieldError = document.getElementById(`pretest-${key}-error`);
            if (required && !value) {
                valid = false;
                if (fieldError) fieldError.classList.remove("hidden");
            } else if (fieldError) {
                fieldError.classList.add("hidden");
            }
        });
        if (!valid) return;

        try {
            const result = await apiRequest("/api/upload-photos", "POST", {
                email: candidateEmail,
                full_name: candidateName,
                pre_test_responses: responses,
            });
            candidateId = result.candidate_id;
            goToStep(4);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove("hidden");
        }
    }

    // ── Step 2: ID Upload ──
    const idDropzone = document.getElementById("id-dropzone");
    const idFileInput = document.getElementById("id-file-input");
    const idPreviewContainer = document.getElementById("id-preview-container");
    const idPreview = document.getElementById("id-preview");
    const btnRemoveId = document.getElementById("btn-remove-id");
    const btnToStep3 = document.getElementById("btn-to-step3");
    
    idDropzone.addEventListener("click", (e) => {
        if (e.target !== btnRemoveId) {
            idFileInput.click();
        }
    });
    
    // Drag & Drop
    idDropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        idDropzone.style.borderColor = "var(--color-primary)";
    });
    
    idDropzone.addEventListener("dragleave", () => {
        idDropzone.style.borderColor = "var(--color-gray-400)";
    });
    
    idDropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        idDropzone.style.borderColor = "var(--color-gray-400)";
        if (e.dataTransfer.files.length > 0) {
            handleIdFile(e.dataTransfer.files[0]);
        }
    });
    
    idFileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleIdFile(e.target.files[0]);
        }
    });
    
    async function handleIdFile(file) {
        if (!file.type.match("image/jpeg") && !file.type.match("image/png")) {
            showToast("Invalid file type. Please upload a JPG or PNG image.", "error");
            return;
        }
        if (file.size > 1 * 1024 * 1024) {
            showToast("File size exceeds 1 MB limit.", "error");
            return;
        }
        
        try {
            idCardBase64 = await readFileAsBase64(file);
            idPreview.src = idCardBase64;
            idPreviewContainer.classList.remove("hidden");
            btnToStep3.removeAttribute("disabled");
        } catch (err) {
            showToast("Failed to read file.", "error");
        }
    }
    
    btnRemoveId.addEventListener("click", (e) => {
        e.stopPropagation();
        idCardBase64 = null;
        idPreview.src = "";
        idPreviewContainer.classList.add("hidden");
        idFileInput.value = "";
        btnToStep3.setAttribute("disabled", "true");
    });
    
    btnToStep3.addEventListener("click", () => goToStep(3));

    // ── Step 3: Selfie Capture ──
    const webcam = document.getElementById("webcam");
    const capturedCanvas = document.getElementById("captured-canvas");
    const selfieStill = document.getElementById("selfie-still");
    const btnCapture = document.getElementById("btn-capture");
    const selfieConfirmControls = document.getElementById("selfie-confirm-controls");
    const btnUsePhoto = document.getElementById("btn-use-photo");
    const btnRetake = document.getElementById("btn-retake");
    
    const selfieFallbackZone = document.getElementById("selfie-fallback-zone");
    const selfieFileInput = document.getElementById("selfie-file-input");
    const selfiePreviewContainer = document.getElementById("selfie-preview-container");
    const selfiePreview = document.getElementById("selfie-preview");
    const btnRemoveSelfie = document.getElementById("btn-remove-selfie");
    const btnSelfieFallbackContinue = document.getElementById("btn-selfie-fallback-continue");
    
    let videoStream = null;

    async function startWebcam() {
        try {
            videoStream = await navigator.mediaDevices.getUserMedia({
                video: { width: 640, height: 480, facingMode: "user" },
                audio: false
            });
            webcam.srcObject = videoStream;
            webcam.classList.remove("hidden");
            document.getElementById("face-guide").classList.remove("hidden");
            selfieStill.classList.add("hidden");
            btnCapture.classList.remove("hidden");
            selfieConfirmControls.classList.add("hidden");
            selfieFallbackZone.classList.add("hidden");
        } catch (err) {
            console.warn("Camera blocked or unavailable, using fallback file upload.", err);
            // Show fallback file input
            webcam.classList.add("hidden");
            document.getElementById("face-guide").classList.add("hidden");
            document.getElementById("camera-error-msg").classList.remove("hidden");
            selfieFallbackZone.classList.remove("hidden");
            btnCapture.classList.add("hidden");
            btnSelfieFallbackContinue.classList.remove("hidden");
        }
    }

    function stopWebcam() {
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }
    }

    btnCapture.addEventListener("click", () => {
        if (!videoStream) return;
        const ctx = capturedCanvas.getContext("2d");
        capturedCanvas.width = webcam.videoWidth;
        capturedCanvas.height = webcam.videoHeight;
        // Mirror selfie capture
        ctx.translate(capturedCanvas.width, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(webcam, 0, 0, capturedCanvas.width, capturedCanvas.height);
        
        selfieBase64 = capturedCanvas.toDataURL("image/jpeg");
        selfieStill.src = selfieBase64;
        selfieStill.classList.remove("hidden");
        webcam.classList.add("hidden");
        document.getElementById("face-guide").classList.add("hidden");
        
        btnCapture.classList.add("hidden");
        selfieConfirmControls.classList.remove("hidden");
        stopWebcam();
    });

    btnRetake.addEventListener("click", startWebcam);

    btnUsePhoto.addEventListener("click", async () => {
        // Trigger non-blocking upload to Cloudinary in background
        uploadPhotosInBackground();
        goToStep(4);
    });

    // Fallback file capture handlers
    selfieFallbackZone.addEventListener("click", (e) => {
        if (e.target !== btnRemoveSelfie) {
            selfieFileInput.click();
        }
    });

    selfieFileInput.addEventListener("change", async (e) => {
        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            if (!file.type.match("image/jpeg") && !file.type.match("image/png")) {
                showToast("Invalid file type.", "error");
                return;
            }
            if (file.size > 1 * 1024 * 1024) {
                showToast("File size exceeds 1 MB limit.", "error");
                return;
            }
            try {
                selfieBase64 = await readFileAsBase64(file);
                selfiePreview.src = selfieBase64;
                selfiePreviewContainer.classList.remove("hidden");
                btnSelfieFallbackContinue.removeAttribute("disabled");
            } catch (err) {
                showToast("Failed to read file.", "error");
            }
        }
    });

    btnRemoveSelfie.addEventListener("click", (e) => {
        e.stopPropagation();
        selfieBase64 = null;
        selfiePreview.src = "";
        selfiePreviewContainer.classList.add("hidden");
        selfieFileInput.value = "";
        btnSelfieFallbackContinue.setAttribute("disabled", "true");
    });

    btnSelfieFallbackContinue.addEventListener("click", () => {
        uploadPhotosInBackground();
        goToStep(4);
    });

    async function uploadPhotosInBackground() {
        try {
            const res = await apiRequest("/api/upload-photos", "POST", {
                email: candidateEmail,
                full_name: candidateName,
                phone_number: candidatePhone,
                role: candidateRole,
                location: candidateLocation,
                selfie_b64: selfieBase64,
                id_card_b64: idCardBase64
            });
            candidateId = res.candidate_id;
        } catch (err) {
            console.error("Background uploads failed", err);
            // We do not block the candidate, but we show a warning toast
            showToast("Document upload connection retry will occur at exam submission.", "error");
        }
    }

    // ── Step 4: Instructions ──
    async function loadInstructionsStats() {
        try {
            const summary = await apiRequest("/api/exam-summary");
            examSettings.secondsPerQuestion = summary.seconds_per_question;
            examSettings.passMark = summary.pass_mark_percent;
            
            document.getElementById("stat-total-q").textContent = summary.total_questions;
            document.getElementById("stat-time-q").textContent = `${examSettings.secondsPerQuestion}s`;
            document.getElementById("stat-pass-mark").textContent = `${examSettings.passMark}%`;
        } catch (err) {
            console.error("Failed loading settings stats", err);
        }
    }

    // Start Exam click hold fill transition
    const btnStartExam = document.getElementById("btn-start-exam");
    btnStartExam.addEventListener("click", () => {
        if (btnStartExam.classList.contains("animating")) return;
        
        btnStartExam.classList.add("animating");
        
        setTimeout(() => {
            // Check if upload finished (got candidateId)
            if (!candidateId) {
                // Try once more inline
                apiRequest("/api/upload-photos", "POST", {
                    email: candidateEmail,
                    full_name: candidateName,
                    phone_number: candidatePhone,
                    role: candidateRole,
                    location: candidateLocation,
                    selfie_b64: selfieBase64,
                    id_card_b64: idCardBase64
                }).then(res => {
                    candidateId = res.candidate_id;
                    startExamWorkspace();
                }).catch(err => {
                    showToast("Could not complete verification file uploading. Re-trying...", "error");
                    btnStartExam.classList.remove("animating");
                });
            } else {
                startExamWorkspace();
            }
        }, 3000);
    });

    // ── Step 5: The Exam ──
    async function startExamWorkspace() {
        try {
            if (questionsList.length === 0) {
                questionsList = await apiRequest("/api/questions");
            }
            if (questionsList.length === 0) {
                throw new Error("No exam questions are available.");
            }
        } catch (err) {
            showToast("Could not load exam questions. Please try again.", "error");
            btnStartExam.classList.remove("animating");
            return;
        }

        goToStep(5);
        isExamRunning = true;
        currentQuestionIndex = 0;
        answersPayload = [];
        tabSwitchesCount = 0;
        totalExamTimeSecs = 0;
        
        // Start total exam duration timer
        examTimerInterval = setInterval(() => {
            totalExamTimeSecs++;
        }, 1000);
        
        initTabSwitchTracking();
        buildQuestionGrids();
        loadQuestion(0);
    }

    function initTabSwitchTracking() {
        window.addEventListener("blur", () => {
            if (isExamRunning) tabSwitchesCount++;
        });
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden" && isExamRunning) {
                tabSwitchesCount++;
            }
        });
    }

    function buildQuestionGrids() {
        const containers = {
            "Numerical": [document.getElementById("grid-numerical"), document.getElementById("mobile-grid-numerical")],
            "Verbal": [document.getElementById("grid-verbal"), document.getElementById("mobile-grid-verbal")],
            "Logical": [document.getElementById("grid-logical"), document.getElementById("mobile-grid-logical")]
        };
        
        // Clear old items
        for (let sec in containers) {
            containers[sec].forEach(el => el.replaceChildren());
        }
        
        questionsList.forEach((q, idx) => {
            const sec = q.section;
            if (containers[sec]) {
                containers[sec].forEach(el => {
                    const cell = document.createElement("div");
                    cell.className = "grid-cell unanswered";
                    cell.id = `cell-${idx}`;
                    cell.textContent = idx + 1;
                    el.appendChild(cell);
                });
            }
        });
    }

    function updateQuestionGridDisplay() {
        // Clear all states and apply new
        document.querySelectorAll(".grid-cell").forEach(cell => {
            const idx = parseInt(cell.textContent) - 1;
            cell.className = "grid-cell";
            if (idx === currentQuestionIndex) {
                cell.classList.add("current");
            } else if (answersPayload[idx]) {
                cell.classList.add("answered");
            } else {
                cell.classList.add("unanswered");
            }
        });
    }

    function loadQuestion(idx) {
        if (idx >= questionsList.length) {
            finishExam();
            return;
        }
        
        currentQuestionIndex = idx;
        selectedAnswer = null;
        updateQuestionGridDisplay();
        
        const q = questionsList[idx];
        
        // Populate layout
        document.getElementById("exam-section-label").textContent = q.section;
        document.getElementById("exam-section-tag").textContent = `${q.section} Reasoning`;
        document.getElementById("exam-progress-text").textContent = `Question ${idx + 1} of ${questionsList.length}`;
        
        const stemEl = document.getElementById("exam-question-stem");
        stemEl.replaceChildren();
        // Allow inline HTML formatting safely for stems
        const stemParser = new DOMParser().parseFromString(q.stem, "text/html");
        stemEl.append(...stemParser.body.childNodes);
        
        const optionsBox = document.getElementById("options-container");
        optionsBox.replaceChildren();
        
        q.options.forEach((opt, oIdx) => {
            const row = document.createElement("div");
            row.className = "option-row";
            row.setAttribute("role", "radio");
            row.setAttribute("aria-checked", "false");
            row.setAttribute("tabindex", "0");
            
            const text = document.createElement("span");
            text.className = "option-text";
            text.textContent = opt;
            
            row.appendChild(text);
            
            row.addEventListener("click", () => selectOption(row, oIdx));
            row.addEventListener("keydown", (e) => {
                if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    selectOption(row, oIdx);
                }
            });
            
            optionsBox.appendChild(row);
        });
        
        // Reset and start countdown timer
        questionTimeLeft = examSettings.secondsPerQuestion;
        questionStartTime = Date.now();
        startQuestionTimer();
        
        // Update Next button label
        const btnNext = document.getElementById("btn-next-question");
        if (idx === questionsList.length - 1) {
            btnNext.textContent = "Submit exam";
        } else {
            btnNext.textContent = "Next question →";
        }
    }

    function selectOption(row, idx) {
        document.querySelectorAll(".option-row").forEach(r => {
            r.classList.remove("selected");
            r.setAttribute("aria-checked", "false");
        });
        row.classList.add("selected");
        row.setAttribute("aria-checked", "true");
        selectedAnswer = idx;
    }

    function startQuestionTimer() {
        if (questionTimerInterval) clearInterval(questionTimerInterval);
        
        const timerDisplay = document.getElementById("exam-timer-display");
        timerDisplay.textContent = questionTimeLeft;
        timerDisplay.classList.remove("timer-critical");
        
        questionTimerInterval = setInterval(() => {
            questionTimeLeft--;
            timerDisplay.textContent = questionTimeLeft;
            
            if (questionTimeLeft <= 10) {
                timerDisplay.classList.add("timer-critical");
            }
            
            if (questionTimeLeft <= 0) {
                clearInterval(questionTimerInterval);
                autoAdvanceOnTimeout();
            }
        }, 1000);
    }

    function autoAdvanceOnTimeout() {
        const timeSpent = Math.round((Date.now() - questionStartTime) / 1000);
        answersPayload[currentQuestionIndex] = {
            question_id: questionsList[currentQuestionIndex].id,
            answer_given: selectedAnswer, // null if none selected
            time_spent_secs: timeSpent,
            was_timeout: selectedAnswer === null
        };
        
        // Load next
        loadQuestion(currentQuestionIndex + 1);
    }

    const btnNextQuestion = document.getElementById("btn-next-question");
    btnNextQuestion.addEventListener("click", () => {
        clearInterval(questionTimerInterval);
        const timeSpent = Math.round((Date.now() - questionStartTime) / 1000);
        answersPayload[currentQuestionIndex] = {
            question_id: questionsList[currentQuestionIndex].id,
            answer_given: selectedAnswer,
            time_spent_secs: timeSpent,
            was_timeout: false
        };
        loadQuestion(currentQuestionIndex + 1);
    });

    // Mobile grid sheet toggles
    const btnMobileGridToggle = document.getElementById("btn-mobile-grid-toggle");
    const mobileGridSheet = document.getElementById("mobile-bottom-sheet");
    const btnCloseSheet = document.getElementById("btn-close-sheet");
    const overlaySheet = document.querySelector(".bottom-sheet-overlay");
    
    function toggleMobileSheet() {
        mobileGridSheet.classList.toggle("hidden");
    }
    
    btnMobileGridToggle.addEventListener("click", toggleMobileSheet);
    btnCloseSheet.addEventListener("click", toggleMobileSheet);
    overlaySheet.addEventListener("click", toggleMobileSheet);

    function finishExam() {
        isExamRunning = false;
        clearInterval(examTimerInterval);
        clearInterval(questionTimerInterval);
        goToStep(6);
    }

    // ── Step 6: Grading & Certificate ──
    async function submitResultsToServer() {
        const spinner = document.getElementById("grading-spinner");
        const cardResult = document.getElementById("result-content-container");
        
        try {
            const res = await apiRequest("/api/submit-results", "POST", {
                candidate_id: candidateId,
                answers: answersPayload,
                tab_switches: tabSwitchesCount,
                time_taken_secs: totalExamTimeSecs
            });
            
            // Populate results card
            document.getElementById("res-candidate-name").textContent = res.candidate_name;
            document.getElementById("res-percent").textContent = `${res.score_percent}%`;
            document.getElementById("res-fraction").textContent = `(${res.score_fraction})`;
            
            const badge = document.getElementById("res-badge");
            badge.textContent = res.pass_fail;
            badge.className = `badge ${res.pass_fail === 'PASS' ? 'badge-pass' : 'badge-fail'}`;
            
            document.getElementById("res-ref-number").textContent = res.ref_number;
            
            // Build breakdown stats per section
            buildSectionBreakdownTable(res.breakdown);
            
            // Set print timestamp
            document.getElementById("res-print-time").textContent = `Generated on: ${new Date(res.submitted_at).toLocaleString()}`;
            
            // Show result
            spinner.classList.add("hidden");
            cardResult.classList.remove("hidden");
        } catch (err) {
            spinner.replaceChildren();
            const errDiv = document.createElement("div");
            errDiv.className = "alert alert-danger";
            errDiv.textContent = `Grade Submission Error: ${err.message}. Please contact the admin.`;
            spinner.appendChild(errDiv);
        }
    }

    function buildSectionBreakdownTable(breakdown) {
        const tableBody = document.getElementById("breakdown-rows");
        tableBody.replaceChildren();
        
        const sections = ["Numerical", "Verbal", "Logical"];
        sections.forEach(sec => {
            const items = breakdown.filter(q => q.section === sec);
            const total = items.length;
            const correct = items.filter(q => q.is_correct).length;
            const percent = total > 0 ? ((correct / total) * 100).toFixed(2) : "0.00";
            
            const tr = document.createElement("tr");
            
            const tdSec = document.createElement("td");
            tdSec.textContent = sec;
            
            const tdCorrect = document.createElement("td");
            tdCorrect.textContent = correct;
            
            const tdTotal = document.createElement("td");
            tdTotal.textContent = total;
            
            const tdPercent = document.createElement("td");
            tdPercent.style.verticalAlign = "middle";
            
            const pctLabel = document.createElement("div");
            pctLabel.style.fontWeight = "600";
            pctLabel.style.marginBottom = "4px";
            pctLabel.textContent = `${percent}%`;
            
            const barContainer = document.createElement("div");
            barContainer.className = "bar-container";
            const barFill = document.createElement("div");
            barFill.className = "bar-fill";
            barFill.style.width = `${percent}%`;
            barContainer.appendChild(barFill);
            
            tdPercent.appendChild(pctLabel);
            tdPercent.appendChild(barContainer);
            
            tr.appendChild(tdSec);
            tr.appendChild(tdCorrect);
            tr.appendChild(tdTotal);
            tr.appendChild(tdPercent);
            
            tableBody.appendChild(tr);
        });
    }

    document.getElementById("btn-print-result").addEventListener("click", () => {
        window.print();
    });

    // Helper: read file content as base64
    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = err => reject(err);
            reader.readAsDataURL(file);
        });
    }
}

// ── Admin Dashboard Logic ───────────────────────────────────────────

function initAdminDashboard() {
    // Check if on login or dashboard page
    const loginForm = document.getElementById("admin-login-form");
    if (loginForm) {
        initAdminLogin(loginForm);
    } else {
        initAdminOperations();
    }
}

function initAdminLogin(form) {
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("login-error");
        errorEl.classList.add("hidden");
        
        const token = document.getElementById("admin-token").value.trim();
        if (!token) return;
        
        try {
            const res = await apiRequest("/admin/login", "POST", { token });
            if (res.success) {
                window.location.href = "/admin";
            }
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove("hidden");
        }
    });
}

function initAdminOperations() {
    let currentQuestionFilter = "all";
    let allQuestionsList = [];

    // Filter change listeners
    document.querySelectorAll('input[name="question-type-filter"]').forEach(radio => {
        radio.addEventListener("change", (e) => {
            currentQuestionFilter = e.target.value;
            renderQuestionList(allQuestionsList);
        });
    });

    function showCustomConfirm(title, message, onConfirm) {
        document.getElementById("confirm-title").textContent = title;
        document.getElementById("confirm-message").textContent = message;
        
        const modal = document.getElementById("confirm-modal");
        modal.classList.remove("hidden");
        
        const btnYes = document.getElementById("btn-confirm-yes");
        const btnNo = document.getElementById("btn-confirm-no");
        
        const newYes = btnYes.cloneNode(true);
        const newNo = btnNo.cloneNode(true);
        btnYes.parentNode.replaceChild(newYes, btnYes);
        btnNo.parentNode.replaceChild(newNo, btnNo);
        
        newYes.addEventListener("click", () => {
            modal.classList.add("hidden");
            if (onConfirm) onConfirm();
        });
        
        newNo.addEventListener("click", () => {
            modal.classList.add("hidden");
        });
        
        const closeOnOutside = (e) => {
            if (e.target === modal) {
                modal.classList.add("hidden");
                modal.removeEventListener("click", closeOnOutside);
            }
        };
        modal.addEventListener("click", closeOnOutside);
    }

    // Setup Logouts
    document.getElementById("btn-admin-logout").addEventListener("click", async () => {
        try {
            await apiRequest("/admin/logout", "POST");
            window.location.href = "/admin/login";
        } catch (err) {
            showToast("Logout failed.", "error");
        }
    });

    // Tabs Manager
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            
            document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
            const panelId = `tab-${tab.dataset.tab}`;
            document.getElementById(panelId).classList.add("active");
            
            // Tab specific triggers
            if (tab.dataset.tab === "settings") loadSettingsTab();
            if (tab.dataset.tab === "questions") loadQuestionsTab();
            if (tab.dataset.tab === "candidates") loadResultsTab();
            if (tab.dataset.tab === "whitelist") loadWhitelistTab();
        });
    });

    // Toasts helpers
    function toastSuccess(msg) { showToast(msg, "success"); }
    function toastError(msg) { showToast(msg, "error"); }

    // ── Panel 1: Exam Settings ──
    const settingsForm = document.getElementById("settings-form");
    const switchOpen = document.getElementById("setting-exam-open");
    const statusText = document.getElementById("setting-status-text");
    const requireIdentityToggle = document.getElementById("setting-require-identity");
    const identityStatusText = document.getElementById("identity-status-text");
    const pretestPanel = document.getElementById("pretest-fields-panel");
    const pretestList = document.getElementById("pretestFieldsList");
    const pretestFieldTypes = [
        { key: "full_name", label: "Full name", locked: true, required: true },
        { key: "email", label: "Email", locked: true, required: true },
        { key: "phone_number", label: "Phone number" },
        { key: "dob", label: "Date of birth" },
        { key: "staff_id", label: "Employee/Staff ID" },
        { key: "department", label: "Department" },
        { key: "location", label: "Location/Branch" },
    ];

    function normalizePretestFields(fields) {
        const map = new Map((fields || []).map(f => [f.key, f]));
        return pretestFieldTypes.map(base => ({
            key: base.key,
            label: map.get(base.key)?.label || base.label,
            enabled: base.locked || Boolean(map.get(base.key)?.enabled),
            required: base.locked || Boolean(map.get(base.key)?.required),
            locked: Boolean(base.locked),
        })).concat((fields || []).filter(f => f.key?.startsWith("custom_")));
    }

    function renderPretestFields(fields) {
        const normalized = normalizePretestFields(fields);
        pretestList.innerHTML = normalized.map((f, idx) => `
            <div class="card" style="padding:12px;display:grid;grid-template-columns:24px 1fr auto auto;gap:10px;align-items:center">
                <span class="font-mono" style="color:var(--mfb-gray-600)">::</span>
                <input class="form-control pretest-label" data-key="${f.key}" value="${f.label}" ${f.locked ? 'readonly' : ''}>
                <label style="font-size:13px;color:var(--mfb-gray-600)">
                    <input type="checkbox" class="pretest-enabled" data-key="${f.key}" ${f.enabled ? 'checked' : ''} ${f.locked ? 'disabled' : ''}> Show
                </label>
                <label style="font-size:13px;color:var(--mfb-gray-600)">
                    <input type="checkbox" class="pretest-required" data-key="${f.key}" ${f.required ? 'checked' : ''} ${f.locked ? 'disabled' : ''}> Required
                </label>
            </div>
        `).join("");
    }

    function readPretestFields() {
        return Array.from(pretestList.querySelectorAll(".pretest-label")).map(input => {
            const key = input.dataset.key;
            const enabled = pretestList.querySelector(`.pretest-enabled[data-key="${key}"]`);
            const required = pretestList.querySelector(`.pretest-required[data-key="${key}"]`);
            return {
                key,
                label: input.value.trim(),
                enabled: enabled ? enabled.checked || enabled.disabled : true,
                required: required ? required.checked || required.disabled : true,
            };
        }).filter(f => f.enabled);
    }

    function syncIdentityPanel() {
        if (!requireIdentityToggle) return;
        identityStatusText.textContent = requireIdentityToggle.checked ? "Verification on" : "Verification off";
        pretestPanel.style.display = requireIdentityToggle.checked ? "none" : "block";
    }

    async function loadSettingsTab() {
        try {
            const s = await apiRequest("/api/admin/settings");
            switchOpen.checked = s.exam_open;
            statusText.textContent = s.exam_open ? "Exam open" : "Exam closed";
            document.getElementById("setting-seconds-per-q").value = s.seconds_per_question;
            document.getElementById("setting-pass-mark").value = s.pass_mark_percent;
            if (requireIdentityToggle) {
                requireIdentityToggle.checked = s.require_identity_verification !== false;
                renderPretestFields(s.pre_test_fields || []);
                syncIdentityPanel();
            }
            document.getElementById("settings-last-updated").textContent = `Last updated: ${new Date(s.updated_at).toLocaleString()}`;
        } catch (err) {
            toastError("Failed to fetch settings.");
        }
    }

    switchOpen.addEventListener("change", () => {
        statusText.textContent = switchOpen.checked ? "Exam open" : "Exam closed";
    });
    if (requireIdentityToggle) {
        requireIdentityToggle.addEventListener("change", syncIdentityPanel);
    }
    document.getElementById("btn-add-pretest-field")?.addEventListener("click", () => {
        const current = readPretestFields();
        current.push({
            key: `custom_${Date.now()}`,
            label: "Custom text field",
            enabled: true,
            required: false,
        });
        renderPretestFields(current);
    });

    settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
            exam_open: switchOpen.checked,
            seconds_per_question: parseInt(document.getElementById("setting-seconds-per-q").value),
            pass_mark_percent: parseFloat(document.getElementById("setting-pass-mark").value),
            require_identity_verification: requireIdentityToggle ? requireIdentityToggle.checked : true,
            pre_test_fields: pretestList ? readPretestFields() : []
        };
        try {
            await apiRequest("/api/admin/settings", "POST", payload);
            toastSuccess("Settings saved successfully.");
            loadSettingsTab();
        } catch (err) {
            toastError(err.message);
        }
    });

    // ── Panel 2: Question Bank ──
    const editorForm = document.getElementById("question-editor-form");
    const bulkToggle = document.getElementById("bulk-toggle");
    const bulkBody = document.getElementById("bulk-body-content");
    
    // Toggle bulk container
    bulkToggle.addEventListener("click", () => {
        bulkBody.classList.toggle("hidden");
        bulkToggle.querySelector(".toggle-icon").innerHTML = bulkBody.classList.contains("hidden") ? "&plus;" : "&minus;";
    });

    async function loadQuestionsTab() {
        try {
            const list = await apiRequest("/api/admin/questions");
            renderQuestionList(list);
        } catch (err) {
            toastError("Failed to load questions.");
        }
    }

    function renderQuestionList(questions) {
        allQuestionsList = questions; // Store reference
        
        const sections = {
            "Numerical": document.getElementById("admin-questions-numerical"),
            "Verbal": document.getElementById("admin-questions-verbal"),
            "Logical": document.getElementById("admin-questions-logical")
        };
        
        // Clear
        for (let sec in sections) {
            sections[sec].replaceChildren();
        }
        
        questions.forEach(q => {
            // Apply filter
            if (currentQuestionFilter === "default" && !q.is_default) return;
            if (currentQuestionFilter === "uploaded" && q.is_default) return;
            
            const row = document.createElement("div");
            row.className = `question-row-item ${q.active ? '' : 'inactive'}`;
            // Reordering via drag and drop is only meaningful when viewing "All Questions"
            if (currentQuestionFilter === "all") {
                row.setAttribute("draggable", "true");
            } else {
                row.setAttribute("draggable", "false");
            }
            row.dataset.id = q.id;
            
            // Drag handle
            const handle = document.createElement("i");
            handle.className = "ti ti-grip-vertical drag-handle";
            if (currentQuestionFilter !== "all") {
                handle.style.visibility = "hidden";
            }
            
            // Pos
            const pos = document.createElement("span");
            pos.className = "question-pos";
            pos.textContent = q.position || q.id;
            
            // Badge for default vs uploaded
            const badge = document.createElement("span");
            if (q.is_default) {
                badge.className = "badge badge-default";
                badge.textContent = "Default";
            } else {
                badge.className = "badge badge-uploaded";
                badge.textContent = "Uploaded";
            }
            
            // Stem
            const stem = document.createElement("span");
            stem.className = "question-stem-text";
            stem.textContent = q.stem.replace(/<[^>]*>/g, ''); // strip HTML for truncation view
            
            // Actions
            const actionBox = document.createElement("div");
            actionBox.className = "row-actions";
            
            const btnEdit = document.createElement("button");
            btnEdit.type = "button";
            btnEdit.className = "btn-icon";
            btnEdit.title = "Edit Question";
            const iconEdit = document.createElement("i");
            iconEdit.className = "ti ti-edit";
            btnEdit.appendChild(iconEdit);
            btnEdit.addEventListener("click", () => editQuestion(q));
            
            const btnDelete = document.createElement("button");
            btnDelete.type = "button";
            btnDelete.className = "btn-icon btn-icon-danger";
            btnDelete.title = "Delete Question";
            const iconTrash = document.createElement("i");
            iconTrash.className = "ti ti-trash";
            btnDelete.appendChild(iconTrash);
            btnDelete.addEventListener("click", () => deleteQuestion(q.id));
            
            actionBox.appendChild(btnEdit);
            actionBox.appendChild(btnDelete);
            
            row.appendChild(handle);
            row.appendChild(pos);
            row.appendChild(badge);
            row.appendChild(stem);
            row.appendChild(actionBox);
            
            // Drag listeners
            setupDragAndDropRow(row, q.section);
            
            // Click handler on row to trigger edit (excluding actions and drag handle)
            row.addEventListener("click", (e) => {
                if (e.target.closest("button") || e.target.closest(".drag-handle")) {
                    return;
                }
                editQuestion(q);
            });
            
            if (sections[q.section]) {
                sections[q.section].appendChild(row);
            }
        });
    }

    // Drag-and-Drop Implementation
    let dragSrcEl = null;
    function setupDragAndDropRow(row, section) {
        row.addEventListener("dragstart", (e) => {
            row.classList.add("dragging");
            dragSrcEl = row;
            e.dataTransfer.effectAllowed = "move";
        });
        
        row.addEventListener("dragover", (e) => {
            e.preventDefault();
            const parent = row.parentNode;
            const draggingNode = parent.querySelector(".dragging");
            if (!draggingNode || draggingNode === row) return;
            
            // Ensure dragging only within the same section container
            if (draggingNode.parentNode !== parent) return;
            
            const bounding = row.getBoundingClientRect();
            const offset = e.clientY - bounding.top - bounding.height / 2;
            if (offset > 0) {
                parent.insertBefore(draggingNode, row.nextSibling);
            } else {
                parent.insertBefore(draggingNode, row);
            }
        });
        
        row.addEventListener("dragend", async () => {
            row.classList.remove("dragging");
            // Find parent and collect IDs in new order
            const parent = row.parentNode;
            const rows = parent.querySelectorAll(".question-row-item");
            const ids = Array.from(rows).map(r => parseInt(r.dataset.id));
            
            try {
                await apiRequest("/api/admin/questions/reorder", "POST", { ordered_ids: ids });
                loadQuestionsTab();
            } catch (err) {
                toastError("Failed to reorder questions.");
            }
        });
    }

    let editorFormSnapshot = null;

    function getEditorFormSnapshot() {
        const sectionEl = document.querySelector('input[name="editor-section"]:checked');
        const answerEl = document.querySelector('input[name="editor-answer"]:checked');
        return JSON.stringify({
            section: sectionEl ? sectionEl.value : "Numerical",
            stem: document.getElementById("editor-stem").value.trim(),
            opt_a: document.getElementById("editor-opt-a").value.trim(),
            opt_b: document.getElementById("editor-opt-b").value.trim(),
            opt_c: document.getElementById("editor-opt-c").value.trim(),
            opt_d: document.getElementById("editor-opt-d").value.trim(),
            answer: answerEl ? answerEl.value : "0",
            active: document.getElementById("editor-active").checked
        });
    }

    function takeFormSnapshot() {
        editorFormSnapshot = getEditorFormSnapshot();
    }

    function hasFormChanges() {
        if (!editorFormSnapshot) return false;
        return getEditorFormSnapshot() !== editorFormSnapshot;
    }

    function closeEditorModal(force = false) {
        if (!force && hasFormChanges()) {
            showCustomConfirm("Unsaved Changes", "You have unsaved changes. Do you want to discard them?", () => {
                document.getElementById("question-editor-modal").classList.add("hidden");
                resetEditorForm();
            });
        } else {
            document.getElementById("question-editor-modal").classList.add("hidden");
            resetEditorForm();
        }
    }

    function editQuestion(q) {
        document.getElementById("editor-title").textContent = "Edit Question";
        document.getElementById("editor-q-id").value = q.id;
        document.getElementById("editor-q-position").value = q.position || "";
        
        // Segment control
        const radios = document.getElementsByName("editor-section");
        radios.forEach(r => {
            r.checked = (r.value === q.section);
        });
        
        document.getElementById("editor-stem").value = q.stem;
        document.getElementById("editor-opt-a").value = q.options[0];
        document.getElementById("editor-opt-b").value = q.options[1];
        document.getElementById("editor-opt-c").value = q.options[2];
        document.getElementById("editor-opt-d").value = q.options[3];
        
        // Answer radio
        const ansRadios = document.getElementsByName("editor-answer");
        ansRadios.forEach(ar => {
            ar.checked = (parseInt(ar.value) === q.answer);
        });
        
        document.getElementById("editor-active").checked = q.active;
        document.getElementById("btn-delete-question").classList.remove("hidden");
        
        // Show modal and take snapshot
        document.getElementById("question-editor-modal").classList.remove("hidden");
        takeFormSnapshot();
    }

    function deleteQuestion(id) {
        showCustomConfirm("Delete Question", "Permanently delete this question? This cannot be undone.", async () => {
            try {
                await apiRequest(`/api/admin/questions/${id}`, "DELETE");
                toastSuccess("Question deleted.");
                closeEditorModal(true);
                loadQuestionsTab();
            } catch (err) {
                toastError("Delete operation failed.");
            }
        });
    }

    // Ghost buttons add question trigger
    document.querySelectorAll(".btn-add-q").forEach(btn => {
        btn.addEventListener("click", () => {
            resetEditorForm();
            const sec = btn.dataset.section;
            const radios = document.getElementsByName("editor-section");
            radios.forEach(r => {
                r.checked = (r.value === sec);
            });
            document.getElementById("question-editor-modal").classList.remove("hidden");
            takeFormSnapshot();
        });
    });

    function resetEditorForm() {
        document.getElementById("editor-title").textContent = "Add Question";
        document.getElementById("editor-q-id").value = "";
        document.getElementById("editor-q-position").value = "";
        document.getElementById("question-editor-form").reset();
        document.getElementById("editor-active").checked = true;
        document.getElementById("btn-delete-question").classList.add("hidden");
        editorFormSnapshot = null;
    }

    document.getElementById("btn-cancel-edit").addEventListener("click", (e) => {
        e.preventDefault();
        closeEditorModal(false);
    });

    document.getElementById("btn-close-question-modal").addEventListener("click", () => {
        closeEditorModal(false);
    });

    // Close on click outside modal card
    const editorModalEl = document.getElementById("question-editor-modal");
    editorModalEl.addEventListener("click", (e) => {
        if (e.target === editorModalEl) {
            closeEditorModal(false);
        }
    });

    document.getElementById("btn-delete-question").addEventListener("click", () => {
        const qId = document.getElementById("editor-q-id").value;
        if (qId) {
            deleteQuestion(parseInt(qId));
        }
    });

    editorForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const qId = document.getElementById("editor-q-id").value;
        
        const sectionEl = document.querySelector('input[name="editor-section"]:checked');
        const answerEl = document.querySelector('input[name="editor-answer"]:checked');
        
        const payload = {
            section: sectionEl ? sectionEl.value : "Numerical",
            stem: document.getElementById("editor-stem").value.trim(),
            options: [
                document.getElementById("editor-opt-a").value.trim(),
                document.getElementById("editor-opt-b").value.trim(),
                document.getElementById("editor-opt-c").value.trim(),
                document.getElementById("editor-opt-d").value.trim()
            ],
            answer: answerEl ? parseInt(answerEl.value) : 0,
            active: document.getElementById("editor-active").checked,
            position: document.getElementById("editor-q-position").value ? parseInt(document.getElementById("editor-q-position").value) : null
        };
        
        try {
            if (qId) {
                // Update
                await apiRequest(`/api/admin/questions/${qId}`, "PUT", payload);
                toastSuccess("Question updated.");
            } else {
                // Create
                await apiRequest("/api/admin/questions", "POST", payload);
                toastSuccess("Question created.");
            }
            closeEditorModal(true);
            loadQuestionsTab();
        } catch (err) {
            toastError(err.message);
        }
    });

    // ── Bulk Upload JSON ──
    document.getElementById("btn-import-json").addEventListener("click", async () => {
        const textarea = document.getElementById("bulk-json-paste");
        const val = textarea.value.trim();
        if (!val) return;
        
        try {
            const arr = JSON.parse(val);
            const res = await apiRequest("/api/admin/questions/bulk", "POST", arr);
            toastSuccess(`Import completed. Added: ${res.added}, Skipped/Duplicate: ${res.skipped}`);
            textarea.value = "";
            loadQuestionsTab();
        } catch (err) {
            toastError("Failed to parse JSON array or upload data.");
        }
    });

    // ── Bulk Upload CSV ──
    const btnTriggerCsv = document.getElementById("btn-trigger-csv");
    const csvFileInput = document.getElementById("csv-file-input");
    const csvFileName = document.getElementById("csv-file-name");
    const csvPreviewText = document.getElementById("csv-preview-text");
    const btnImportCsv = document.getElementById("btn-import-csv");
    
    let parsedCsvQuestions = [];

    btnTriggerCsv.addEventListener("click", () => csvFileInput.click());
    csvFileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            csvFileName.textContent = file.name;
            
            const reader = new FileReader();
            reader.onload = () => {
                parseQuestionsCSV(reader.result);
            };
            reader.readAsText(file);
        }
    });

    function parseQuestionsCSV(text) {
        const lines = text.split(/\r?\n/);
        parsedCsvQuestions = [];
        
        // Find headers
        if (lines.length <= 1) return;
        const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
        
        // Map columns
        const colIdx = {
            section: headers.indexOf("section"),
            stem: headers.indexOf("stem"),
            option_a: headers.indexOf("option_a"),
            option_b: headers.indexOf("option_b"),
            option_c: headers.indexOf("option_c"),
            option_d: headers.indexOf("option_d"),
            answer: headers.indexOf("answer")
        };
        
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            
            // Basic CSV Split (handles quotes optionally)
            const row = splitCSVLine(line);
            
            const section = row[colIdx.section];
            const stem = row[colIdx.stem];
            const optA = row[colIdx.option_a];
            const optB = row[colIdx.option_b];
            const optC = row[colIdx.option_c];
            const optD = row[colIdx.option_d];
            const answer = parseInt(row[colIdx.answer]);
            
            if (section && stem && optA && optB && optC && optD && !isNaN(answer)) {
                parsedCsvQuestions.push({
                    section: section.trim(),
                    stem: stem.trim(),
                    options: [optA.trim(), optB.trim(), optC.trim(), optD.trim()],
                    answer: answer,
                    active: true
                });
            }
        }
        
        csvPreviewText.textContent = `${parsedCsvQuestions.length} questions parsed successfully.`;
        csvPreviewText.classList.remove("hidden");
        btnImportCsv.removeAttribute("disabled");
    }

    btnImportCsv.addEventListener("click", async () => {
        if (parsedCsvQuestions.length === 0) return;
        try {
            const res = await apiRequest("/api/admin/questions/bulk", "POST", parsedCsvQuestions);
            toastSuccess(`Imported CSV. Added: ${res.added}, Skipped/Duplicate: ${res.skipped}`);
            
            // reset file
            csvFileInput.value = "";
            csvFileName.textContent = "No file selected";
            csvPreviewText.classList.add("hidden");
            btnImportCsv.setAttribute("disabled", "true");
            parsedCsvQuestions = [];
            loadQuestionsTab();
        } catch (err) {
            toastError("CSV Import failed.");
        }
    });

    // Helper: CSV comma splitter that honors double quotes
    function splitCSVLine(line) {
        const result = [];
        let insideQuote = false;
        let entry = "";
        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            if (char === '"') {
                insideQuote = !insideQuote;
            } else if (char === ',' && !insideQuote) {
                result.push(entry);
                entry = "";
            } else {
                entry += char;
            }
        }
        result.push(entry);
        return result.map(e => e.replace(/^"(.*)"$/, '$1')); // strip quotes
    }

    // ── Panel 3: Candidates & Results ──
    let currentResultsPage = 1;
    let currentResultsSort = "submitted_at";
    let currentResultsOrder = "DESC";

    async function loadResultsTab() {
        try {
            const res = await apiRequest(`/api/admin/results?page=${currentResultsPage}&sort=${currentResultsSort}&order=${currentResultsOrder}`);
            
            // Populate Mini Stats
            document.getElementById("results-stat-total").textContent = res.summary.total;
            document.getElementById("results-stat-passed").textContent = res.summary.passed;
            document.getElementById("results-stat-failed").textContent = res.summary.failed;
            document.getElementById("results-stat-avg").textContent = `${res.summary.avg_score}%`;
            document.getElementById("results-stat-time").textContent = `${formatTime(res.summary.avg_time)}`;
            
            renderResultsTable(res.results);
            
            // Pagination state
            document.getElementById("page-indicator").textContent = `Page ${res.page}`;
            document.getElementById("btn-prev-page").disabled = (res.page === 1);
            // If results returned is less than 25, disable next page
            document.getElementById("btn-next-page").disabled = (res.results.length < 25);
        } catch (err) {
            toastError("Failed to fetch results.");
        }
    }

    function renderResultsTable(results) {
        const tbody = document.getElementById("results-tbody");
        tbody.replaceChildren();
        
        if (results.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.setAttribute("colspan", "11");
            td.style.textAlign = "center";
            td.textContent = "No candidate exam results recorded.";
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }
        
        results.forEach(r => {
            const tr = document.createElement("tr");
            
            const tdName = document.createElement("td");
            tdName.style.fontWeight = "600";
            tdName.textContent = r.name;
            
            const tdEmail = document.createElement("td");
            tdEmail.textContent = r.email;
            
            const tdPhone = document.createElement("td");
            tdPhone.textContent = r.phone_number;
            
            const tdRole = document.createElement("td");
            tdRole.textContent = r.role;
            
            const tdLocation = document.createElement("td");
            tdLocation.textContent = r.location;
            
            const tdScore = document.createElement("td");
            tdScore.className = "font-mono";
            tdScore.textContent = `${r.score_percent}% (${r.score_fraction})`;
            
            const tdBadge = document.createElement("td");
            const badge = document.createElement("span");
            badge.className = `badge ${r.pass_fail === 'PASS' ? 'badge-pass' : 'badge-fail'}`;
            badge.textContent = r.pass_fail;
            tdBadge.appendChild(badge);
            
            const tdTime = document.createElement("td");
            tdTime.className = "font-mono";
            tdTime.textContent = formatTime(r.time_taken_secs);
            
            const tdSwitches = document.createElement("td");
            tdSwitches.className = "font-mono";
            tdSwitches.textContent = r.tab_switches;
            
            const tdDate = document.createElement("td");
            tdDate.textContent = new Date(r.submitted_at).toLocaleString();
            
            const tdVerification = document.createElement("td");
            const btnSelfie = document.createElement("button");
            btnSelfie.type = "button";
            btnSelfie.className = "btn-icon";
            btnSelfie.title = "View Selfie";
            const iconCam = document.createElement("i");
            iconCam.className = "ti ti-camera";
            btnSelfie.appendChild(iconCam);
            btnSelfie.addEventListener("click", () => openLightbox(r.candidate_id, "selfie"));
            
            const btnId = document.createElement("button");
            btnId.type = "button";
            btnId.className = "btn-icon";
            btnId.title = "View ID Card";
            const iconId = document.createElement("i");
            iconId.className = "ti ti-id-badge";
            btnId.appendChild(iconId);
            btnId.addEventListener("click", () => openLightbox(r.candidate_id, "idcard"));
            
            tdVerification.appendChild(btnSelfie);
            tdVerification.appendChild(btnId);
            
            tr.appendChild(tdName);
            tr.appendChild(tdEmail);
            tr.appendChild(tdPhone);
            tr.appendChild(tdRole);
            tr.appendChild(tdLocation);
            tr.appendChild(tdScore);
            tr.appendChild(tdBadge);
            tr.appendChild(tdTime);
            tr.appendChild(tdSwitches);
            tr.appendChild(tdDate);
            tr.appendChild(tdVerification);
            
            tbody.appendChild(tr);
        });
    }

    // Pagination handlers
    document.getElementById("btn-prev-page").addEventListener("click", () => {
        if (currentResultsPage > 1) {
            currentResultsPage--;
            loadResultsTab();
        }
    });

    document.getElementById("btn-next-page").addEventListener("click", () => {
        currentResultsPage++;
        loadResultsTab();
    });

    document.getElementById("btn-clear-results").addEventListener("click", () => {
        showCustomConfirm(
            "Clear All Results",
            "Are you sure you want to permanently clear all candidate registrations and exam results? This resets the portal and cannot be undone.",
            async () => {
                try {
                    await apiRequest("/api/admin/results/clear", "POST");
                    toastSuccess("All results and registrations cleared successfully.");
                    currentResultsPage = 1;
                    loadResultsTab();
                } catch (err) {
                    toastError("Failed to clear results.");
                }
            }
        );
    });

    // Sorting headers
    document.querySelectorAll(".data-table th.sortable").forEach(th => {
        th.addEventListener("click", () => {
            const col = th.dataset.sort;
            if (currentResultsSort === col) {
                currentResultsOrder = (currentResultsOrder === "ASC") ? "DESC" : "ASC";
            } else {
                currentResultsSort = col;
                currentResultsOrder = "DESC";
            }
            
            // Update UI sort classes
            document.querySelectorAll(".data-table th.sortable").forEach(header => {
                header.classList.remove("active");
                const icon = header.querySelector(".sort-icon");
                if (icon) icon.className = "sort-icon";
            });
            
            th.classList.add("active");
            const icon = th.querySelector(".sort-icon");
            if (icon) {
                icon.className = `sort-icon ${currentResultsOrder.toLowerCase()}`;
            }
            
            currentResultsPage = 1;
            loadResultsTab();
        });
    });

    // Lightbox modal operations
    const lightboxModal = document.getElementById("lightbox-modal");
    const lightboxImg = document.getElementById("lightbox-img");

    function openLightbox(candidateId, type) {
        // Fetch securely proxied bytes via Flask route directly into img src
        lightboxImg.src = `/api/admin/image/${candidateId}/${type}`;
        lightboxModal.classList.remove("hidden");
    }

    // Close lightbox on clicking outside image container
    lightboxModal.addEventListener("click", (e) => {
        if (e.target === lightboxModal || e.target.classList.contains("lightbox-content") || e.target.className === "lightbox-caption") {
            lightboxModal.classList.add("hidden");
            lightboxImg.src = "";
        }
    });

    // Time Formatter helper: SS -> MMm SSs
    function formatTime(totalSecs) {
        if (isNaN(totalSecs) || totalSecs < 0) return "0s";
        const m = Math.floor(totalSecs / 60);
        const s = totalSecs % 60;
        return m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    // ── Panel 4: Whitelist ──
    const whitelistForm = document.getElementById("whitelist-add-form");
    const whitelistEmailInput = document.getElementById("whitelist-email");
    const whitelistTbody = document.getElementById("whitelist-tbody");
    
    const whitelistCsvBtn = document.getElementById("btn-trigger-whitelist-csv");
    const whitelistCsvInput = document.getElementById("whitelist-csv-input");
    const whitelistCsvName = document.getElementById("whitelist-csv-name");
    const whitelistPreview = document.getElementById("whitelist-preview-text");
    const btnImportWhitelistCsv = document.getElementById("btn-import-whitelist-csv");
    
    let parsedWhitelistEmails = [];

    async function loadWhitelistTab() {
        try {
            const list = await apiRequest("/api/admin/whitelist");
            document.getElementById("whitelist-count-badge").textContent = list.length;
            renderWhitelistTable(list);
        } catch (err) {
            toastError("Failed to fetch whitelist.");
        }
    }

    function renderWhitelistTable(list) {
        whitelistTbody.replaceChildren();
        
        if (list.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.setAttribute("colspan", "3");
            td.style.textAlign = "center";
            td.textContent = "Whitelist is empty.";
            tr.appendChild(td);
            whitelistTbody.appendChild(tr);
            return;
        }
        
        list.forEach(item => {
            const tr = document.createElement("tr");
            
            const tdEmail = document.createElement("td");
            tdEmail.style.fontWeight = "600";
            tdEmail.textContent = item.email;
            
            const tdDate = document.createElement("td");
            tdDate.textContent = new Date(item.added_at).toLocaleDateString();
            
            const tdAction = document.createElement("td");
            tdAction.className = "action-cell";
            const btnDel = document.createElement("button");
            btnDel.type = "button";
            btnDel.className = "btn-icon btn-icon-danger";
            const iconTrash = document.createElement("i");
            iconTrash.className = "ti ti-trash";
            btnDel.appendChild(iconTrash);
            btnDel.addEventListener("click", () => removeEmailFromWhitelist(item.id));
            
            tdAction.appendChild(btnDel);
            
            tr.appendChild(tdEmail);
            tr.appendChild(tdDate);
            tr.appendChild(tdAction);
            whitelistTbody.appendChild(tr);
        });
    }

    whitelistForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = whitelistEmailInput.value.trim();
        if (!email) return;
        
        try {
            const res = await apiRequest("/api/admin/whitelist", "POST", { email });
            toastSuccess(res.message);
            whitelistEmailInput.value = "";
            loadWhitelistTab();
        } catch (err) {
            toastError(err.message);
        }
    });

    function removeEmailFromWhitelist(id) {
        showCustomConfirm("Remove Email", "Remove email from whitelist?", async () => {
            try {
                await apiRequest(`/api/admin/whitelist/${id}`, "DELETE");
                toastSuccess("Removed successfully.");
                loadWhitelistTab();
            } catch (err) {
                toastError("Failed to remove email.");
            }
        });
    }

    function clearWhitelist() {
        showCustomConfirm("Clear Whitelist", "Are you sure you want to permanently clear all whitelisted emails? This cannot be undone.", async () => {
            try {
                await apiRequest("/api/admin/whitelist/clear", "POST");
                toastSuccess("Whitelist cleared successfully.");
                loadWhitelistTab();
            } catch (err) {
                toastError("Failed to clear whitelist.");
            }
        });
    }

    document.getElementById("btn-clear-whitelist").addEventListener("click", clearWhitelist);

    // Whitelist CSV bulk imports
    whitelistCsvBtn.addEventListener("click", () => whitelistCsvInput.click());
    whitelistCsvInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            whitelistCsvName.textContent = file.name;
            
            const reader = new FileReader();
            reader.onload = () => {
                parseWhitelistCSV(reader.result);
            };
            reader.readAsText(file);
        }
    });

    function parseWhitelistCSV(text) {
        const lines = text.split(/\r?\n/);
        parsedWhitelistEmails = [];
        
        lines.forEach(line => {
            const email = line.trim().toLowerCase();
            // Simple regex match for email validation
            if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                parsedWhitelistEmails.push(email);
            }
        });
        
        whitelistPreview.textContent = `${parsedWhitelistEmails.length} valid emails parsed.`;
        whitelistPreview.classList.remove("hidden");
        btnImportWhitelistCsv.removeAttribute("disabled");
    }

    btnImportWhitelistCsv.addEventListener("click", async () => {
        if (parsedWhitelistEmails.length === 0) return;
        try {
            const res = await apiRequest("/api/admin/whitelist/bulk", "POST", { emails: parsedWhitelistEmails });
            toastSuccess(`Whitelist CSV Imported. Added: ${res.added}, Duplicate/Skipped: ${res.skipped}`);
            
            // reset
            whitelistCsvInput.value = "";
            whitelistCsvName.textContent = "No file selected";
            whitelistPreview.classList.add("hidden");
            btnImportWhitelistCsv.setAttribute("disabled", "true");
            parsedWhitelistEmails = [];
            loadWhitelistTab();
        } catch (err) {
            toastError("Whitelist CSV Import failed.");
        }
    });

    // ── Initial Tab Load ──
    loadSettingsTab();
}

// Page Router Initialization
document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("reg-form")) {
        initCandidatePortal();
    } else if (document.getElementById("admin-login-form") || document.querySelector(".admin-dashboard-container")) {
        initAdminDashboard();
    }
});
