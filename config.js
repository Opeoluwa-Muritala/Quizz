const QUIZ_CONFIG = {
  title: "Mainstreet Exam Portal",
  description: "Complete all questions before the time runs out.",
  passMark: 70,
  adminPassword: "admin123",
  logo: "./logo1.png",
  sheetsWebAppUrl: "https://script.google.com/macros/s/AKfycbxPRFsKC8-FBvnjXAGSyXyP9pq95faOhVfiOCTVQTtGeHAl7_isMm0Bnf3uD5e-eai-/exec",
  sheetUrl: "https://docs.google.com/spreadsheets/d/1vkdOHo9Rrid2CnQOXHPYIRPSE_B84VRM-CA7yw5OAxk/edit?usp=sharing",


  questions: [
    {
      id: 1,
      type: "mcq",
      text: "A company’s revenue increased from ₦4,000,000 to ₦5,200,000. What is the percentage increase?",
      options: ["20%", "25%", "30%", "35%"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 2,
      type: "mcq",
      text: "If ₦48,000 is invested at 10% simple interest for 2 years, what is the total amount?",
      options: ["₦52,800", "₦57,600", "₦58,000", "₦60,000"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 3,
      type: "mcq",
      text: "Solve for x: 3x - 9 = 18",
      options: ["7", "8", "9", "10"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 4,
      type: "mcq",
      text: "A trader bought a product for ₦25,000 and sold it for ₦31,250. Calculate the profit percentage.",
      options: ["20%", "25%", "30%", "35%"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 5,
      type: "mcq",
      text: "If 8 workers complete a task in 15 days, how many days will 12 workers take?",
      options: ["8 days", "10 days", "12 days", "14 days"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 6,
      type: "mcq",
      text: "Find the missing number: 5, 10, 20, 40, ___",
      options: ["60", "70", "80", "100"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 7,
      type: "mcq",
      text: "A car travels 360 km in 6 hours. What is the average speed?",
      options: ["50 km/h", "55 km/h", "60 km/h", "65 km/h"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 8,
      type: "mcq",
      text: "The ratio of boys to girls in a class is 2:3. If there are 30 students, how many are boys?",
      options: ["10", "12", "15", "18"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 9,
      type: "mcq",
      text: "What is 15% of ₦80,000?",
      options: ["₦10,000", "₦12,000", "₦14,000", "₦16,000"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 10,
      type: "mcq",
      text: "Solve: x² - 25 = 0",
      options: ["3", "4", "5", "6"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 11,
      type: "mcq",
      text: "A business spent ₦120,000 on salaries and ₦80,000 on logistics. What percentage was spent on logistics?",
      options: ["35%", "40%", "45%", "50%"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 12,
      type: "mcq",
      text: "If a laptop costs ₦250,000 after a 20% discount, what was the original price?",
      options: ["₦280,000", "₦300,000", "₦312,500", "₦325,000"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 13,
      type: "mcq",
      text: "A company’s staff strength increased from 150 to 180 employees. Calculate the percentage increase.",
      options: ["15%", "18%", "20%", "25%"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 14,
      type: "mcq",
      text: "What is the average of 12, 18, 24, and 30?",
      options: ["18", "19", "20", "21"],
      correct: 3,
      timeLimit: 30
    },
    {
      id: 15,
      type: "mcq",
      text: "If ₦500,000 is shared in the ratio 2:3, how much does the larger share receive?",
      options: ["₦200,000", "₦250,000", "₦300,000", "₦350,000"],
      correct: 2,
      timeLimit: 30
    },

    {
      id: 16,
      type: "mcq",
      text: "Choose the word closest in meaning to “Efficient.”",
      options: ["Slow", "Productive", "Weak", "Careless"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 17,
      type: "mcq",
      text: "Choose the opposite of “Expand.”",
      options: ["Reduce", "Increase", "Improve", "Extend"],
      correct: 0,
      timeLimit: 30
    },
    {
      id: 18,
      type: "mcq",
      text: "Identify the correctly written sentence.",
      options: [
        "She don’t understand the process.",
        "She doesn’t understands the process.",
        "She doesn’t understand the process.",
        "She not understand the process."
      ],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 19,
      type: "mcq",
      text: "Fill in the blank: The manager and his assistant _____ attending the meeting.",
      options: ["is", "are", "was", "has"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 20,
      type: "mcq",
      text: "Choose the correctly spelled word.",
      options: ["Enviroment", "Environment", "Environmant", "Enviornment"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 21,
      type: "mcq",
      text: "What is the meaning of the idiom “once in a blue moon”?",
      options: ["Frequently", "Rarely", "Suddenly", "Daily"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 22,
      type: "mcq",
      text: "Choose the word that best completes the sentence: The employees were asked to _____ the new policy immediately.",
      options: ["implement", "implementing", "implemented", "implementation"],
      correct: 0,
      timeLimit: 30
    },
    {
      id: 23,
      type: "mcq",
      text: "Which word does not belong?",
      options: ["Lion", "Tiger", "Elephant", "Carrot"],
      correct: 3,
      timeLimit: 30
    },
    {
      id: 24,
      type: "mcq",
      text: "Complete the analogy: Book is to Reading as Fork is to _____.",
      options: ["Cooking", "Eating", "Washing", "Drinking"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 25,
      type: "mcq",
      text: "Choose the sentence with correct punctuation.",
      options: [
        "However we continued the meeting.",
        "However, we continued the meeting.",
        "However we, continued the meeting.",
        "However; we continued the meeting."
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 26,
      type: "mcq",
      text: "What is the synonym of “Reliable”?",
      options: ["Dependable", "Weak", "Uncertain", "Dishonest"],
      correct: 0,
      timeLimit: 30
    },
    {
      id: 27,
      type: "mcq",
      text: "Identify the error: “Each of the employees have submitted their reports.”",
      options: ["Each", "employees", "have", "reports"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 28,
      type: "mcq",
      text: "Choose the best meaning of “confidential.”",
      options: ["Public", "Secret", "Dangerous", "Important"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 29,
      type: "mcq",
      text: "Select the correct passive form: “The company launched a new product.”",
      options: [
        "A new product launches the company.",
        "A new product was launched by the company.",
        "The company was launched by a new product.",
        "A new product is launching the company."
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 30,
      type: "mcq",
      text: "Choose the correct word: The training session was very _____.",
      options: ["inform", "informative", "information", "informed"],
      correct: 1,
      timeLimit: 30
    },

    {
      id: 31,
      type: "mcq",
      text: "Find the next number: 2, 6, 12, 20, 30, ___",
      options: ["36", "40", "42", "44"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 32,
      type: "mcq",
      text: "If all bankers are graduates and some graduates are managers, which statement is definitely true?",
      options: [
        "All managers are bankers",
        "Some graduates are managers",
        "All graduates are bankers",
        "No bankers are managers"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 33,
      type: "mcq",
      text: "A customer is angry because a transfer failed. What should you do first?",
      options: [
        "Ignore the customer",
        "Explain bank policy immediately",
        "Listen and verify the complaint",
        "End the conversation"
      ],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 34,
      type: "mcq",
      text: "Choose the odd one out.",
      options: ["Laptop", "Keyboard", "Printer", "Banana"],
      correct: 3,
      timeLimit: 30
    },
    {
      id: 35,
      type: "mcq",
      text: "If today is Friday, what day will it be in 10 days?",
      options: ["Sunday", "Monday", "Tuesday", "Wednesday"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 36,
      type: "mcq",
      text: "A team missed its target due to poor communication. What is the best corrective action?",
      options: [
        "Ignore the issue",
        "Improve communication channels",
        "Punish everyone",
        "Reduce staff salaries"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 37,
      type: "mcq",
      text: "Rearrange the letters “LPAEN” to form a meaningful word.",
      options: ["PANEL", "PENAL", "PLANE", "Both A and C"],
      correct: 3,
      timeLimit: 30
    },
    {
      id: 38,
      type: "mcq",
      text: "A colleague takes credit for your work. What is the best response?",
      options: [
        "Start an argument publicly",
        "Report immediately without discussion",
        "Discuss professionally with the colleague",
        "Ignore permanently"
      ],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 39,
      type: "mcq",
      text: "Find the missing letter sequence: A, C, F, J, O, ___",
      options: ["T", "U", "V", "W"],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 40,
      type: "mcq",
      text: "Which action best demonstrates integrity?",
      options: [
        "Hiding mistakes",
        "Taking credit for others’ work",
        "Reporting errors honestly",
        "Ignoring company policy"
      ],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 41,
      type: "mcq",
      text: "A company’s sales dropped despite increased marketing. What should management investigate first?",
      options: [
        "Employee uniforms",
        "Product quality and customer feedback",
        "Office furniture",
        "Staff birthdays"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 42,
      type: "mcq",
      text: "If all pens are books and all books are bags, then all pens are:",
      options: ["Bags", "Pencils", "Tables", "Papers"],
      correct: 0,
      timeLimit: 30
    },
    {
      id: 43,
      type: "mcq",
      text: "You are assigned a task outside your expertise. What should you do?",
      options: [
        "Reject the task immediately",
        "Seek guidance and learn quickly",
        "Ignore instructions",
        "Delegate without approval"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 44,
      type: "mcq",
      text: "Choose the next number: 1, 4, 9, 16, 25, ___",
      options: ["30", "35", "36", "49"],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 45,
      type: "mcq",
      text: "A customer requests another customer’s account details. What should you do?",
      options: [
        "Share limited information",
        "Refuse and protect confidentiality",
        "Ask another staff member",
        "Ignore the customer"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 46,
      type: "mcq",
      text: "Which option best describes teamwork?",
      options: [
        "Competing against colleagues",
        "Working independently always",
        "Collaborating toward common goals",
        "Avoiding responsibility"
      ],
      correct: 2,
      timeLimit: 30
    },
    {
      id: 47,
      type: "mcq",
      text: "A manager gives unclear instructions. What should you do?",
      options: [
        "Assume details",
        "Ask for clarification",
        "Ignore the task",
        "Wait indefinitely"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 48,
      type: "mcq",
      text: "Find the odd number: 8, 16, 24, 33, 40",
      options: ["8", "16", "24", "33"],
      correct: 3,
      timeLimit: 30
    },
    {
      id: 49,
      type: "mcq",
      text: "Why is customer service important?",
      options: [
        "It wastes company time",
        "It improves customer satisfaction and loyalty",
        "It reduces communication",
        "It increases complaints"
      ],
      correct: 1,
      timeLimit: 30
    },
    {
      id: 50,
      type: "mcq",
      text: "If you discover an error in a financial report, what should you do first?",
      options: [
        "Hide the error",
        "Correct it quietly without informing anyone",
        "Report and correct the error promptly",
        "Ignore it if it seems small"
      ],
      correct: 2,
      timeLimit: 30
    }
  ]
};

window.QUIZ_CONFIG = QUIZ_CONFIG;
