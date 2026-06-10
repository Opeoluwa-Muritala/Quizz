# config.py - Startup defaults for Mainstreet MFB Aptitude Test

EXAM_TITLE = "Mainstreet MFB Aptitude Test"
PASS_MARK_PERCENT = 50.0
SECONDS_PER_QUESTION = 60

# Whitelist emails (seeded if whitelist table is empty)
WHITELIST_SEEDS = [
    "storytelling1622@gmail.com",
    "Juchenna@mainstreetmfb.com",
    "eguuchennajohn@gmail.com",
    "muritalaopeoluwa10@gmail.com",
    "test@mail.com",
    "uju.umar9029@gmail.com",
    "vera.ganiyu8374@live.com",
    "godwin.nwosu9536@protonmail.com",
    "dotun.eze4772@protonmail.com",
    "ibrahim.eferebo2905@icloud.com",
    "jumoke.vincent9629@icloud.com",
    "emeka.chukwu9990@hotmail.com",
    "nneka.dada9149@outlook.com",
    "adaeze.hassan3182@icloud.com",
    "victoria.lawan4426@protonmail.com",
    "patience.diallo4109@live.com",
    "amara.eferebo8306@protonmail.com",
    "ibrahim.ogundipe5663@live.com",
    "obinna.peters3207@outlook.com",
    "nneka.kareem1450@hotmail.com",
    "ibrahim.tobi6677@yahoo.com",
    "funmi.diallo6974@icloud.com",
    "madu.qasim8153@yahoo.com",
    "precious.coker8173@icloud.com",
    "jumoke.ihejirika9141@live.com",
    "wale.ganiyu8181@yahoo.com",
    "toyin.yusuf5525@live.com",
    "seun.vandi6935@protonmail.com",
    "emeka.philips7079@icloud.com",
    "hauwa.vincent3163@gmail.com",
    "kelechi.vincent8159@gmail.com",
    "efosa.rasheed9380@gmail.com",
    "tunde.taiwo5585@icloud.com",
    "kunle.umar1983@protonmail.com",
    "jumoke.vandi7393@gmail.com",
    "victoria.diallo3367@protonmail.com",
    "josephine.vincent7304@hotmail.com",
    "hauwa.kareem5791@gmail.com",
    "jumoke.peters4269@hotmail.com",
    "efosa.fagbohun2554@gmail.com",
    "zainab.xavier2347@outlook.com",
    "funmi.okonkwo1810@yahoo.com",
    "nneka.ganiyu4225@live.com",
    "rahmat.taiwo9136@outlook.com",
    "musa.eze8141@protonmail.com",
    "efosa.ogundipe1544@hotmail.com",
    "adaeze.eze8238@live.com",
    "efosa.qasim6660@protonmail.com",
    "gbenga.hamza2111@gmail.com",
    "ibrahim.okonkwo8034@yahoo.com",
    "emeka.nwosu9121@icloud.com",
    "seun.qasim4454@protonmail.com",
    "amara.lawan6469@protonmail.com",
    "vera.tobi4855@live.com",
    "seun.bakare4182@yahoo.com",
    "qudus.yusuf5097@yahoo.com",
    "ike.jibril6118@gmail.com",
    "ibrahim.peters6531@icloud.com",
    "tunde.williams5689@outlook.com",
    "chukwuemeka.balogun5093@yahoo.com",
    "vera.yusuf2191@yahoo.com",
    "musa.lawan7634@outlook.com",
    "damilola.kareem5760@yahoo.com",
    "uche.eferebo1125@yahoo.com",
    "chukwuemeka.kanu2510@protonmail.com",
    "lami.qasim6717@outlook.com",
    "chukwuemeka.ogundipe5525@outlook.com",
    "wasiu.quadri7582@yahoo.com",
    "tunde.vandi8856@hotmail.com",
    "wasiu.bakare1272@gmail.com",
    "uche.eferebo1240@yahoo.com",
    "remi.bakare7167@hotmail.com",
    "damilola.balogun1137@hotmail.com",
    "sade.adeyemi1145@yahoo.com",
    "hauwa.sanni4087@yahoo.com",
    "dotun.vandi3020@gmail.com",
    "gbenga.umar1392@yahoo.com",
    "vera.garba7960@gmail.com",
    "vera.sanni1061@protonmail.com",
    "remi.fagbohun4184@hotmail.com",
    "amara.abiodun7826@yahoo.com",
    "gbenga.hamza4551@live.com",
    "chioma.hamza7714@gmail.com",
    "wasiu.ogundipe8352@icloud.com",
    "bello.vandi7998@outlook.com",
    "victoria.kareem7227@yahoo.com",
    "rahmat.raji3583@yahoo.com",
    "toyin.nwosu1896@outlook.com",
    "chukwuemeka.jimoh6034@live.com",
    "chukwuemeka.peters1834@outlook.com",
    "nneka.qasim6798@icloud.com",
    "funmi.diallo4317@yahoo.com",
    "chioma.salami8095@outlook.com",
    "kelechi.vandi1148@protonmail.com",
    "obinna.uchenna6278@icloud.com",
    "ngozi.chukwu9791@icloud.com"
]

# Initial 50 questions
QUESTIONS = [
    # ── Numerical Reasoning (1 - 15) ──────────────────────────────────
    {
        "id": 1,
        "section": "Numerical",
        "stem": "A company’s revenue increased from ₦4,000,000 to ₦5,200,000. What is the percentage increase?",
        "options": ["20%", "25%", "30%", "35%"],
        "answer": 2,
        "active": True
    },
    {
        "id": 2,
        "section": "Numerical",
        "stem": "If ₦48,000 is invested at 10% simple interest for 2 years, what is the total amount?",
        "options": ["₦52,800", "₦57,600", "₦58,000", "₦60,000"],
        "answer": 1,
        "active": True
    },
    {
        "id": 3,
        "section": "Numerical",
        "stem": "Solve for x: 3x - 9 = 18",
        "options": ["7", "8", "9", "10"],
        "answer": 2,
        "active": True
    },
    {
        "id": 4,
        "section": "Numerical",
        "stem": "A trader bought a product for ₦25,000 and sold it for ₦31,250. Calculate the profit percentage.",
        "options": ["20%", "25%", "30%", "35%"],
        "answer": 1,
        "active": True
    },
    {
        "id": 5,
        "section": "Numerical",
        "stem": "If 8 workers complete a task in 15 days, how many days will 12 workers take?",
        "options": ["8 days", "10 days", "12 days", "14 days"],
        "answer": 1,
        "active": True
    },
    {
        "id": 6,
        "section": "Numerical",
        "stem": "Find the missing number: 5, 10, 20, 40, ___",
        "options": ["60", "70", "80", "100"],
        "answer": 2,
        "active": True
    },
    {
        "id": 7,
        "section": "Numerical",
        "stem": "A car travels 360 km in 6 hours. What is the average speed?",
        "options": ["50 km/h", "55 km/h", "60 km/h", "65 km/h"],
        "answer": 2,
        "active": True
    },
    {
        "id": 8,
        "section": "Numerical",
        "stem": "The ratio of boys to girls in a class is 2:3. If there are 30 students, how many are boys?",
        "options": ["10", "12", "15", "18"],
        "answer": 1,
        "active": True
    },
    {
        "id": 9,
        "section": "Numerical",
        "stem": "What is 15% of ₦80,000?",
        "options": ["₦10,000", "₦12,000", "₦14,000", "₦16,000"],
        "answer": 1,
        "active": True
    },
    {
        "id": 10,
        "section": "Numerical",
        "stem": "Solve: x² - 25 = 0",
        "options": ["3", "4", "5", "6"],
        "answer": 2,
        "active": True
    },
    {
        "id": 11,
        "section": "Numerical",
        "stem": "A business spent ₦120,000 on salaries and ₦80,000 on logistics. What percentage was spent on logistics?",
        "options": ["35%", "40%", "45%", "50%"],
        "answer": 1,
        "active": True
    },
    {
        "id": 12,
        "section": "Numerical",
        "stem": "If a laptop costs ₦250,000 after a 20% discount, what was the original price?",
        "options": ["₦280,000", "₦300,000", "₦312,500", "₦325,000"],
        "answer": 2,
        "active": True
    },
    {
        "id": 13,
        "section": "Numerical",
        "stem": "A company’s staff strength increased from 150 to 180 employees. Calculate the percentage increase.",
        "options": ["15%", "18%", "20%", "25%"],
        "answer": 2,
        "active": True
    },
    {
        "id": 14,
        "section": "Numerical",
        "stem": "What is the average of 12, 18, 24, and 30?",
        "options": ["18", "19", "20", "21"],
        "answer": 3,
        "active": True
    },
    {
        "id": 15,
        "section": "Numerical",
        "stem": "If ₦500,000 is shared in the ratio 2:3, how much does the larger share receive?",
        "options": ["₦200,000", "₦250,000", "₦300,000", "₦350,000"],
        "answer": 2,
        "active": True
    },

    # ── Verbal Reasoning (16 - 30) ───────────────────────────────────
    {
        "id": 16,
        "section": "Verbal",
        "stem": "Choose the word closest in meaning to “Efficient.”",
        "options": ["Slow", "Productive", "Weak", "Careless"],
        "answer": 1,
        "active": True
    },
    {
        "id": 17,
        "section": "Verbal",
        "stem": "Choose the opposite of “Expand.”",
        "options": ["Reduce", "Increase", "Improve", "Extend"],
        "answer": 0,
        "active": True
    },
    {
        "id": 18,
        "section": "Verbal",
        "stem": "Identify the correctly written sentence.",
        "options": [
            "She don’t understand the process.",
            "She doesn’t understands the process.",
            "She doesn’t understand the process.",
            "She not understand the process."
        ],
        "answer": 2,
        "active": True
    },
    {
        "id": 19,
        "section": "Verbal",
        "stem": "Fill in the blank: The manager and his assistant _____ attending the meeting.",
        "options": ["is", "are", "was", "has"],
        "answer": 1,
        "active": True
    },
    {
        "id": 20,
        "section": "Verbal",
        "stem": "Choose the correctly spelled word.",
        "options": ["Enviroment", "Environment", "Environmant", "Enviornment"],
        "answer": 1,
        "active": True
    },
    {
        "id": 21,
        "section": "Verbal",
        "stem": "What is the meaning of the idiom “once in a blue moon”?",
        "options": ["Frequently", "Rarely", "Suddenly", "Daily"],
        "answer": 1,
        "active": True
    },
    {
        "id": 22,
        "section": "Verbal",
        "stem": "Choose the word that best completes the sentence: The employees were asked to _____ the new policy immediately.",
        "options": ["implement", "implementing", "implemented", "implementation"],
        "answer": 0,
        "active": True
    },
    {
        "id": 23,
        "section": "Verbal",
        "stem": "Which word does not belong?",
        "options": ["Lion", "Tiger", "Elephant", "Carrot"],
        "answer": 3,
        "active": True
    },
    {
        "id": 24,
        "section": "Verbal",
        "stem": "Complete the analogy: Book is to Reading as Fork is to _____.",
        "options": ["Cooking", "Eating", "Washing", "Drinking"],
        "answer": 1,
        "active": True
    },
    {
        "id": 25,
        "section": "Verbal",
        "stem": "Choose the sentence with correct punctuation.",
        "options": [
            "However we continued the meeting.",
            "However, we continued the meeting.",
            "However we, continued the meeting.",
            "However; we continued the meeting."
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 26,
        "section": "Verbal",
        "stem": "What is the synonym of “Reliable”?",
        "options": ["Dependable", "Weak", "Uncertain", "Dishonest"],
        "answer": 0,
        "active": True
    },
    {
        "id": 27,
        "section": "Verbal",
        "stem": "Identify the error: “Each of the employees have submitted their reports.”",
        "options": ["Each", "employees", "have", "reports"],
        "answer": 2,
        "active": True
    },
    {
        "id": 28,
        "section": "Verbal",
        "stem": "Choose the best meaning of “confidential.”",
        "options": ["Public", "Secret", "Dangerous", "Important"],
        "answer": 1,
        "active": True
    },
    {
        "id": 29,
        "section": "Verbal",
        "stem": "Select the correct passive form: “The company launched a new product.”",
        "options": [
            "A new product launches the company.",
            "A new product was launched by the company.",
            "The company was launched by a new product.",
            "A new product is launching the company."
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 30,
        "section": "Verbal",
        "stem": "Choose the correct word: The training session was very _____.",
        "options": ["inform", "informative", "information", "informed"],
        "answer": 1,
        "active": True
    },

    # ── Logical Reasoning (31 - 50) ──────────────────────────────────
    {
        "id": 31,
        "section": "Logical",
        "stem": "Find the next number: 2, 6, 12, 20, 30, ___",
        "options": ["36", "40", "42", "44"],
        "answer": 2,
        "active": True
    },
    {
        "id": 32,
        "section": "Logical",
        "stem": "If all bankers are graduates and some graduates are managers, which statement is definitely true?",
        "options": [
            "All managers are bankers",
            "Some graduates are managers",
            "All graduates are bankers",
            "No bankers are managers"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 33,
        "section": "Logical",
        "stem": "A customer is angry because a transfer failed. What should you do first?",
        "options": [
            "Ignore the customer",
            "Explain bank policy immediately",
            "Listen and verify the complaint",
            "End the conversation"
        ],
        "answer": 2,
        "active": True
    },
    {
        "id": 34,
        "section": "Logical",
        "stem": "Choose the odd one out.",
        "options": ["Laptop", "Keyboard", "Printer", "Banana"],
        "answer": 3,
        "active": True
    },
    {
        "id": 35,
        "section": "Logical",
        "stem": "If today is Friday, what day will it be in 10 days?",
        "options": ["Sunday", "Monday", "Tuesday", "Wednesday"],
        "answer": 1,
        "active": True
    },
    {
        "id": 36,
        "section": "Logical",
        "stem": "A team missed its target due to poor communication. What is the best corrective action?",
        "options": [
            "Ignore the issue",
            "Improve communication channels",
            "Punish everyone",
            "Reduce staff salaries"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 37,
        "section": "Logical",
        "stem": "Rearrange the letters “LPAEN” to form a meaningful word.",
        "options": ["PANEL", "PENAL", "PLANE", "Both A and C"],
        "answer": 3,
        "active": True
    },
    {
        "id": 38,
        "section": "Logical",
        "stem": "A colleague takes credit for your work. What is the best response?",
        "options": [
            "Start an argument publicly",
            "Report immediately without discussion",
            "Discuss professionally with the colleague",
            "Ignore permanently"
        ],
        "answer": 2,
        "active": True
    },
    {
        "id": 39,
        "section": "Logical",
        "stem": "Find the missing letter sequence: A, C, F, J, O, ___",
        "options": ["T", "U", "V", "W"],
        "answer": 1,
        "active": True
    },
    {
        "id": 40,
        "section": "Logical",
        "stem": "Which action best demonstrates integrity?",
        "options": [
            "Hiding mistakes",
            "Taking credit for others’ work",
            "Reporting errors honestly",
            "Ignoring company policy"
        ],
        "answer": 2,
        "active": True
    },
    {
        "id": 41,
        "section": "Logical",
        "stem": "A company’s sales dropped despite increased marketing. What should management investigate first?",
        "options": [
            "Employee uniforms",
            "Product quality and customer feedback",
            "Office furniture",
            "Staff birthdays"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 42,
        "section": "Logical",
        "stem": "If all pens are books and all books are bags, then all pens are:",
        "options": ["Bags", "Pencils", "Tables", "Papers"],
        "answer": 0,
        "active": True
    },
    {
        "id": 43,
        "section": "Logical",
        "stem": "You are assigned a task outside your expertise. What should you do?",
        "options": [
            "Reject the task immediately",
            "Seek guidance and learn quickly",
            "Ignore instructions",
            "Delegate without approval"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 44,
        "section": "Logical",
        "stem": "Choose the next number: 1, 4, 9, 16, 25, ___",
        "options": ["30", "35", "36", "49"],
        "answer": 2,
        "active": True
    },
    {
        "id": 45,
        "section": "Logical",
        "stem": "A customer requests another customer’s account details. What should you do?",
        "options": [
            "Share limited information",
            "Refuse and protect confidentiality",
            "Ask another staff member",
            "Ignore the customer"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 46,
        "section": "Logical",
        "stem": "Which option best describes teamwork?",
        "options": [
            "Competing against colleagues",
            "Working independently always",
            "Collaborating toward common goals",
            "Avoiding responsibility"
        ],
        "answer": 2,
        "active": True
    },
    {
        "id": 47,
        "section": "Logical",
        "stem": "A manager gives unclear instructions. What should you do?",
        "options": [
            "Assume details",
            "Ask for clarification",
            "Ignore the task",
            "Wait indefinitely"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 48,
        "section": "Logical",
        "stem": "Find the odd number: 8, 16, 24, 33, 40",
        "options": ["8", "16", "24", "33"],
        "answer": 3,
        "active": True
    },
    {
        "id": 49,
        "section": "Logical",
        "stem": "Why is customer service important?",
        "options": [
            "It wastes company time",
            "It improves customer satisfaction and loyalty",
            "It reduces communication",
            "It increases complaints"
        ],
        "answer": 1,
        "active": True
    },
    {
        "id": 50,
        "section": "Logical",
        "stem": "If you discover an error in a financial report, what should you do first?",
        "options": [
            "Hide the error",
            "Correct it quietly without informing anyone",
            "Report and correct the error promptly",
            "Ignore it if it seems small"
        ],
        "answer": 2,
        "active": True
    }
]
