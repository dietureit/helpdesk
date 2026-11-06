"""HD AI Issue Code registry: the seed codes, plus the readers that tagging and metrics use.

Once seeded, managers own the codes in Desk. Codes are retired, never deleted, and merged_into
rolls a retired code's history into another. Definitions and examples go into the tagging prompt,
so their Include/Exclude boundaries are what keep neighbouring codes apart.
"""

import frappe

DOCTYPE = "HD AI Issue Code"
FIELDS = [
    "code",
    "label",
    "kind",
    "family",
    "owner_department",
    "severity_floor",
    "is_food_safety",
    "definition",
    "examples",
]

CODES = [
    # Food safety: Complaint, Kitchen & QA
    {
        "code": "FS_ILLNESS",
        "label": "Illness after eating",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S1",
        "is_food_safety": 1,
        "definition": "Someone got ill after eating our food. Include: vomiting, diarrhoea, stomach pain or cramps, fever, food poisoning, or a clinic or hospital visit after a meal, even when the customer is unsure the food caused it. Exclude: allergic reactions (FS_ALLERGEN), and diet or health questions with no illness after a meal, such as belly fat or a dietitian's advice (ENQ_CALORIES_DIET).",
        "examples": "\n".join(
            [
                "Had cramps and vomiting all night after your lunch",
                "تسممت بعد غدا أمس ورحت الطوارئ",
                "صار عندي مغص وإسهال بعد ما أكلت الوجبة",
                "my husband felt sick right after the chicken wrap",
            ]
        ),
    },
    {
        "code": "FS_ALLERGEN",
        "label": "Allergen exposure or reaction",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S1",
        "is_food_safety": 1,
        "definition": "Someone ate an allergen they react to, or had an allergic reaction after a meal. Include: rash, itching, swelling or breathing trouble after a meal, whether or not the allergy was declared, and eating even a bite of a declared allergen such as nuts, sesame, shellfish or gluten. Exclude: an allergen noticed before eating with no reaction (NUT_EXCLUSION_IGNORED), and allergies mentioned while asking about plans (ENQ_CALORIES_DIET).",
        "examples": "\n".join(
            [
                "I'm allergic to nuts, ate the salad and my lips swelled up",
                "عندي حساسية من الروبيان وطلع لي طفح بعد العشا",
                "بنتي أكلت الحلى وفيه مكسرات وضاق نفسها",
                "3indi 7asasiya mn el sesame w akalt el sauce, jismi kilah 7ikka",
            ]
        ),
    },
    {
        "code": "FS_FOREIGN_HARD",
        "label": "Hard or sharp object in food",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S1",
        "is_food_safety": 1,
        "definition": "A hard or sharp object was in the food. Include: glass, metal, wire, staples, stones, hard plastic pieces, and sharp bone in a boneless dish. Exclude: hair, threads, paper or soft plastic film (FS_FOREIGN_SOFT), insects (FS_PEST), and a cracked container with nothing in the food (PKG_DAMAGED).",
        "examples": "\n".join(
            [
                "Found a small piece of glass in the rice",
                "لقيت سلك حديد في الدجاج",
                "عضيت على حصاة في العدس وانكسر ضرسي",
            ]
        ),
    },
    {
        "code": "FS_PEST",
        "label": "Insect or pest in food",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S1",
        "is_food_safety": 1,
        "definition": "An insect or other pest, or signs of one, was in or on the food or packaging. Include: live or dead insects, cockroaches, worms, larvae, ants, droppings. Exclude: hair or threads (FS_FOREIGN_SOFT), and software bugs in the app (TEC_CRASH).",
        "examples": "\n".join(
            [
                "There was a dead cockroach inside the salad box",
                "لقيت دودة في الخس",
                "فيه نمل داخل علبة الحلى",
            ]
        ),
    },
    {
        "code": "FS_UNDERCOOKED",
        "label": "Undercooked or raw food",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 1,
        "definition": "Meat, chicken, fish or eggs were raw, pink or not cooked through. Include: food the customer calls half cooked or not fully cooked, even without naming the dish. Exclude: hard rice, firm pasta, crunchy vegetables, and dry, tough or burnt food (QLT_TASTE_TEXTURE).",
        "examples": "\n".join(
            [
                "The chicken is still pink in the middle",
                "الدجاج مو مستوي من داخل ولونه وردي",
                "food came half cooked, not done at all",
                "اللحم نيّ ما استوى",
            ]
        ),
    },
    {
        "code": "FS_SPOILED",
        "label": "Spoiled, expired or off smell",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 1,
        "definition": "Food looked, smelled or tasted spoiled, or was past its date. Include: a sour or rotten smell, mould, slimy or fizzy food, curdled dairy, an expired date on the label. Exclude: food that is merely bland, salty or oily (QLT_TASTE_TEXTURE), and meals that arrived warm but were not spoiled (FS_TEMPERATURE).",
        "examples": "\n".join(
            [
                "The yogurt smells sour, I think it's gone off",
                "الأكل ريحته خايسة وطعمه حامض",
                "فيه عفن على الخبز",
                "the date on the box already passed",
            ]
        ),
    },
    {
        "code": "FS_TEMPERATURE",
        "label": "Chilled meal arrived warm",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 1,
        "definition": "Chilled meals arrived warm, or sat out in the heat before the customer got them. Include: warm bags, melted ice packs, meals left in the sun, a customer afraid to eat a warm meal. Exclude: late meals that were still cold (DLV_LATE; late and warm gets both codes), and questions about eating chilled meals cold (ENQ_MENU).",
        "examples": "\n".join(
            [
                "Meals came warm and the ice pack had melted",
                "الأكل وصل حار مو بارد، الثلج كله ذايب",
                "الكيس كان عند الباب في الشمس والأكل دافي",
                "el akl wasal 7ar, mo barid",
            ]
        ),
    },
    {
        "code": "FS_FOREIGN_SOFT",
        "label": "Hair or soft foreign matter",
        "kind": "Complaint",
        "family": "FS",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 1,
        "definition": "A hair or other soft foreign matter was in the food. Include: hair, threads, fibres, paper, sticker pieces, cling film, nylon or glove pieces. Exclude: glass, metal, stones, hard plastic or bone (FS_FOREIGN_HARD), and insects (FS_PEST).",
        "examples": "\n".join(
            [
                "Found a long hair in my pasta",
                "لقيت شعرة في السلطة",
                "فيه قطعة نايلون داخل الأكل",
            ]
        ),
    },
    # Nutrition: Complaint, Kitchen & QA
    {
        "code": "NUT_WRONG_PLAN",
        "label": "Meal breaks diet program",
        "kind": "Complaint",
        "family": "NUT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 0,
        "definition": "A meal did not fit the customer's diet program, such as keto, dairy and gluten free, diabetic, vegetarian or high protein. Include: a bag from another program, rice or bread on keto, sugary desserts on diabetic, meat on vegetarian. Exclude: a different dish that still fits the program (ACC_WRONG_MEAL), and one ingredient they had asked us to leave out (NUT_EXCLUSION_IGNORED).",
        "examples": "\n".join(
            [
                "I'm on keto but today's lunch came with rice and bread",
                "أنا مشتركة في خطة بدون جلوتين وجاني باستا",
                "my diabetic plan had a dessert full of sugar",
            ]
        ),
    },
    {
        "code": "NUT_EXCLUSION_IGNORED",
        "label": "Allergy or dislike ignored",
        "kind": "Complaint",
        "family": "NUT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S2",
        "is_food_safety": 0,
        "definition": "An ingredient the customer asked us to leave out, for an allergy or a dislike, was in the meal, but no allergen was eaten and nobody reacted. Include: disliked ingredients such as onion or mushroom coming back, and an allergen noticed before eating. Exclude: an allergen eaten or any allergic reaction (FS_ALLERGEN), and new requests to remove an ingredient (REQ_MEAL_SWAP).",
        "examples": "\n".join(
            [
                "I put no mushrooms on my profile and they're in every meal",
                "قلت لكم بدون بصل وللحين تحطونه",
                "مسجلة عندكم حساسية مكسرات وجاني لوز في الوجبة، انتبهت قبل لا آكل",
            ]
        ),
    },
    {
        "code": "NUT_MACROS",
        "label": "Calories or macros wrong",
        "kind": "Complaint",
        "family": "NUT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The customer says calories, protein or other macros do not match what was promised or labelled. Include: meals far above or below their plan's calories, protein too low, label or app numbers that look wrong. Exclude: calorie questions before buying (ENQ_CALORIES_DIET), and a portion that is just small (NUT_PORTION).",
        "examples": "\n".join(
            [
                "The label says 400 kcal but this is clearly much more",
                "خطتي ١٢٠٠ سعرة بس الوجبات واضح إنها أكثر",
                "the macros on the label don't match the app",
            ]
        ),
    },
    {
        "code": "NUT_PORTION",
        "label": "Portion too small",
        "kind": "Complaint",
        "family": "NUT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "A portion, or the protein in it, was too small or smaller than before. Include: little chicken or rice, half-empty boxes, meals that do not fill. Exclude: a whole meal or item missing (ACC_MISSING_ITEM), and calorie or macro numbers that look wrong (NUT_MACROS).",
        "examples": "\n".join(
            [
                "Portions got smaller, the box is half empty",
                "الكمية وايد قليلة ما تشبع",
                "قطعة الدجاج صغيرة مرة",
            ]
        ),
    },
    # Order accuracy: Complaint, Operations & Packing
    {
        "code": "ACC_WRONG_MEAL",
        "label": "Wrong meal delivered",
        "kind": "Complaint",
        "family": "ACC",
        "owner_department": "Operations & Packing",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The customer got a different dish or order than they chose. Include: someone else's bag, a dish they did not select, the same dish twice instead of two different ones. Exclude: a meal that breaks their diet program (NUT_WRONG_PLAN), and items missing from an otherwise right order (ACC_MISSING_ITEM).",
        "examples": "\n".join(
            [
                "Got the wrong meals in my bag this morning",
                "وصلني أكل مو حقي، الكيس عليه اسم غيري",
                "اخترت سالمون وجاني دجاج",
            ]
        ),
    },
    {
        "code": "ACC_MISSING_ITEM",
        "label": "Meal or item missing",
        "kind": "Complaint",
        "family": "ACC",
        "owner_department": "Operations & Packing",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Part of the day's order did not come. Include: a missing meal, snack, drink, sauce, dessert or cutlery, or fewer boxes than ordered. Exclude: the whole delivery not arriving (DLV_MISSED), and a small portion inside a box (NUT_PORTION).",
        "examples": "\n".join(
            [
                "Lunch came but the snack is missing",
                "ناقص الفطور اليوم",
                "وصلت وجبتين بس بدال ثلاث",
            ]
        ),
    },
    # Food quality: Complaint, Kitchen & QA
    {
        "code": "QLT_TASTE_TEXTURE",
        "label": "Taste, texture or look",
        "kind": "Complaint",
        "family": "QLT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "The food was safe but disappointing in taste, texture or look. Include: bland, salty, oily, too spicy, dry, soggy, tough, overcooked or burnt food, and food that looks unappetising. Exclude: raw, pink or half-cooked meat (FS_UNDERCOOKED), and sour, rotten-smelling or mouldy food (FS_SPOILED).",
        "examples": "\n".join(
            [
                "Way too much oil in today's dish",
                "الرز ناشف والدجاج وايد مالح",
                "الأكل ماله طعم",
                "el steak kan gawi mithl el ma6a6",
            ]
        ),
    },
    {
        "code": "QLT_REPETITION",
        "label": "Menu repetition",
        "kind": "Complaint",
        "family": "QLT",
        "owner_department": "Kitchen & QA",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "The customer is tired of the same dishes or finds too little variety. Include: the same meals every week, a menu that never changes, few choices on their plan. Exclude: the same dish sent twice by mistake (ACC_WRONG_MEAL), and ideas for new dishes without a complaint (FB_SUGGESTION).",
        "examples": "\n".join(
            [
                "Same meals every week, it's getting boring",
                "كل يوم نفس الأكل، ملّينا",
                "المنيو ما يتغير أبد",
            ]
        ),
    },
    # Packaging: Complaint, Operations & Packing
    {
        "code": "PKG_LEAK",
        "label": "Leak or spill",
        "kind": "Complaint",
        "family": "PKG",
        "owner_department": "Operations & Packing",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Food or liquid leaked or spilled from a container. Include: soup or sauce spilled in the bag, a lid not sealed, a wet or stained bag. Exclude: a cracked or crushed container with nothing spilled (PKG_DAMAGED).",
        "examples": "\n".join(
            [
                "The box leaked and sauce went all over the bag",
                "الشوربة انكبت في الكيس",
                "الغطا مو مسكّر زين والصوص سايل",
            ]
        ),
    },
    {
        "code": "PKG_DAMAGED",
        "label": "Damaged container or bag",
        "kind": "Complaint",
        "family": "PKG",
        "owner_department": "Operations & Packing",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Packaging arrived broken, crushed or opened. Include: cracked or crushed boxes, broken seals or lids, a torn bag, a damaged cooler bag. Exclude: spills (PKG_LEAK), pieces of packaging in the food (FS_FOREIGN_HARD or FS_FOREIGN_SOFT), views on packaging materials such as plastic (FB_SUGGESTION), and 'package' meaning a plan (ENQ_PLANS).",
        "examples": "\n".join(
            [
                "The box came crushed and the lid was cracked",
                "العلبة مكسورة والختم مفتوح",
                "الكيس واصل مشقوق",
            ]
        ),
    },
    {
        "code": "PKG_LABEL",
        "label": "Label missing or wrong",
        "kind": "Complaint",
        "family": "PKG",
        "owner_department": "Operations & Packing",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "A meal's label was missing, unreadable or wrong. Include: a wrong dish name, a missing date, missing ingredients or allergens, a label that does not match the box. Exclude: the wrong dish itself (ACC_WRONG_MEAL), and calorie numbers the customer doubts (NUT_MACROS).",
        "examples": "\n".join(
            [
                "No label on the box, no idea what's inside",
                "ما في تاريخ على العلب",
                "the allergen list is missing from the sticker",
            ]
        ),
    },
    # Delivery: Complaint, Delivery
    {
        "code": "DLV_LATE",
        "label": "Late delivery",
        "kind": "Complaint",
        "family": "DLV",
        "owner_department": "Delivery",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The delivery came after the promised time, or the customer is still waiting past it. Include: a late driver, meals arriving hours late, repeated lateness; add FS_TEMPERATURE as well when late meals arrived warm. Exclude: nothing arriving that day (DLV_MISSED), and asking what time a delivery will come (REQ_ADDRESS_TIME).",
        "examples": "\n".join(
            [
                "Delivery is an hour late again",
                "للحين ما وصل الأكل والساعة صارت ١١",
                "الغدا وصلني العصر، متأخر وايد",
                "el driver t2akhar sa3teen",
            ]
        ),
    },
    {
        "code": "DLV_MISSED",
        "label": "Delivery missed",
        "kind": "Complaint",
        "family": "DLV",
        "owner_department": "Delivery",
        "severity_floor": "S2",
        "is_food_safety": 0,
        "definition": "The day's delivery never arrived, leaving the customer without food. Include: no delivery on a paid day, a skipped day they never asked for, a driver who never came. Exclude: deliveries that came late (DLV_LATE) or with items missing (ACC_MISSING_ITEM).",
        "examples": "\n".join(
            [
                "Nobody came today and I have no food",
                "الأكل ما وصل اليوم وأنا دافعة",
                "ma wasalni shay il yom",
            ]
        ),
    },
    {
        "code": "DLV_WRONG_ADDRESS",
        "label": "Wrong address or location",
        "kind": "Complaint",
        "family": "DLV",
        "owner_department": "Delivery",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The meals went to the wrong place, or the driver could not find the customer. Include: an old address, the wrong building or zone, meals handed to someone else, a driver calling every day for the location. Exclude: asking to change the address (REQ_ADDRESS_TIME).",
        "examples": "\n".join(
            [
                "The driver delivered to my old address",
                "السواق راح عمارة ثانية",
                "كل يوم يتصل يسأل عن اللوكيشن",
            ]
        ),
    },
    {
        "code": "DLV_DRIVER_CONDUCT",
        "label": "Driver behaviour or handover",
        "kind": "Complaint",
        "family": "DLV",
        "owner_department": "Delivery",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The driver's behaviour or handover was a problem. Include: rude or careless drivers, throwing or dropping the bag, not calling, refusing to come up, leaving meals unattended; add FS_TEMPERATURE as well when the meals ended up warm. Exclude: rude support or sales staff (CS_RUDE).",
        "examples": "\n".join(
            [
                "The driver was rude and threw the bag at the door",
                "المندوب ما اتصل وخلّى الأكل عند الحارس",
                "السواق كلمني بأسلوب مو زين",
            ]
        ),
    },
    # App and tech: Complaint, Tech
    {
        "code": "TEC_LOGIN",
        "label": "Login, sign-up or OTP",
        "kind": "Complaint",
        "family": "TEC",
        "owner_department": "Tech",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The customer cannot log in, sign up or verify their account. Include: an OTP or code that never arrives, password problems, locked or duplicate accounts. Exclude: how to get or start using the app (ENQ_HOW_TO_ORDER).",
        "examples": "\n".join(
            [
                "The OTP never comes so I can't log in",
                "ما أقدر أسجل دخول، الكود ما يوصلني",
                "يقول الرقم مسجل من قبل",
            ]
        ),
    },
    {
        "code": "TEC_MEAL_SELECTION",
        "label": "App meal or day selection",
        "kind": "Complaint",
        "family": "TEC",
        "owner_department": "Tech",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Choosing meals, days or plan options in the app or on the website did not work. Include: choices not saving, different meals showing after choosing, pauses or skips the app got wrong, options that will not select. Exclude: plan rules such as the minimum days per week (ENQ_PLANS), and asking staff to pause or skip (REQ_PAUSE_RESUME).",
        "examples": "\n".join(
            [
                "I picked my meals but the app shows different ones",
                "paused two days and the app skipped the whole week",
                "التطبيق ما يخليني أختار غدا وعشا بس",
            ]
        ),
    },
    {
        "code": "TEC_PAYMENT",
        "label": "Online payment failed",
        "kind": "Complaint",
        "family": "TEC",
        "owner_department": "Tech",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Paying in the app, on the website or through a payment link failed. Include: declined cards, links that will not open, checkout errors, promo codes rejected at checkout. Exclude: money taken wrongly or twice (SUB_CHARGE), and questions about how to pay (ENQ_HOW_TO_ORDER).",
        "examples": "\n".join(
            [
                "Payment keeps failing at checkout",
                "رابط الدفع يطلع لي خطأ",
                "the discount code doesn't work when I pay",
            ]
        ),
    },
    {
        "code": "TEC_CRASH",
        "label": "App or website error",
        "kind": "Complaint",
        "family": "TEC",
        "owner_department": "Tech",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The app or website crashed, froze, showed an error or would not load. Include: the app closing, stuck screens, a step that will not continue, missing notifications. Exclude: login (TEC_LOGIN), meal selection (TEC_MEAL_SELECTION) and payment (TEC_PAYMENT) problems.",
        "examples": "\n".join(
            [
                "The app freezes on the same screen every time",
                "التطبيق يطلعني بروحه",
                "el app ma yeshtaghel, 7athafto w nazzalto mn jideed",
            ]
        ),
    },
    # Billing and subscription: Complaint, Finance
    {
        "code": "SUB_CHARGE",
        "label": "Wrong or double charge",
        "kind": "Complaint",
        "family": "SUB",
        "owner_department": "Finance",
        "severity_floor": "S2",
        "is_food_safety": 0,
        "definition": "Money was taken wrongly. Include: double charges, a wrong amount, charges after cancelling or pausing, an unexpected renewal. Exclude: an agreed refund that is late (SUB_REFUND_DELAY), payments that failed (TEC_PAYMENT), and discount questions, since Gulf Arabic خصم usually means a discount (ENQ_TRIAL_OFFER).",
        "examples": "\n".join(
            [
                "I was charged twice for the same month",
                "انسحب المبلغ مرتين من البطاقة",
                "جددتوا الاشتراك وخصمتوا مني بدون ما أطلب",
            ]
        ),
    },
    {
        "code": "SUB_REFUND_DELAY",
        "label": "Refund late or missing",
        "kind": "Complaint",
        "family": "SUB",
        "owner_department": "Finance",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "A refund or credit that was agreed is late, short or never arrived. Include: asking where the refund is, waiting weeks, a partial refund. Exclude: a new demand for money back after a problem (SUB_CANCEL_INTENT), and neutral questions on how refunds work (REQ_CANCEL).",
        "examples": "\n".join(
            [
                "Still waiting for the refund you promised two weeks ago",
                "وين فلوسي؟ قلتوا بترجعونها",
                "the refund came less than we agreed",
            ]
        ),
    },
    {
        "code": "SUB_CANCEL_INTENT",
        "label": "Unhappy, wants to cancel",
        "kind": "Complaint",
        "family": "SUB",
        "owner_department": "Finance",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "An unhappy customer says they will cancel, stop, not renew or switch, or demands their money back because of a problem. Include: threats to leave, refund demands after a bad experience, saying they will move to a competitor. Exclude: cancelling for neutral reasons such as travel, moving or budget (REQ_CANCEL).",
        "examples": "\n".join(
            [
                "After this I'm cancelling, I want my money back",
                "خلاص ما بجدد، كل أسبوع مشكلة",
                "بحوّل على شركة ثانية إذا استمر الوضع",
            ]
        ),
    },
    # Customer service: Complaint, Customer Service
    {
        "code": "CS_NO_RESPONSE",
        "label": "Nobody replied",
        "kind": "Complaint",
        "family": "CS",
        "owner_department": "Customer Service",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "The customer explicitly says nobody answered their messages or calls, or nobody called back. Include: no reply on WhatsApp or Instagram, unanswered calls, a promised call-back that never came. Exclude: chats that simply contain no agent replies, which never mean nobody replied, and a driver who did not come (DLV_LATE or DLV_MISSED).",
        "examples": "\n".join(
            [
                "Messaged you three times on WhatsApp, nobody answers",
                "محد يرد على التلفون",
                "قالوا بيتصلون فيني وما أحد اتصل",
            ]
        ),
    },
    {
        "code": "CS_WRONG_INFO",
        "label": "Wrong information from staff",
        "kind": "Complaint",
        "family": "CS",
        "owner_department": "Customer Service",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Staff or our messages gave wrong, conflicting or missing information, or promised something that did not happen. Include: wrong prices or plan details, different answers from different staff, 'nobody told me'. Exclude: a rude tone (CS_RUDE), and no reply at all (CS_NO_RESPONSE).",
        "examples": "\n".join(
            [
                "The price you sent me is different from the app",
                "ما أحد قال لي إن العرض خلص",
                "قالوا لي شي والحين تقولون شي ثاني",
            ]
        ),
    },
    {
        "code": "CS_RUDE",
        "label": "Rude or unhelpful staff",
        "kind": "Complaint",
        "family": "CS",
        "owner_department": "Customer Service",
        "severity_floor": "S3",
        "is_food_safety": 0,
        "definition": "Support or sales staff were rude, dismissive or unhelpful. Include: a bad tone, blaming the customer, refusing to help. Exclude: drivers (DLV_DRIVER_CONDUCT), and slow or missing replies (CS_NO_RESPONSE).",
        "examples": "\n".join(
            [
                "The agent was very rude to me on the phone",
                "الموظفة كلمتني بأسلوب مو زين",
                "they keep blaming me instead of helping",
            ]
        ),
    },
    # Requests: Request, Customer Service
    {
        "code": "REQ_PAUSE_RESUME",
        "label": "Pause, skip or resume",
        "kind": "Request",
        "family": "REQ",
        "owner_department": "Customer Service",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A customer asks to pause, freeze, skip, resume or move delivery days. Include: travel, adding skipped days to the end, holding meals while away. Exclude: the app pausing wrongly (TEC_MEAL_SELECTION), and prospects asking how pausing works (ENQ_PLANS).",
        "examples": "\n".join(
            [
                "Please pause my plan from Thursday, I'm travelling",
                "أبغى أجمّد الاشتراك أسبوع",
                "رجعوا التوصيل من بكرة الله يعافيكم",
            ]
        ),
    },
    {
        "code": "REQ_CANCEL",
        "label": "Cancel or not renew",
        "kind": "Request",
        "family": "REQ",
        "owner_department": "Customer Service",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A customer asks to cancel or not renew for a neutral reason, or asks how cancelling and refunds work. Include: moving, travel, reaching a goal, budget, a plain 'cancel it'. Exclude: cancelling because they are unhappy (SUB_CANCEL_INTENT).",
        "examples": "\n".join(
            [
                "Please cancel, I'm moving abroad next month",
                "ما بجدد الشهر الجاي لأني مسافرة",
                "If I cancel now, how is the rest refunded?",
            ]
        ),
    },
    {
        "code": "REQ_ADDRESS_TIME",
        "label": "Change address or delivery time",
        "kind": "Request",
        "family": "REQ",
        "owner_department": "Customer Service",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A customer asks to change or confirm their delivery address, location pin or time. Include: a one-off delivery to work, a new location, asking when today's or tomorrow's delivery comes. Exclude: complaints about late (DLV_LATE) or misdelivered (DLV_WRONG_ADDRESS) meals, and prospects asking where we deliver (ENQ_DELIVERY_AREA).",
        "examples": "\n".join(
            [
                "Can tomorrow's delivery come to my office instead?",
                "ممكن التوصيل يكون الساعة ٩ الصبح؟",
                "بغيّر اللوكيشن، برسل لكم الجديد",
            ]
        ),
    },
    {
        "code": "REQ_MEAL_SWAP",
        "label": "Swap a meal or ingredient",
        "kind": "Request",
        "family": "REQ",
        "owner_department": "Customer Service",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A customer asks to change a dish, swap a protein or remove an ingredient from now on. Include: beef to chicken, no onion from now on, adding an allergy or dislike to their profile. Exclude: complaints that an exclusion was ignored (NUT_EXCLUSION_IGNORED), and prospects asking about options (ENQ_MENU).",
        "examples": "\n".join(
            [
                "Please swap the beef dishes for chicken",
                "أبغى أبدل السناك بشي ثاني",
                "شيلوا الفطر من وجباتي",
            ]
        ),
    },
    # Enquiries: Enquiry, Marketing & Sales (questions only, never complaints)
    {
        "code": "ENQ_PRICE",
        "label": "Price question",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about what plans or meals cost, not a complaint. Include: monthly price, price per meal or day, price lists, price comparisons and objections from prospects. Exclude: complaints about a charge (SUB_CHARGE), and offers or discounts (ENQ_TRIAL_OFFER).",
        "examples": "\n".join(
            [
                "What's the monthly fee if I take two meals daily?",
                "الباقة الشهرية بكم؟ يا ليت ترسلون الأسعار",
                "kam el se3r lil bakej?",
            ]
        ),
    },
    {
        "code": "ENQ_PLANS",
        "label": "Plans and options",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about what plans exist and how they work. Include: plan types such as Classic, Keto or Ramadan, meals per day, days per week, durations, family or business lunch plans, schedules for shift workers; 'package' or بكج usually means a plan. Exclude: calories and diet needs (ENQ_CALORIES_DIET), price (ENQ_PRICE), and dishes (ENQ_MENU).",
        "examples": "\n".join(
            [
                "What's the difference between Classic and Keto?",
                "عندكم خطة لرمضان؟",
                "Can I take five days a week only? I work shifts",
            ]
        ),
    },
    {
        "code": "ENQ_CALORIES_DIET",
        "label": "Calories and diet needs",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about calories, macros or whether we suit a diet or health need. Include: plans by calories, protein amounts, diabetic, gluten or dairy free, vegetarian, pregnancy, weight goals, allergies declared before ordering. Exclude: complaints that delivered meals had wrong numbers (NUT_MACROS) or broke the diet (NUT_WRONG_PLAN).",
        "examples": "\n".join(
            [
                "Do you have a 1500 calorie plan with high protein?",
                "أبي خطة محسوبة السعرات عشان أنزل وزن",
                "My son can't eat seafood, can you do that?",
                "عندكم أكل لمرضى السكر؟",
            ]
        ),
    },
    {
        "code": "ENQ_DELIVERY_AREA",
        "label": "Delivery area and timing",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about whether, where or when we deliver. Include: areas such as Al Wakra, Al Khor or Lusail, delivery outside Qatar, delivery fees, time slots, the website saying it cannot deliver to their location. Exclude: existing customers changing their own address or time (REQ_ADDRESS_TIME), and complaints about deliveries (DLV_LATE, DLV_MISSED).",
        "examples": "\n".join(
            [
                "Do you deliver to Al Khor?",
                "تقدرون توصلون لين الوكرة؟",
                "What time do the meals usually arrive?",
            ]
        ),
    },
    {
        "code": "ENQ_TRIAL_OFFER",
        "label": "Trial, offers and discounts",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about trials, samples, offers, discounts or promo codes. Include: corporate or staff discounts, referral or influencer codes, free-month deals; in Gulf Arabic خصم usually means a discount. Exclude: a promo code failing at checkout (TEC_PAYMENT).",
        "examples": "\n".join(
            [
                "Any offers this month?",
                "في خصم؟ عندكم كود للموظفين؟",
                "Is there a trial week before I commit?",
            ]
        ),
    },
    {
        "code": "ENQ_MENU",
        "label": "Menu and ingredients",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about the dishes, menu, ingredients or how meals are prepared and kept. Include: menu requests, photos, oils and sugar used, desserts, shelf life, reheating, eating chilled meals cold. Exclude: complaints about the food (the matching complaint code), and diet suitability (ENQ_CALORIES_DIET).",
        "examples": "\n".join(
            [
                "Can you share this week's menu?",
                "يعني الأكل يوصل بارد وأسخنه؟",
                "What oil do you cook with?",
            ]
        ),
    },
    {
        "code": "ENQ_HOW_TO_ORDER",
        "label": "How to order or pay",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A question about how to sign up, renew, order or pay. Include: getting the app, ordering on the website or delivery apps, payment methods such as bank transfer, how to start, who to contact. Exclude: app problems (TEC_LOGIN, TEC_CRASH), and failed payments (TEC_PAYMENT).",
        "examples": "\n".join(
            [
                "Where do I sign up, the website or the app?",
                "Are you on Talabat or Snoonu?",
                "شلون أشترك؟ الدفع تحويل ولا كاش؟",
            ]
        ),
    },
    {
        "code": "ENQ_OTHER",
        "label": "Jobs, ads and non-customers",
        "kind": "Enquiry",
        "family": "ENQ",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "A message from someone who is not buying or using our service. Include: job seekers and CVs, influencer or agency pitches, suppliers, spam and fake account-verification messages, wrong numbers, general fitness questions. Exclude: any problem with food we sent, including free meals sent to creators (the matching complaint code).",
        "examples": "\n".join(
            [
                "I'm a content creator, would love to collaborate",
                "أبغى وظيفة سواق أو طباخ",
                "Your page broke our rules, verify your account here",
            ]
        ),
    },
    # Feedback: Feedback, Marketing & Sales (the plan names no owner; see the Demand section of the Brief)
    {
        "code": "FB_PRAISE",
        "label": "Praise",
        "kind": "Feedback",
        "family": "FB",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "The customer praises our food, service, staff or delivery. Include: loving a dish, thanks for good service, saying they recommend us. Exclude: courtesy around a complaint ('thanks, but the rice was dry' is QLT_TASTE_TEXTURE only), a thank-you that only ends a chat, and reactions to our posts or videos that say nothing about the food or service.",
        "examples": "\n".join(
            [
                "The new lentil soup is amazing, well done",
                "الأكل لذيذ الله يعطيكم العافية",
                "Five stars from me, the taste and the packing are perfect",
                "تسلم إيدينكم، أحلى أكل",
            ]
        ),
    },
    {
        "code": "FB_SUGGESTION",
        "label": "Suggestion",
        "kind": "Feedback",
        "family": "FB",
        "owner_department": "Marketing & Sales",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "An idea or wish to improve the food, menu, packaging, app or service, without a specific failure. Include: new dishes, more variety or more choice on delivery apps, less plastic packaging, app features. Exclude: requests about their own order (REQ_MEAL_SWAP, REQ_ADDRESS_TIME), and problems that happened (the matching complaint code).",
        "examples": "\n".join(
            [
                "It would be great to have more vegetarian dishes",
                "ياليت تضيفون حلويات بدون سكر",
                "Please use less plastic in the packaging",
            ]
        ),
    },
    # Sentinel: the tagger's "no code fits" answer; never offered as a listed code
    {
        "code": "NEW",
        "label": "New / unclassified",
        "kind": "Other",
        "family": "NEW",
        "owner_department": "Customer Service",
        "severity_floor": "S4",
        "is_food_safety": 0,
        "definition": "No listed code fits. Include: a problem, request or question that no other code covers, with a short proposed label. Exclude: anything a listed code covers, even partly.",
        "examples": "\n".join(
            [
                "Can you send me an invoice for my company?",
                "ممكن تاخذون الأكياس الفاضية؟",
            ]
        ),
    },
]


def seed() -> int:
    """Insert the codes that are missing and return how many. Existing codes are never touched."""
    # ponytail: seed never updates, so a better definition here reaches only fresh sites; ship a
    # patch that updates the named codes (where they still match the old text) if one must change.
    existing = set(frappe.get_all(DOCTYPE, pluck="name"))
    missing = [c for c in CODES if c["code"] not in existing]
    for c in missing:
        frappe.get_doc({"doctype": DOCTYPE, **c}).insert(ignore_permissions=True)
    return len(missing)


def active_codes() -> list[dict]:
    """Active codes for the tagger and the page, NEW excluded, ordered by family then code."""
    return frappe.get_all(
        DOCTYPE,
        filters={"status": "Active", "name": ["!=", "NEW"]},
        fields=FIELDS,
        order_by="family asc, code asc",
    )


def code_meta() -> dict[str, dict]:
    """Every code (retired ones and NEW too) by code, with "target": the code its counts roll up to."""
    meta = {r.code: r for r in frappe.get_all(DOCTYPE, fields=FIELDS + ["status", "merged_into"])}
    for r in meta.values():
        r["target"] = _target(r.code, meta)
    return meta


def _target(code: str, meta: dict) -> str:
    # The controller rejects merge cycles; if one slips through, the code keeps its own counts.
    # A merged_into that points at a missing code stops the chain at the last code that exists.
    seen, target = {code}, code
    while meta[target].get("merged_into") in meta:
        target = meta[target]["merged_into"]
        if target in seen:
            return code
        seen.add(target)
    return target


if __name__ == "__main__":
    # Self-check of the seed table and merge chains: env/bin/python -m helpdesk.ai_analysis.registry
    import re

    from helpdesk.ai_analysis import DEPARTMENTS

    # The plan's seed table: family -> (kind, owner); floors S3 for complaints, S4 otherwise, unless listed.
    plan = {
        "FS": ("Complaint", "Kitchen & QA"),
        "NUT": ("Complaint", "Kitchen & QA"),
        "ACC": ("Complaint", "Operations & Packing"),
        "QLT": ("Complaint", "Kitchen & QA"),
        "PKG": ("Complaint", "Operations & Packing"),
        "DLV": ("Complaint", "Delivery"),
        "TEC": ("Complaint", "Tech"),
        "SUB": ("Complaint", "Finance"),
        "CS": ("Complaint", "Customer Service"),
        "REQ": ("Request", "Customer Service"),
        "ENQ": ("Enquiry", "Marketing & Sales"),
        "FB": ("Feedback", "Marketing & Sales"),
        "NEW": ("Other", "Customer Service"),
    }
    floors = {
        "FS_ILLNESS": "S1",
        "FS_ALLERGEN": "S1",
        "FS_FOREIGN_HARD": "S1",
        "FS_PEST": "S1",
        "FS_UNDERCOOKED": "S2",
        "FS_SPOILED": "S2",
        "FS_TEMPERATURE": "S2",
        "FS_FOREIGN_SOFT": "S2",
        "NUT_WRONG_PLAN": "S2",
        "NUT_EXCLUSION_IGNORED": "S2",
        "QLT_TASTE_TEXTURE": "S4",
        "QLT_REPETITION": "S4",
        "DLV_MISSED": "S2",
        "SUB_CHARGE": "S2",
    }
    arabic = re.compile("[؀-ۿ]")
    names = [c["code"] for c in CODES]
    assert len(names) == len(set(names)) == 48, len(names)
    for c in CODES:
        code, kind, family = c["code"], c["kind"], c["family"]
        assert list(c) == FIELDS, code
        assert kind in {"Complaint", "Request", "Enquiry", "Feedback", "Other"}, code
        assert c["owner_department"] in DEPARTMENTS and c["severity_floor"] in {"S1", "S2", "S3", "S4"}, code
        assert code.split("_")[0] == family and (kind, c["owner_department"]) == plan[family], code
        assert c["severity_floor"] == floors.get(code, "S3" if kind == "Complaint" else "S4"), code
        assert c["is_food_safety"] == int(family == "FS"), code
        assert "Include:" in c["definition"] and "Exclude:" in c["definition"], code
        assert all(ref in names for ref in re.findall(r"\b[A-Z]{2,3}_[A-Z_]+\b", c["definition"])), code
        lines = c["examples"].splitlines()
        assert 2 <= len(lines) <= 4 and all(x.strip() for x in lines), code
        assert any(arabic.search(x) for x in lines) and any(not arabic.search(x) for x in lines), code

    links = {"A": "B", "B": "C", "C": None, "X": "Y", "Y": "X", "D": "GONE", "E": ""}
    meta = {k: {"merged_into": v} for k, v in links.items()}
    assert [_target(k, meta) for k in "ABCXYDE"] == ["C", "C", "C", "X", "Y", "D", "E"]
    print(f"registry ok: {len(CODES)} codes")
